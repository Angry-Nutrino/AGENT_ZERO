"""
salience.py — the shared "right to interrupt" engine (Brief 40 A2 + Brief 45 WhatsApp priority).

ONE engine, TWO gates (Alkama's framing). The scoring/budget/timing/batching MACHINERY is shared;
the AmbientGate and the MessageGate are two configurations of it with different inputs, thresholds,
and budget policies. No LLM call ever decides WHETHER to surface — code decides; the LLM only
composes the remark (ambient) or breaks ties on the ambiguous slice (messages) AFTER the gates clear.

Decided parameters (Alkama, 2026-06-19):
- Ambient budget = 4 unprompted remarks/day (was 2 in the brief — bumped).
- WhatsApp: ONLY 'drop-everything' senders (Shobha) break through instantly; everyone else is HELD
  and surfaced when he's free. Conservative for the testing phase — urgency-from-strangers stays
  held until the gate's taste is proven (my reasoning: a bad urgency heuristic on unknown senders is
  exactly where it would spam him; restrict the interrupt to one known-trust source first).
- Batching = 15s per-sender debounce: buffer a sender's messages, RESET the 15s timer on each new
  one, compile into a single event only after 15s of silence (kills the one-sentence-at-a-time spam).
  Applies to everyone INCLUDING the drop-everything tier, so Shobha's rapid-fire becomes one coherent
  ping (≤15s later — a deliberate tradeoff vs 3 separate interrupts; per-sender window is overridable).

Pure, dependency-light, fully self-tested: `python core_logic/salience.py`. The MiniLM relevance is
injected (an `encode` fn) so the engine tests without the model — the backend passes the real encoder.
"""
import time
import math

SURFACE, HOLD, DROP = "surface", "hold", "drop"


# ── Budget: a daily token bucket with per-class cooldowns ──────────────────────
class Budget:
    """Daily cap (no accumulation) + optional per-class cooldown. Ambient uses per_day=4; the
    WhatsApp drop-everything tier BYPASSES the budget entirely (priority never gets capped)."""
    def __init__(self, per_day=4, cooldowns=None):
        self.per_day = per_day
        self.cooldowns = cooldowns or {}     # class -> min seconds between two of that class
        self._day = None
        self._count = 0
        self._last_by_class = {}             # class -> ts of last consume

    def _roll(self, now):
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if day != self._day:
            self._day, self._count, self._last_by_class = day, 0, {}

    def allow(self, cls=None, now=None):
        now = now if now is not None else time.time()
        self._roll(now)
        if self._count >= self.per_day:
            return False
        cd = self.cooldowns.get(cls)
        if cd is not None and cls in self._last_by_class and (now - self._last_by_class[cls]) < cd:
            return False
        return True

    def consume(self, cls=None, now=None):
        now = now if now is not None else time.time()
        self._roll(now)
        self._count += 1
        if cls is not None:
            self._last_by_class[cls] = now

    def remaining(self, now=None):
        self._roll(now if now is not None else time.time())
        return max(0, self.per_day - self._count)


# ── Timing etiquette: hard NOs (any True -> never surface, regardless of score) ─
def timing_blocked(ctx):
    """ctx: dict with optional flags. Returns a reason string if blocked, else None."""
    ctx = ctx or {}
    if ctx.get("ptt_held"):            return "PTT held"
    if ctx.get("task_in_flight"):      return "a user task is in flight"
    if ctx.get("clara_speaking"):      return "Clara is speaking"
    if ctx.get("dnd"):                 return "DND window"
    mins = ctx.get("mins_since_interaction")
    floor = ctx.get("min_quiet_mins", 0)
    if mins is not None and floor and mins < floor:
        return f"only {mins:.1f} min since last interaction (< {floor})"
    return None


def _cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ── Ambient gate (Brief 40): salience = novelty × relevance × actionability ─────
_ACTIONABILITY = {
    "battery_low": 0.9, "meeting_soon": 0.9, "odd_hours": 0.5,
    "new_app_seen": 0.25, "long_session": 0.5, "off_rhythm": 0.6, "default": 0.3,
}


class AmbientGate:
    def __init__(self, budget=None, threshold=0.45):
        self.budget = budget or Budget(per_day=4)
        self.threshold = threshold

    @staticmethod
    def novelty(obs, baseline):
        """Deviation from the A0 baseline (0..1). baseline: {process_hour_freq:{(proc,hour):p}, ...}.
        Unseen process at this hour -> ~1; the usual app at the usual hour -> ~0."""
        baseline = baseline or {}
        proc = str(obs.get("process", "")).lower()
        hour = obs.get("hour")
        freqs = baseline.get("process_hour_freq", {})
        # frequency of (proc,hour) as a share of that hour's observations; novelty = 1 - share
        p = freqs.get(f"{proc}|{hour}")
        if p is None:
            return 1.0 if proc else 0.5         # never seen at this hour
        return max(0.0, min(1.0, 1.0 - p))

    @staticmethod
    def relevance(obs, discourse_vecs, encode):
        """Max cosine between the observation and the current discourse/goal vectors. Relevance is a
        SUPPRESSOR, not an amplifier: with no discourse to be relevant to (he's not mid-conversation),
        it returns a NEUTRAL 1.0 (don't penalize). It only drags the score down when discourse EXISTS
        and the observation clearly misses it. encode: text -> vector."""
        text = str(obs.get("text") or obs.get("process") or "")
        if not encode or not discourse_vecs or not text:
            return 1.0
        try:
            v = encode(text)
        except Exception:
            return 1.0
        return max((_cosine(v, d) for d in discourse_vecs), default=1.0)

    @staticmethod
    def actionability(obs):
        return _ACTIONABILITY.get(obs.get("class", "default"), _ACTIONABILITY["default"])

    def evaluate(self, obs, baseline=None, discourse_vecs=None, encode=None, timing_ctx=None, now=None):
        nov = self.novelty(obs, baseline)
        rel = self.relevance(obs, discourse_vecs, encode)
        act = self.actionability(obs)
        score = nov * rel * act
        detail = {"novelty": round(nov, 3), "relevance": round(rel, 3),
                  "actionability": round(act, 3), "score": round(score, 4)}
        if score < self.threshold:
            return HOLD, {**detail, "reason": f"score {score:.3f} < {self.threshold}"}
        blk = timing_blocked(timing_ctx)
        if blk:
            return HOLD, {**detail, "reason": f"timing: {blk}"}
        cls = obs.get("class", "default")
        if not self.budget.allow(cls, now):
            return HOLD, {**detail, "reason": "budget exhausted"}
        self.budget.consume(cls, now)
        return SURFACE, {**detail, "reason": "cleared salience+timing+budget"}


# ── Message gate (Brief 45): person-priority; ONLY drop-everything breaks through ─
DROP_EVERYTHING = 1.0
_DEFAULT_PERSON_MAP = {}          # name/id -> weight; populated from config
_URGENCY_CUES = ("urgent", "emergency", "asap", "call me", "right now", "please reply", "important")


class MessageGate:
    def __init__(self, person_map=None):
        self.person_map = {k.lower(): v for k, v in (person_map or _DEFAULT_PERSON_MAP).items()}

    def person_weight(self, sender):
        s = str(sender or "").lower()
        if s in self.person_map:
            return self.person_map[s]
        # substring match so "Shobha 💛" / "+91…(Shobha)" still resolves
        for name, w in self.person_map.items():
            if name and name in s:
                return w
        return 0.2                 # saved-but-unmapped default; unsaved handled by the caller

    @staticmethod
    def urgency(text):
        t = str(text or "").lower()
        return any(cue in t for cue in _URGENCY_CUES)

    def evaluate(self, sender, text):
        """Returns (decision, detail). Testing-phase policy: ONLY a drop-everything sender (weight
        == 1.0) surfaces; everyone else is HELD (shown when he's free). Urgency is NOTED but does
        NOT break through yet (graduates later once the gate's taste is proven)."""
        w = self.person_weight(sender)
        urgent = self.urgency(text)
        detail = {"sender": sender, "weight": w, "urgent": urgent}
        if w >= DROP_EVERYTHING:
            return SURFACE, {**detail, "reason": "drop-everything sender"}
        return HOLD, {**detail, "reason": "held (not a drop-everything sender) — urgency noted" if urgent
                      else "held (not a drop-everything sender)"}


# ── Batcher: 15s per-sender debounce; reset on each new message ────────────────
class Batcher:
    """Collapse a sender's rapid-fire one-sentence-at-a-time messages into ONE event. add() each
    incoming message; the 15s quiet timer RESETS on every new message from that sender; flush_due()
    emits (sender, [texts], first_ts) for any sender silent for >= its window. Caller polls
    flush_due() every ~1-2s. Per-sender window overridable (e.g. a shorter one for Shobha)."""
    def __init__(self, window_s=15.0, windows=None):
        self.window_s = window_s
        self.windows = {k.lower(): v for k, v in (windows or {}).items()}
        self._buf = {}            # sender -> {"msgs":[...], "first_ts":t, "last_ts":t}

    def _window_for(self, sender):
        s = str(sender or "").lower()
        if s in self.windows:
            return self.windows[s]
        for name, w in self.windows.items():
            if name and name in s:
                return w
        return self.window_s

    def add(self, sender, text, ts=None):
        ts = ts if ts is not None else time.time()
        b = self._buf.get(sender)
        if b is None:
            self._buf[sender] = {"msgs": [text], "first_ts": ts, "last_ts": ts}
        else:
            b["msgs"].append(text)
            b["last_ts"] = ts      # RESET the quiet timer

    def flush_due(self, now=None):
        now = now if now is not None else time.time()
        out = []
        for sender in list(self._buf):
            b = self._buf[sender]
            if now - b["last_ts"] >= self._window_for(sender):
                out.append((sender, list(b["msgs"]), b["first_ts"]))
                del self._buf[sender]
        return out

    def pending(self):
        return {s: list(b["msgs"]) for s, b in self._buf.items()}


if __name__ == "__main__":
    fails = []

    def check(cond, label):
        if not cond:
            fails.append(label)

    # ── Budget ────────────────────────────────────────────────────────────────
    t0 = time.mktime(time.strptime("2026-06-19 10:00:00", "%Y-%m-%d %H:%M:%S"))
    b = Budget(per_day=4)
    for i in range(4):
        check(b.allow(now=t0 + i), f"budget allows #{i}"); b.consume(now=t0 + i)
    check(not b.allow(now=t0 + 5), "budget blocks the 5th (per_day=4)")
    check(b.allow(now=t0 + 86400 + 1), "budget refills next day")
    # cooldown
    bc = Budget(per_day=10, cooldowns={"battery_low": 3600})
    check(bc.allow("battery_low", now=t0), "cooldown allows first"); bc.consume("battery_low", now=t0)
    check(not bc.allow("battery_low", now=t0 + 60), "cooldown blocks within 1h")
    check(bc.allow("battery_low", now=t0 + 3601), "cooldown clears after 1h")

    # ── Timing ────────────────────────────────────────────────────────────────
    check(timing_blocked({"clara_speaking": True}) is not None, "timing blocks while speaking")
    check(timing_blocked({"mins_since_interaction": 1, "min_quiet_mins": 5}) is not None, "timing blocks too-soon")
    check(timing_blocked({"mins_since_interaction": 30, "min_quiet_mins": 5}) is None, "timing ok when quiet")

    # ── AmbientGate ───────────────────────────────────────────────────────────
    ag = AmbientGate(budget=Budget(per_day=4), threshold=0.45)
    base = {"process_hour_freq": {"code.exe|10": 0.9}}    # code at 10am is the norm
    d, det = ag.evaluate({"process": "code.exe", "hour": 10, "class": "new_app_seen"}, base, now=t0)
    check(d == HOLD, f"ambient HOLDs the usual app (got {d}, {det})")
    d, det = ag.evaluate({"process": "setup.tmp", "hour": 23, "class": "off_rhythm", "text": "installer at 11pm"},
                         base, now=t0)
    check(d == SURFACE, f"ambient SURFACEs a novel off-rhythm event (got {d}, {det})")
    # budget exhaustion holds even a salient one
    ag2 = AmbientGate(budget=Budget(per_day=1), threshold=0.45)
    ag2.evaluate({"process": "x.exe", "hour": 3, "class": "off_rhythm"}, {}, now=t0)
    d, _ = ag2.evaluate({"process": "y.exe", "hour": 3, "class": "off_rhythm"}, {}, now=t0 + 1)
    check(d == HOLD, "ambient HOLDs once budget exhausted")

    # ── MessageGate ───────────────────────────────────────────────────────────
    mg = MessageGate(person_map={"Shobha": 1.0})
    d, det = mg.evaluate("Shobha", "hey")
    check(d == SURFACE, f"message SURFACEs Shobha (got {d})")
    d, det = mg.evaluate("Shobha 💛", "call me")
    check(d == SURFACE, "message resolves Shobha via substring")
    d, det = mg.evaluate("Random Person", "URGENT call me now")
    check(d == HOLD, f"message HOLDs a non-Shobha even if 'urgent' (testing-phase policy) (got {d})")
    check(det["urgent"] is True, "urgency is still NOTED for the held message")

    # ── Batcher (15s debounce, reset on new) ──────────────────────────────────
    bt = Batcher(window_s=15.0)
    bt.add("A", "one", ts=t0)
    check(bt.flush_due(now=t0 + 10) == [], "batch not due at 10s")
    bt.add("A", "two", ts=t0 + 10)                       # resets timer
    check(bt.flush_due(now=t0 + 20) == [], "batch reset by 2nd msg — not due at 20s (10s since last)")
    out = bt.flush_due(now=t0 + 26)                      # 16s since last
    check(len(out) == 1 and out[0][0] == "A" and out[0][1] == ["one", "two"],
          f"batch flushes both after 15s quiet (got {out})")
    check(bt.flush_due(now=t0 + 100) == [], "batch cleared after flush")
    # per-sender override window
    bt2 = Batcher(window_s=15.0, windows={"Shobha": 3.0})
    bt2.add("Shobha", "hi", ts=t0)
    check(len(bt2.flush_due(now=t0 + 4)) == 1, "Shobha override window (3s) flushes faster")

    if fails:
        print("salience self-test FAILED:")
        for f in fails:
            print("  -", f)
        raise SystemExit(1)
    print("salience self-test: all cases passed.")
