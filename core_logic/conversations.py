"""
conversations.py — persistent, cross-channel message store (Brief 43.3, Wave 1).

Clara does not server-persist messages today (only the browser's localStorage). This is the durable
archive + the feed for the unified "master console": EVERY user+Clara exchange across ALL channels
(interface / telegram / voice / harness) is appended here, tagged with its source, so the interface can
show ONE continuous thread with source badges (Alkama's chosen design — one thread, not two tabs).

Distinct from crud.recent_exchanges (a capped working-memory window for coherence). This is the full
history + UI source. Per-day JSONL (append-only, crash-tolerant, human-readable). Lives OUTSIDE logs/ so
the Brief-37 janitor (which prunes logs/traces/benchmarks) never deletes conversation history.

Standalone + defensive (never raises into the caller). Wiring into process_request / the WS + Telegram
paths and a /history endpoint is done in the validatable pass; this module is the tested storage layer.
Self-test: `python core_logic/conversations.py`.
"""
import os
import json
import uuid
import threading
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DIR = os.path.join(_ROOT, "conversations")
_lock = threading.Lock()

VALID_SOURCES = ("interface", "telegram", "voice", "harness", "system")
VALID_ROLES = ("user", "clara")


def _day_file(d, when):
    return os.path.join(d, f"{when.strftime('%Y-%m-%d')}.jsonl")


def record_message(source, role, text, message_id="", ts=None, conv_dir=None):
    """Append one message to today's JSONL. Never raises — a logging hiccup must not cost a turn."""
    try:
        d = conv_dir or _DEFAULT_DIR
        os.makedirs(d, exist_ok=True)
        when = ts or datetime.now()
        rec = {
            "ts": when.isoformat(timespec="seconds"),
            "source": str(source),
            "role": str(role),
            "text": "" if text is None else str(text),
            "message_id": str(message_id or ""),
        }
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with _lock:
            with open(_day_file(d, when), "a", encoding="utf-8") as f:
                f.write(line)
        return True
    except Exception:
        return False


def record_exchange(source, user_text, clara_text, message_id="", conv_dir=None):
    """Append a user turn + Clara's reply as an ordered pair (one call so display order is stable).
    Used by process_request's write-through. Never raises."""
    record_message(source, "user", user_text, message_id=message_id, conv_dir=conv_dir)
    record_message(source, "clara", clara_text, message_id=message_id, conv_dir=conv_dir)


_HELD_FILE = "whatsapp_held.jsonl"
_HELD_CAP = 500   # the watcher runs 24/7 and catches spam — bound the archive like everything else
VALID_HELD_STATUS = ("unread", "read")   # read is a LABEL (engage-to-read), never a delete


def _held_path(conv_dir=None):
    return os.path.join(conv_dir or _DEFAULT_DIR, _HELD_FILE)


def _ensure_held_migrated(path):
    """Read all held rows, back-filling id + status on any legacy row (pre-read/unread schema).
    Idempotent: rewrites the file ONLY when a row was missing either field, so once upgraded reads are
    pure. A legacy row = never-labelled = 'unread'. Caller must hold _lock. Returns the rows; never raises."""
    try:
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(ln) for ln in f if ln.strip()]
        changed = False
        for r in rows:
            if not r.get("id"):
                r["id"] = uuid.uuid4().hex[:12]
                changed = True
            if r.get("status") not in VALID_HELD_STATUS:
                r["status"] = "unread"
                changed = True
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return rows
    except Exception:
        return []


def record_whatsapp_held(sender, text, ts=None, conv_dir=None):
    """Held (non-priority) WhatsApp messages go HERE — a separate quiet archive, NOT the main
    conversation feed the UI renders. Keeps the Clara chat clean (Alkama's 'only Shobha breaks
    through; everyone else held') while preserving a 'what did I miss on WhatsApp?' record.
    Each row carries a stable `id` + `status` ('unread' on arrival; flipped to 'read' only when Alkama
    engages with it — engage-to-read). Bounded to the most recent _HELD_CAP entries so a 24/7 spam feed
    can't grow it forever. Never raises."""
    try:
        d = conv_dir or _DEFAULT_DIR
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, _HELD_FILE)
        rec = {
            "id": uuid.uuid4().hex[:12],
            "ts": (ts or datetime.now()).isoformat(timespec="seconds"),
            "sender": str(sender),
            "text": "" if text is None else str(text),
            "status": "unread",
        }
        with _lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            # Bound the archive: once it drifts past the cap, keep only the most recent _HELD_CAP.
            try:
                with open(path, encoding="utf-8") as f:
                    lines = f.readlines()
                if len(lines) > _HELD_CAP:
                    with open(path, "w", encoding="utf-8") as f:
                        f.writelines(lines[-_HELD_CAP:])
            except Exception:
                pass
        return True
    except Exception:
        return False


def read_whatsapp_held(limit=50, status=None, conv_dir=None):
    """Return held WhatsApp messages (oldest→newest). `status` filters to 'unread' or 'read'
    (None/'all' = both). `limit<=0` returns the whole filtered archive (used by a sender drill-down
    that must see everything, not just the recent tail). Lazily migrates legacy rows to carry
    id+status. Never raises."""
    try:
        with _lock:
            rows = _ensure_held_migrated(_held_path(conv_dir))
        if status in VALID_HELD_STATUS:
            rows = [r for r in rows if r.get("status", "unread") == status]
        if limit and limit > 0:
            rows = rows[-limit:]
        return rows
    except Exception:
        return []


def mark_whatsapp_read(ids=None, sender=None, conv_dir=None):
    """Flip held messages from unread→read (engage-to-read). Match by exact `ids` (precise: the rows
    just shown to Alkama) and/or `sender` (substring, case-insensitive: an explicit 'mark all from X
    read'). With neither, nothing is marked (so a bare call can't silently clear the inbox). Read is a
    LABEL — the row is never removed and stays fully queryable (status='all' / by sender) any number of
    times. Returns the count newly marked. Never raises."""
    try:
        id_set = {str(i) for i in ids} if ids else None
        snd = sender.lower().strip() if sender else None
        if id_set is None and not snd:
            return 0
        path = _held_path(conv_dir)
        n = 0
        with _lock:
            rows = _ensure_held_migrated(path)
            for r in rows:
                if r.get("status") == "read":
                    continue
                if (id_set is not None and str(r.get("id")) in id_set) or \
                   (snd and snd in str(r.get("sender", "")).lower()):
                    r["status"] = "read"
                    n += 1
            if n:
                with open(path, "w", encoding="utf-8") as f:
                    for r in rows:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return n
    except Exception:
        return 0


def load_recent(limit=200, sources=None, include_harness=False, conv_dir=None):
    """Return the most recent `limit` messages (oldest-first for display), newest day files first.
    `sources` filters to a set; by default harness traffic is EXCLUDED (the console hides drill noise
    unless toggled). Never raises — returns [] on any error."""
    try:
        d = conv_dir or _DEFAULT_DIR
        if not os.path.isdir(d):
            return []
        # EXCLUDE the held archive — it is the QUIET store (non-priority WhatsApp), deliberately
        # kept out of the chat feed. Without this, held spam leaks back into /history on reload and
        # the whole "only Shobha breaks through" design is defeated.
        files = sorted((f for f in os.listdir(d)
                        if f.endswith(".jsonl") and f != _HELD_FILE), reverse=True)
        out = []
        for fname in files:
            rows = []
            try:
                with open(os.path.join(d, fname), encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            rows.append(json.loads(line))
            except Exception:
                continue
            # prepend older file's rows ahead of newer (we walk newest file first, build backwards)
            out = rows + out
            if len(out) >= limit * 2:  # enough collected; trim below
                break
        if sources is not None:
            out = [r for r in out if r.get("source") in sources]
        elif not include_harness:
            out = [r for r in out if r.get("source") != "harness"]
        return out[-limit:]
    except Exception:
        return []


if __name__ == "__main__":
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="conv_selftest_")
    try:
        assert record_message("interface", "user", "hello", "m1", conv_dir=tmp)
        assert record_message("interface", "clara", "hi there", "m1", conv_dir=tmp)
        assert record_message("telegram", "user", "from tg", "m2", conv_dir=tmp)
        assert record_message("harness", "user", "drill q", "h1", conv_dir=tmp)
        # default load excludes harness
        rows = load_recent(conv_dir=tmp)
        assert len(rows) == 3, f"expected 3 (harness excluded), got {len(rows)}"
        assert rows[0]["text"] == "hello" and rows[-1]["text"] == "from tg", "order wrong"
        assert all(r["source"] != "harness" for r in rows), "harness leaked into default load"
        # explicit include_harness
        rows_all = load_recent(include_harness=True, conv_dir=tmp)
        assert len(rows_all) == 4, f"expected 4 with harness, got {len(rows_all)}"
        # source filter
        tg = load_recent(sources=("telegram",), conv_dir=tmp)
        assert len(tg) == 1 and tg[0]["source"] == "telegram", "source filter wrong"
        # bad input never raises
        assert record_message("interface", "user", None, conv_dir=tmp) is True

        # ── held archive (non-priority WhatsApp): write/read + cap + chat-feed isolation ──
        assert record_whatsapp_held("Luxury Souq", "Rolex 64000", conv_dir=tmp)
        assert record_whatsapp_held("+91 999", "is this Alkama?", conv_dir=tmp)
        held = read_whatsapp_held(conv_dir=tmp)
        assert len(held) == 2 and held[-1]["sender"] == "+91 999", "held read wrong"
        # CRITICAL: held archive must NOT leak into the chat feed (/history)
        chat = load_recent(include_harness=True, conv_dir=tmp)
        assert all("Rolex 64000" != r.get("text") for r in chat), "held leaked into chat feed!"
        assert not any(r.get("sender") for r in chat), "held record (has 'sender') reached chat feed!"

        # ── read/unread (engage-to-read) ──
        un = read_whatsapp_held(status="unread", conv_dir=tmp)
        assert len(un) == 2 and all(r["status"] == "unread" and r.get("id") for r in un), "new held not unread/ided"
        souq_ids = [r["id"] for r in un if r["sender"] == "Luxury Souq"]
        assert mark_whatsapp_read(ids=souq_ids, conv_dir=tmp) == 1, "mark by id should flip exactly 1"
        assert mark_whatsapp_read(ids=souq_ids, conv_dir=tmp) == 0, "re-marking an already-read row is a no-op"
        assert len(read_whatsapp_held(status="unread", conv_dir=tmp)) == 1, "one unread should remain"
        assert len(read_whatsapp_held(status="read", conv_dir=tmp)) == 1, "one read should exist"
        assert len(read_whatsapp_held(conv_dir=tmp)) == 2, "read is a LABEL — nothing removed (all still queryable)"
        assert mark_whatsapp_read(sender="+91", conv_dir=tmp) == 1, "mark by sender should flip the remaining unread"
        assert read_whatsapp_held(status="unread", conv_dir=tmp) == [], "inbox now all read"
        assert mark_whatsapp_read(conv_dir=tmp) == 0, "bare mark (no ids, no sender) must be a no-op"
        # legacy migration: a pre-schema row (no id/status) reads as unread and is back-filled
        with open(_held_path(tmp), "a", encoding="utf-8") as _f:
            _f.write(json.dumps({"ts": "2026-06-01T09:00:00", "sender": "Legacy", "text": "old row"}) + "\n")
        legacy = [r for r in read_whatsapp_held(conv_dir=tmp) if r["sender"] == "Legacy"]
        assert legacy and legacy[0]["status"] == "unread" and legacy[0].get("id"), "legacy row not migrated"

        # cap: archive is bounded to _HELD_CAP
        for i in range(_HELD_CAP + 25):
            record_whatsapp_held("spam", f"msg {i}", conv_dir=tmp)
        capped = read_whatsapp_held(limit=10000, conv_dir=tmp)
        assert len(capped) == _HELD_CAP, f"held archive not capped: {len(capped)} > {_HELD_CAP}"
        assert capped[-1]["text"] == f"msg {_HELD_CAP + 24}", "cap kept the wrong (not most-recent) tail"
        print("conversations self-test: all cases passed.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
