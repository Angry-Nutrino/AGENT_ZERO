"""
core_logic/admissibility.py — Pre-execution admissibility gate (BRIEF_54, Phase 0).

The layer between "the agent decided to act" and "the action fires": before a MUTATING tool
dispatches, the gate builds an ABSTRACT governance envelope, asks an adapter for a verdict
(ALLOW / REVIEW / DENY), and records every decision to a local audit ledger. The agent can no
longer act with zero external record — robert bezdan's axiom ("the agent should not self-authorize
critical actions; the evidence should exist BEFORE execution") is the design principle.

Phase 0 scope (Alkama greenlit 2026-07-02): the gate + the `noop`/`policy` local adapters + the
ledger. The `partner_a` remote adapter (the governance partner's pilot, contract in BRIEF_54 §7) is a follow-up —
this module is adapter-shaped so it bolts on without re-plumbing.

Flags (core_logic/.env; all safe-by-default):
    ADMISSIBILITY_GATE    on|off        (default OFF — gate is a no-op)
    ADMISSIBILITY_ADAPTER noop|policy   (default noop — always ALLOW, observe only)
    ADMISSIBILITY_MODE    shadow|enforce(default shadow — verdicts LOGGED, never block)
    ADMISSIBILITY_FAIL    open|closed   (default open — an adapter crash ALLOWS + ledgers the outage;
                                         a personal assistant must not brick on a gate failure)

PRIVACY FLOOR (load-bearing — same posture as the confirmed partner A contract):
- The envelope is ABSTRACT: tool, intent, target_type, sha256(path basename), arg summary
  (keys + value lengths ONLY), classification, mode. Raw file contents / full paths / conversation
  NEVER enter the envelope. Local adapters additionally receive local_ctx (the real path) which
  NEVER leaves the machine; a remote adapter gets the envelope alone.
- The ledger (core_logic/admissibility_ledger.json) is local telemetry — gitignored, watcher-ignored.

Known v1 hole (documented, not hidden): python_repl executes arbitrary code and can write files
around the gate. Native tools are exempt in Phase 0 (the drill hammers python_repl; gating it costs
latency on every compute). Revisit when enforcement matters.

Self-test (no backend, no env pollution): python core_logic/admissibility.py
"""
import os
import json
import time
import uuid
import hashlib
import tempfile
from datetime import datetime

_LEDGER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admissibility_ledger.json")
_POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admissibility_policy.json")
_MAX_LEDGER = 2000

ALLOW, REVIEW, DENY = "ALLOW", "REVIEW", "DENY"

# MCP tools that mutate state — the gate's scope. Reads/searches never gate (latency floor).
# Pattern fallback catches future mutating tools conservatively.
MUTATING_TOOLS = frozenset({
    "write_file", "create_directory", "move_file", "edit_block",
    "start_process", "interact_with_process", "kill_process", "force_terminate",
})
_MUTATING_HINTS = ("write", "create", "move", "delete", "remove", "kill", "terminate", "edit_")

_INTENTS = {
    "write_file": "create_or_modify_file", "edit_block": "modify_file",
    "create_directory": "create_directory", "move_file": "move_or_rename",
    "start_process": "execute_process", "interact_with_process": "execute_process",
    "kill_process": "terminate_process", "force_terminate": "terminate_process",
}


def gate_enabled() -> bool:
    return os.getenv("ADMISSIBILITY_GATE", "").strip().lower() in ("on", "1", "true", "yes")


def gate_mode() -> str:
    m = os.getenv("ADMISSIBILITY_MODE", "shadow").strip().lower()
    return m if m in ("shadow", "enforce") else "shadow"


def _fail_open() -> bool:
    return os.getenv("ADMISSIBILITY_FAIL", "open").strip().lower() != "closed"


def is_mutating(tool_name: str) -> bool:
    t = (tool_name or "").lower()
    return t in MUTATING_TOOLS or any(h in t for h in _MUTATING_HINTS)


def build_envelope(tool_name: str, args: dict, task_id=None) -> dict:
    """The ABSTRACT governance envelope — metadata only, never content (see PRIVACY FLOOR)."""
    args = args if isinstance(args, dict) else {}
    path = str(args.get("path") or args.get("source") or args.get("command") or "")
    basename = os.path.basename(path.rstrip("\\/")) if path else ""
    arg_summary = {k: f"<{type(v).__name__}:{len(str(v))}ch>" for k, v in args.items()}
    return {
        "agent_id": os.getenv("ADMISSIBILITY_AGENT_ID", "clara-01"),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "nonce": uuid.uuid4().hex,
        "signature": "",                       # local phase 0 — signing lands with the partner_a adapter
        "tool": tool_name,
        "intent": _INTENTS.get(tool_name, "mutate_state"),
        "target_type": "process" if "process" in (tool_name or "") else "local_file",
        "target_path_hash": hashlib.sha256(basename.encode()).hexdigest()[:16] if basename else "",
        "arg_summary": arg_summary,            # keys + value LENGTHS only — never values
        "data_classification": "non_sensitive",
        "execution_mode": "sandbox/eval",
        "task_id": str(task_id or ""),
    }


# ── Adapters (evaluate(envelope, local_ctx) -> (verdict, reason)) ─────────────────

def _noop_evaluate(envelope, local_ctx):
    return ALLOW, "noop adapter (observe only)"


def _load_policy() -> dict:
    try:
        with open(_POLICY_PATH, encoding="utf-8") as f:
            p = json.load(f)
        return p if isinstance(p, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _policy_evaluate(envelope, local_ctx):
    """Alkama-authored local rules — the agent doesn't self-authorize; the written policy does.
    local_ctx carries the RAW path (never leaves the machine)."""
    p = _load_policy()
    tool = envelope.get("tool", "")
    if tool in (p.get("deny_tools") or []):
        return DENY, f"policy: tool '{tool}' is denied"
    if tool in (p.get("review_tools") or []):
        return REVIEW, f"policy: tool '{tool}' requires review"
    raw_path = str((local_ctx or {}).get("path", ""))
    for sub in (p.get("deny_path_substrings") or []):
        if sub and sub.lower() in raw_path.lower():
            return DENY, f"policy: path matches denied pattern '{sub}'"
    default = str(p.get("default", "allow")).upper()
    return (default if default in (ALLOW, REVIEW, DENY) else ALLOW), "policy: default"


_ADAPTERS = {"noop": _noop_evaluate, "policy": _policy_evaluate}


def _adapter():
    name = os.getenv("ADMISSIBILITY_ADAPTER", "noop").strip().lower()
    return name if name in _ADAPTERS else "noop", _ADAPTERS.get(name, _noop_evaluate)


# ── The gate ──────────────────────────────────────────────────────────────────────

def gate(tool_name: str, args: dict, task_id=None) -> dict:
    """Adjudicate one proposed action. Returns a decision dict:
        {verdict, reason, receipt_id, adapter, mode, enforced}
    Fast path: gate off / non-mutating tool → ALLOW without envelope or ledger.
    Sync + local by design in Phase 0 (µs) — goes async when a remote adapter lands."""
    if not gate_enabled() or not is_mutating(tool_name):
        return {"verdict": ALLOW, "reason": "gate off or non-mutating", "receipt_id": "",
                "adapter": "", "mode": gate_mode(), "enforced": False}
    name, evaluate = _adapter()
    envelope = build_envelope(tool_name, args, task_id)
    local_ctx = {"path": str((args or {}).get("path", ""))}
    try:
        verdict, reason = evaluate(envelope, local_ctx)
    except Exception as e:
        verdict = ALLOW if _fail_open() else DENY
        reason = f"adapter '{name}' failed ({e}) — fail-{'open' if _fail_open() else 'closed'}"
    receipt = uuid.uuid4().hex[:12]
    mode = gate_mode()
    enforced = (mode == "enforce") and verdict in (REVIEW, DENY)
    _ledger_append({
        "receipt_id": receipt, "verdict": verdict, "reason": reason, "adapter": name,
        "mode": mode, "enforced": enforced, "envelope": envelope,
    })
    return {"verdict": verdict, "reason": reason, "receipt_id": receipt,
            "adapter": name, "mode": mode, "enforced": enforced}


def _ledger_append(entry: dict) -> None:
    """Atomic ring append (mkstemp → fsync → os.replace — the crud._save_memory pattern). Never raises."""
    try:
        try:
            with open(_LEDGER_PATH, encoding="utf-8") as f:
                data = json.load(f)
            rows = data.get("decisions") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                rows = []
        except (OSError, json.JSONDecodeError):
            rows = []
        rows.append(entry)
        rows = rows[-_MAX_LEDGER:]
        fd, tmp = tempfile.mkstemp(prefix=".admissibility_ledger.", suffix=".tmp",
                                   dir=os.path.dirname(_LEDGER_PATH) or ".")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "decisions": rows}, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _LEDGER_PATH)
    except Exception:
        pass


# ── Self-test ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import shutil
    fails = []
    _saved = {k: os.environ.get(k) for k in
              ("ADMISSIBILITY_GATE", "ADMISSIBILITY_ADAPTER", "ADMISSIBILITY_MODE", "ADMISSIBILITY_FAIL")}
    tmpdir = tempfile.mkdtemp(prefix="adm_test_")
    _real_ledger, _real_policy = _LEDGER_PATH, _POLICY_PATH
    _LEDGER_PATH = os.path.join(tmpdir, "ledger.json")
    _POLICY_PATH = os.path.join(tmpdir, "policy.json")

    # (1) OFF by default → ALLOW, nothing ledgered.
    os.environ.pop("ADMISSIBILITY_GATE", None)
    d = gate("write_file", {"path": "x.txt", "content": "hi"})
    if d["verdict"] != ALLOW or d["receipt_id"] or os.path.exists(_LEDGER_PATH):
        fails.append("gate must be a silent no-op when off")

    os.environ["ADMISSIBILITY_GATE"] = "on"
    # (2) Non-mutating tools never gate.
    if gate("read_file", {"path": "x.txt"})["receipt_id"]:
        fails.append("read_file must not gate")
    if not is_mutating("write_file") or is_mutating("start_search"):
        fails.append("classification wrong")

    # (3) noop shadow: ALLOW + ledgered + envelope is ABSTRACT (no content/full path).
    os.environ["ADMISSIBILITY_ADAPTER"] = "noop"
    os.environ["ADMISSIBILITY_MODE"] = "shadow"
    d = gate("write_file", {"path": "E:\\secret\\dir\\notes.txt", "content": "SECRET BODY"}, task_id="t1")
    led = json.load(open(_LEDGER_PATH, encoding="utf-8"))["decisions"]
    env_str = json.dumps(led[-1]["envelope"])
    if d["verdict"] != ALLOW or not d["receipt_id"] or led[-1]["receipt_id"] != d["receipt_id"]:
        fails.append("noop shadow must ALLOW + ledger with matching receipt")
    if "SECRET BODY" in env_str or "E:\\\\secret" in env_str or "secret\\\\dir" in env_str:
        fails.append("PRIVACY: envelope leaked content or full path")
    if d["enforced"]:
        fails.append("shadow must never enforce")

    # (4) policy adapter: deny_tools / review_tools / path substring / default all honored.
    json.dump({"deny_tools": ["kill_process"], "review_tools": ["start_process"],
               "deny_path_substrings": ["C:\\Windows"], "default": "allow"},
              open(_POLICY_PATH, "w", encoding="utf-8"))
    os.environ["ADMISSIBILITY_ADAPTER"] = "policy"
    if gate("kill_process", {"pid": 1})["verdict"] != DENY:
        fails.append("policy deny_tools not honored")
    if gate("start_process", {"command": "ls"})["verdict"] != REVIEW:
        fails.append("policy review_tools not honored")
    if gate("write_file", {"path": "C:\\Windows\\evil.txt", "content": "x"})["verdict"] != DENY:
        fails.append("policy deny_path_substrings not honored")
    if gate("write_file", {"path": "E:\\ok.txt", "content": "x"})["verdict"] != ALLOW:
        fails.append("policy default allow not honored")

    # (5) enforce mode sets enforced=True on DENY; shadow leaves it False.
    os.environ["ADMISSIBILITY_MODE"] = "enforce"
    if not gate("kill_process", {"pid": 1})["enforced"]:
        fails.append("enforce mode must mark DENY enforced")

    # (6) fail-open: a crashing adapter ALLOWS (and DENIES when fail=closed).
    _ADAPTERS["boom"] = lambda e, c: (_ for _ in ()).throw(RuntimeError("boom"))
    os.environ["ADMISSIBILITY_ADAPTER"] = "boom"

    def _crash_gate():
        return gate("write_file", {"path": "x.txt"})
    os.environ["ADMISSIBILITY_FAIL"] = "open"
    # unknown adapter names fall back to noop ("boom" is registered, so test with a truly unknown name)
    os.environ["ADMISSIBILITY_ADAPTER"] = "nonexistent"
    name, _ = _adapter()
    if name != "noop":
        fails.append("unknown adapter must fall back to noop")
    # exercise the exception path via the registered boom adapter
    _orig_adapter_fn = _adapter
    try:
        os.environ["ADMISSIBILITY_ADAPTER"] = "boom"
        # temporarily let _adapter resolve boom
        globals()["_adapter"] = lambda: ("boom", _ADAPTERS["boom"])
        if _crash_gate()["verdict"] != ALLOW:
            fails.append("fail-open must ALLOW on adapter crash")
        os.environ["ADMISSIBILITY_FAIL"] = "closed"
        if _crash_gate()["verdict"] != DENY:
            fails.append("fail-closed must DENY on adapter crash")
    finally:
        globals()["_adapter"] = _orig_adapter_fn  # restore the real function

    # (7) ledger ring cap holds.
    if len(json.load(open(_LEDGER_PATH, encoding="utf-8"))["decisions"]) > _MAX_LEDGER:
        fails.append("ledger ring cap exceeded")

    shutil.rmtree(tmpdir, ignore_errors=True)
    for k, v in _saved.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v

    if fails:
        print("admissibility self-test FAILED:")
        for f in fails:
            print("  -", f)
        raise SystemExit(1)
    print("admissibility self-test: all cases passed.")
