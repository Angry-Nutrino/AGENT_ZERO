import asyncio
import hashlib
from .session_logger import slog


class ResourceLedger:
    """
    Per-task read-hash tracking and per-path write locks for concurrent task safety.

    Two mechanisms work together:
    1. Read-modify-write protection: records a hash of file content at read time,
       then validates it at write time. If another task wrote the file in between,
       returns a conflict error so Clara re-reads before overwriting.
    2. Pure-write exclusivity: asyncio.Lock per path, held only for the duration
       of the write call, so two pure writes to the same file cannot interleave.

    Both mechanisms are opt-in via task_id — background/system tasks pass no
    task_id and bypass all checks transparently.
    """

    def __init__(self):
        self._read_hashes: dict = {}       # (task_id, path) → hash_str
        self._write_locks: dict = {}       # path → asyncio.Lock
        self._meta_lock: asyncio.Lock | None = None  # protects _write_locks dict

    # ── internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _hash_file(path: str) -> str | None:
        """Read file from disk and return MD5 hash. None if file doesn't exist."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return hashlib.md5(f.read().encode("utf-8", errors="replace")).hexdigest()
        except Exception:
            return None

    async def _get_write_lock(self, path: str) -> asyncio.Lock:
        if self._meta_lock is None:
            self._meta_lock = asyncio.Lock()
        async with self._meta_lock:
            if path not in self._write_locks:
                self._write_locks[path] = asyncio.Lock()
            return self._write_locks[path]

    # ── public API ────────────────────────────────────────────────────────────

    def record_read(self, task_id: str, path: str, content: str = "") -> None:
        """Record hash of the file's ON-DISK state at read time. Called after read_file.

        Hashes the FILE, not the tool's returned string. DC's read_file prepends a
        '[Reading N lines from line M ...]' header + blank line, and an offset read returns
        only a slice — so hashing the returned text could NEVER equal check_write's hash of
        the on-disk file, and every read-then-write by the same task was false-blocked with
        "modified by another task" on byte-identical content. That made the read-modify-write
        guard both useless (a real concurrent edit was indistinguishable from the constant
        false positive) and costly (each occurrence burned a ReAct turn plus a bypass).
        Hashing the same source on both sides makes the comparison correct by construction.
        `content` is now only a fallback for an unreadable path. (2026-08-07, from the
        08-07 evening drill Q23 flag.)
        """
        h = self._hash_file(path)
        if h is None:
            h = self._hash(content)
        self._read_hashes[(task_id, path)] = h
        slog.debug(f"   [Ledger] task {task_id[:8]} read '{path}' @ {h[:8]}")

    def check_write(self, task_id: str, path: str) -> tuple:
        """
        Before a write: check whether the file changed since this task last read it.
        Returns (ok: bool, reason: str).
          ok=True, reason=""   → safe to proceed (acquire write lock and write)
          ok=False, reason=... → file modified by another task; Clara must re-read first
        """
        key = (task_id, path)
        if key not in self._read_hashes:
            return True, ""  # pure write — no prior read by this task, skip hash check

        stored = self._read_hashes[key]
        current = self._hash_file(path)

        if current is None:
            return True, ""  # file doesn't exist yet — new file, no conflict possible

        if current != stored:
            slog.warning(
                f"   [Ledger] CONFLICT: task {task_id[:8]} write to '{path}' blocked — "
                f"file changed since read (stored={stored[:8]}, current={current[:8]})"
            )
            return False, (
                f"Write blocked: '{path}' was modified by another task since you last "
                f"read it. Re-read the file first to get the current content, then write."
            )

        return True, ""

    async def acquire_write(self, path: str, task_id: str = "") -> asyncio.Lock:
        """
        Acquire exclusive write lock for path. Caller MUST release in a try/finally.
        Suspends the coroutine cooperatively if another task holds the lock.
        """
        lock = await self._get_write_lock(path)
        await lock.acquire()
        slog.debug(f"   [Ledger] task {task_id[:8]} acquired write lock '{path}'")
        return lock

    def release_task(self, task_id: str) -> None:
        """Remove all read hashes for a completed or failed task."""
        keys = [k for k in self._read_hashes if k[0] == task_id]
        for k in keys:
            del self._read_hashes[k]
        if keys:
            slog.debug(f"   [Ledger] task {task_id[:8]} released {len(keys)} read hash(es)")


# Module-level singleton — shared across all concurrent tasks
resource_ledger = ResourceLedger()


if __name__ == "__main__":
    # ── self-test (no backend) — run as `python -m core_logic.resource_ledger` ─
    # (module form required: this file uses a relative import for slog.)
    # Guards the 2026-08-07 fix: record_read must hash the FILE, not the tool's
    # returned string, or every read-then-write is false-blocked.
    import os, tempfile

    fails = []

    def check(label, cond):
        if not cond:
            fails.append(f"  FAILED: {label}")

    tmpdir = tempfile.mkdtemp(prefix="ledger_selftest_")
    p = os.path.join(tmpdir, "sample.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write("line one\nline two\nline three\n")

    L = ResourceLedger()

    # DC read_file returns a header + blank line + body — NOT the raw file bytes.
    dc_output = "[Reading 3 lines from line 0 of sample.py]\n\nline one\nline two\nline three\n"

    # 1. read (via the real tool-output shape) then write, file unchanged → ALLOWED.
    #    This is the regression: before the fix this returned ok=False every time.
    L.record_read("task-a", p, dc_output)
    ok, reason = L.check_write("task-a", p)
    check("unchanged file after read must NOT be blocked", ok is True and reason == "")

    # 2. a genuine external modification → BLOCKED.
    with open(p, "w", encoding="utf-8") as f:
        f.write("line one\nline two CHANGED\nline three\n")
    ok, reason = L.check_write("task-a", p)
    check("externally modified file must be blocked", ok is False)
    check("block reason names the guard", "Write blocked" in reason)

    # 3. pure write — no prior read by this task → ALLOWED (hash check skipped).
    ok, reason = L.check_write("task-b", p)
    check("pure write with no prior read must be allowed", ok is True)

    # 4. partial (offset) read hashes the whole file, so a slice does not false-block.
    L2 = ResourceLedger()
    L2.record_read("task-c", p, "[Reading 1 lines from line 1 of sample.py]\n\nline two CHANGED\n")
    ok, _ = L2.check_write("task-c", p)
    check("offset/partial read must not false-block", ok is True)

    # 5. unreadable path → falls back to hashing content, and a missing file never blocks.
    missing = os.path.join(tmpdir, "does_not_exist.txt")
    L2.record_read("task-d", missing, "whatever")
    ok, _ = L2.check_write("task-d", missing)
    check("missing file must not block", ok is True)

    # 6. release_task drops this task's hashes only.
    L.record_read("task-e", p, dc_output)
    L.release_task("task-a")
    check("release_task cleared the releasing task", ("task-a", p) not in L._read_hashes)
    check("release_task left other tasks alone", ("task-e", p) in L._read_hashes)

    for fn in os.listdir(tmpdir):
        os.remove(os.path.join(tmpdir, fn))
    os.rmdir(tmpdir)

    if fails:
        print("resource_ledger self-test FAILED:")
        print("\n".join(fails))
        raise SystemExit(1)
    print("resource_ledger self-test: 8 checks passed.")
