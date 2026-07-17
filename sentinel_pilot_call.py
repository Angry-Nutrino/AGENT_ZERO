"""
partner A pilot — LIVE walkthrough helper (the governance partner call, Fri 2026-07-10 5-6 AM IST).

Purpose: fire CLARA's first ENFORCED /analyze call in ONE command during the joint session, and print the
whole path the governance partner wants to walk (signed request -> verification inputs -> decision -> ledger hash/receipt).
Reuses the exact signing the live adapter uses (core_logic.admissibility._partner_a_sign) so what runs here
IS what CLARA runs.

Usage (from repo root, venv python):
    jarvis_v2/Scripts/python.exe partner_a_pilot_call.py --simulate # STEP 1: fire both /simulate calls, print full output
    jarvis_v2/Scripts/python.exe partner_a_pilot_call.py            # DRY: build + print the signed /analyze request, send NOTHING
    jarvis_v2/Scripts/python.exe partner_a_pilot_call.py --send     # STEP 2: fire the enforced /analyze call live

Default is DRY on purpose — show the governance partner the constructed request first, then --send to fire live together.
Creds come from core_logic/.env (PARTNER_A_AGENT_ID / PARTNER_A_AGENT_KEY / PARTNER_A_AGENT_PUBKEY).
"""
import os, sys, json, time, base64
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join("core_logic", ".env"))

from core_logic.admissibility import _partner_a_sign

BASE = os.getenv("PARTNER_A_BASE_URL", "https://partner_asca.com").rstrip("/")
AGENT = os.getenv("PARTNER_A_AGENT_ID", "").strip()

# The first enforced action = the benign health-check read (lowest-risk possible for the milestone call).
COMMAND = {"type": "read_url", "target": "https://partner_asca.com/health",
           "reason": "first live enforced CLARA governed call (pilot milestone)"}


def build_request():
    cmd_json = json.dumps(COMMAND)
    ts_unix = str(int(time.time()))
    ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    signed_payload = {"agent_id": AGENT, "command": cmd_json, "timestamp": ts_iso, "ts_unix": ts_unix}
    signature = _partner_a_sign(signed_payload)           # Ed25519 over canonical JSON
    body = {"agent_id": AGENT, "command": cmd_json, "timestamp": ts_iso}   # ts_unix EXCLUDED from body
    headers = {"Content-Type": "application/json", "X-Signature": signature, "X-Timestamp-Unix": ts_unix}
    canonical = json.dumps(signed_payload, sort_keys=True, separators=(",", ":"))
    return body, headers, signed_payload, canonical


def verify_self(canonical, signature_b64):
    """Prove the signature verifies against the REGISTERED public key before we send (what partner A does)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    pub = base64.b64decode(os.getenv("PARTNER_A_AGENT_PUBKEY", ""))
    Ed25519PublicKey.from_public_bytes(pub).verify(base64.b64decode(signature_b64), canonical.encode())
    return True


def run_simulate():
    """STEP 1: fire both /simulate calls and print full request + response — screenshot-ready."""
    import requests
    calls = [
        ("HEALTH-CHECK  (read_url)",
         {"type": "read_url", "target": "https://partner_asca.com/health",
          "reason": "pilot session — health-check simulate"}),
        ("SANDBOX WRITE (write_file)",
         {"type": "write_file", "path": "sandbox-test", "content_ref": "abc123hash",
          "operation": "create_or_modify_file", "dry_run": True, "sandbox": True,
          "reason": "pilot session — sandbox write_file simulate", "environment": "sandbox/eval"}),
    ]
    for label, command in calls:
        body = {"agent_id": AGENT, "command": json.dumps(command), "timestamp": str(int(time.time()))}
        r = requests.post(f"{BASE}/api/v2/simulate",
                          headers={"x-api-key": os.getenv("PARTNER_A_API_KEY", ""), "Content-Type": "application/json"},
                          json=body, timeout=float(os.getenv("PARTNER_A_TIMEOUT_S", "10")))
        print("=" * 70)
        print(f"SIMULATE — {label}")
        print("=" * 70)
        print(f"POST {BASE}/api/v2/simulate   ->   HTTP {r.status_code}")
        try:
            d = r.json()
            print(f"  decision    : {d.get('decision')}")
            print(f"  risk        : {d.get('risk')}  (score {d.get('risk_score')})")
            print(f"  reason      : {d.get('reason')}")
            print(f"  action_hash : {d.get('action_hash')}")
            print(f"  record.status: {d.get('record', {}).get('status')}")
            print(f"  simulation  : {d.get('simulation')}   signature_verified: {d.get('signature_verified')}")
            print("  --- full JSON ---")
            print(json.dumps(d, indent=2))
        except Exception:
            print("  raw:", r.text[:800])
        print()


def run_analyze_write():
    """STEP 3: the REVIEW flow. PART 1 — signed /analyze with the sandbox write_file envelope
    (partner A's review/audit trail). PART 2 — CLARA's gate armed (partner_a + enforce): prove she
    HOLDS the action on a review/deny verdict instead of executing."""
    import requests
    command = {"type": "write_file", "path": "sandbox-test", "content_ref": "pilot-review-test",
               "operation": "create_or_modify_file", "dry_run": True, "sandbox": True,
               "reason": "pilot session — sandbox write_file enforced (REVIEW flow)",
               "environment": "sandbox/eval"}
    cmd_json = json.dumps(command)
    ts_unix = str(int(time.time()))
    ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    signed = {"agent_id": AGENT, "command": cmd_json, "timestamp": ts_iso, "ts_unix": ts_unix}
    headers = {"Content-Type": "application/json", "x-api-key": os.getenv("PARTNER_A_API_KEY", ""),
               "X-Signature": _partner_a_sign(signed), "X-Timestamp-Unix": ts_unix}
    print("=" * 70)
    print("PART 1 — SIGNED /analyze : sandbox write_file  (the REVIEW flow)")
    print("=" * 70)
    r = requests.post(f"{BASE}/analyze", headers=headers,
                      json={"agent_id": AGENT, "command": cmd_json, "timestamp": ts_iso},
                      timeout=float(os.getenv("PARTNER_A_TIMEOUT_S", "10")))
    print(f"POST {BASE}/analyze   ->   HTTP {r.status_code}")
    data = r.json()
    for k in ("decision", "risk", "risk_score", "reason", "ledger_id", "audit_id",
              "replay_url", "evidence_url", "review_action_id", "review_response_deadline_ts"):
        if k in data and data[k] is not None:
            print(f"  {k:28}: {data[k]}")
    print("\n  FULL RESPONSE JSON:")
    print(json.dumps(data, indent=2))

    print("\n" + "=" * 70)
    print("PART 2 — CLARA's handling: gate ARMED (adapter=partner_a, mode=ENFORCE)")
    print("=" * 70)
    os.environ["ADMISSIBILITY_GATE"] = "on"
    os.environ["ADMISSIBILITY_ADAPTER"] = "partner_a"
    os.environ["ADMISSIBILITY_MODE"] = "enforce"
    from core_logic import admissibility as adm
    decision = adm.gate("write_file", {"path": "sandbox-test", "content": "pilot review test"},
                        task_id="pilot-review-demo")
    print(f"  gate verdict : {decision['verdict']}")
    print(f"  enforced     : {decision['enforced']}   (mode={decision['mode']}, adapter={decision['adapter']})")
    print(f"  reason       : {decision['reason']}")
    if decision["enforced"]:
        held = ("DENIED — action blocked" if decision["verdict"] == "DENY"
                else "HELD FOR REVIEW — action paused")
        print(f"\n  >> CLARA OUTCOME: {held}. The write_file is NOT executed.")
        print("     tool_executor returns the block to the ReAct loop instead of running the tool")
        print("     (core_logic/tool_executor.py — the enforced-verdict path).")
    else:
        print("\n  >> gate did not enforce — action would have proceeded.")


def main():
    if not AGENT or not os.getenv("PARTNER_A_AGENT_KEY"):
        print("ERROR: PARTNER_A_AGENT_ID / PARTNER_A_AGENT_KEY missing from core_logic/.env"); sys.exit(1)
    if "--simulate" in sys.argv:
        run_simulate(); return
    if "--send-write" in sys.argv:
        run_analyze_write(); return
    body, headers, signed_payload, canonical = build_request()

    print("=" * 70)
    print("PARTNER_A /analyze — signed request (agent_id =", AGENT, ")")
    print("=" * 70)
    print("\n[1] Canonical signed payload (sort_keys, compact — the bytes we sign):")
    print("   ", canonical)
    print("\n[2] Headers:")
    print("    X-Signature     :", headers["X-Signature"])
    print("    X-Timestamp-Unix:", headers["X-Timestamp-Unix"])
    print("\n[3] POST body (ts_unix excluded, per spec):")
    print("   ", json.dumps(body))
    print("\n[4] Local signature self-check against the registered public key:",
          "VERIFIED" if verify_self(canonical, headers["X-Signature"]) else "FAILED")

    if "--send" not in sys.argv:
        print("\n[DRY RUN] Nothing sent. Re-run with --send to fire the enforced call live.")
        return

    import requests
    print("\n[5] Sending POST", f"{BASE}/analyze", "...")
    r = requests.post(f"{BASE}/analyze", headers={**headers, "x-api-key": os.getenv("PARTNER_A_API_KEY", "")},
                      json=body, timeout=float(os.getenv("PARTNER_A_TIMEOUT_S", "10")))
    print("    HTTP", r.status_code)
    try:
        data = r.json()
    except Exception:
        print("    raw:", r.text[:500]); return
    print("\n[6] ENFORCED DECISION:")
    for k in ("signature_verified", "decision", "risk", "risk_score", "action_hash",
              "ledger_hash", "receipt", "reason"):
        if k in data:
            print(f"    {k:16}: {data[k]}")
    print("\n[7] EXACT FULL RESPONSE JSON (verbatim from partner A):")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
