"""
whatsapp_gate.py — backend glue for read-only WhatsApp awareness (Brief 45, Phase 1).

Sits between the (external, Node) whatsapp-web.js push and CLARA's notification path. The scoring is
the SHARED salience engine (salience.py): a Batcher (15s per-sender debounce) front-stage, then the
MessageGate (Shobha = drop-everything; everyone else HELD) back-stage.

Flow: the Node service POSTs each incoming message to /whatsapp_incoming -> record_incoming() ->
Batcher. A backend poller calls poll() every ~2s; any sender silent for >=15s yields one compiled
batch, which the MessageGate routes to SURFACE (interrupt Alkama now) or HOLD (store, show when free).
READ-ONLY: nothing is ever sent back to WhatsApp here.

Decided config (Alkama, 2026-06-19): PERSON_MAP = {Shobha: 1.0}. Only Shobha breaks through during the
testing phase; urgency-from-strangers is noted but held. 15s batch window (override per-sender if needed).

Self-test: `python core_logic/whatsapp_gate.py` (no backend, no Node).
"""
try:
    from .salience import Batcher, MessageGate, SURFACE, HOLD   # package (backend)
except ImportError:
    from salience import Batcher, MessageGate, SURFACE, HOLD    # script (self-test)

# Drop-everything roster. Add names/numbers -> weight (1.0 = breaks through). Substring-matched, so
# "Shobha 💛" or a saved "+91…(Shobha)" still resolves. Keep this tight during the testing phase.
PERSON_MAP = {
    "shobha": 1.0,
}
BATCH_WINDOW_S = 15.0
PER_SENDER_WINDOWS = {}        # e.g. {"shobha": 5.0} for a snappier window on a key person

_batcher = Batcher(window_s=BATCH_WINDOW_S, windows=PER_SENDER_WINDOWS)
_gate = MessageGate(person_map=PERSON_MAP)


def record_incoming(sender, text, ts=None):
    """Called per incoming message (from /whatsapp_incoming). Buffers into the 15s debounce."""
    _batcher.add(sender, text, ts)


def poll(now=None):
    """Called every ~2s by the backend poller. Returns a list of dispatch dicts for senders whose 15s
    quiet window has elapsed: {sender, text (compiled), count, decision (surface|hold), detail}."""
    out = []
    for sender, msgs, first_ts in _batcher.flush_due(now):
        compiled = "\n".join(msgs)
        decision, detail = _gate.evaluate(sender, compiled)
        out.append({"sender": sender, "text": compiled, "count": len(msgs),
                    "first_ts": first_ts, "decision": decision, "detail": detail})
    return out


def pending():
    return _batcher.pending()


if __name__ == "__main__":
    import time
    fails = []
    def check(c, l):
        if not c: fails.append(l)

    t0 = time.time()
    # Shobha sends 3 messages one-sentence-at-a-time within the window
    record_incoming("Shobha", "hey", ts=t0)
    record_incoming("Shobha", "are you free", ts=t0 + 4)
    record_incoming("Shobha", "call me when you can", ts=t0 + 8)
    # a stranger, plus an "urgent" stranger
    record_incoming("Random Guy", "yo", ts=t0 + 2)
    record_incoming("Spammer", "URGENT claim your prize now", ts=t0 + 3)

    check(poll(now=t0 + 10) == [], "nothing flushes before 15s quiet")
    out = poll(now=t0 + 24)        # 16s after Shobha's last (t0+8), >15s for all
    by = {d["sender"]: d for d in out}
    check("Shobha" in by, "Shobha batch flushed")
    check(by["Shobha"]["count"] == 3 and "call me" in by["Shobha"]["text"], "Shobha's 3 msgs compiled into one")
    check(by["Shobha"]["decision"] == SURFACE, "Shobha SURFACEs (drop-everything)")
    check(by["Random Guy"]["decision"] == HOLD, "stranger HELD")
    check(by["Spammer"]["decision"] == HOLD, "urgent stranger HELD (testing-phase: only Shobha breaks through)")
    check(by["Spammer"]["detail"]["urgent"] is True, "stranger's urgency still NOTED")
    check(poll(now=t0 + 100) == [], "buffer cleared after flush")

    if fails:
        print("whatsapp_gate self-test FAILED:")
        for f in fails: print("  -", f)
        raise SystemExit(1)
    print("whatsapp_gate self-test: all cases passed.")
