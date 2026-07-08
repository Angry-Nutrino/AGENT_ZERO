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
import os
import time
import math

SURFACE, HOLD, DROP = "surface", "hold", "drop"


# ── Budget: a daily token bucket with per-class cooldowns ──────────────────────
class Budget:
    """Optional daily cap (per_day=None -> NO cap) + per-class cooldown. The ambient feed dropped its
    daily cap 2026-06-24 (passive interface delivery doesn't interrupt, so scarcity isn't load-bearing)
    but KEEPS the cooldown for dedup (one nudge per session). WhatsApp drop-everything BYPASSES both."""
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
        if self.per_day is not None and self._count >= self.per_day:   # per_day=None -> no daily cap
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
        return None if self.per_day is None else max(0, self.per_day - self._count)


# ── Manual mute hook (the interrupt/timing layer was removed 2026-06-24 — passive feed) ─
def timing_blocked(ctx):
    """ctx: dict with optional flags. Returns a reason string if blocked, else None. These are the
    HARD timing NOs from Brief 40 — 'is now a decent moment?' — checked AFTER salience+budget clear."""
    ctx = ctx or {}
    # Interrupt-timing inference (deep_work / clock-DND / min_quiet) was REMOVED 2026-06-24: A2 delivers
    # passively to the interface (no sound/poke), so a nudge cannot interrupt — there is nothing to gate.
    # timing_blocked is kept only as the hook for a future MANUAL dnd flag ({"dnd": True} = user muted).
    if ctx.get("dnd"):                 return "DND (manual mute)"
    return None


def _cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _clamp01(x):
    return max(0.0, min(1.0, x))


# ── Ambient gate (Brief 40): salience = novelty × relevance × actionability ─────
_ACTIONABILITY = {
    # odd_hours 0.5 -> 0.6 (2026-06-24, tuned against the shadow pass): late-night activity scored 0.429,
    # a hair under 0.45; at 0.6 a novel odd-hour (novelty >= 0.75) clears the bar. Volume is held sane by
    # the per-class cooldown (one nudge per session) + the 4/day budget — so this fires the class without
    # spamming. Refine further from accumulated shadow data.
    "battery_low": 0.9, "meeting_soon": 0.9, "odd_hours": 0.6,
    "new_app_seen": 0.25, "long_session": 0.5, "off_rhythm": 0.6, "default": 0.3,
}

# Per-class cooldowns (seconds) for the AMBIENT default budget — a SUSTAINED session (e.g. a long
# late-night browse) must yield ONE nudge, not one per sample. The 2026-06-24 shadow pass showed ~12
# near-identical odd_hours candidates for a single 23:2x session; without a cooldown, any threshold that
# fires would spam. Budget already supports cooldowns — the ambient gate just needs to use them.
_AMBIENT_COOLDOWNS = {"battery_low": 3600, "odd_hours": 7200, "new_app_seen": 10800, "long_session": 7200,
                      "off_rhythm": 7200}

# ── Observation classifier (Y1b, Brief 40): raw A0 record -> a candidate obs {class, ...} or None ─
# Deterministic, NO LLM. Decides WHAT KIND of moment a record is (which sets actionability + which
# novelty sub-formula runs); the gate then decides whether it is salient enough. Returns None to DROP
# a record that is not a candidate at all (healthy/plugged battery, routine session transitions) so the
# gate never wastes a score on it. off_rhythm/long_session need session-duration state A0 does not yet
# expose -> not emitted in this step (documented follow-up); session_rhythm records currently drop.
BATTERY_LOW_PCT   = 25       # unplugged AND at/below this -> battery_low candidate
ODD_HOUR_DAY_FRAC = 0.25     # active at this hour on < this fraction of observed days -> odd_hours
_NIGHT_HOURS      = set(range(0, 6))   # fallback "odd" hours when there is no baseline yet


def _is_odd_hour(hour, baseline):
    """An hour is 'odd' if Alkama is rarely active then. Baseline-relative when available
    (days_active(hour)/days_observed < ODD_HOUR_DAY_FRAC); falls back to night hours otherwise."""
    if not baseline:
        return hour in _NIGHT_HOURS
    days_obs = baseline.get("days_observed", 0)
    if not days_obs:
        return hour in _NIGHT_HOURS
    return (baseline.get("hour_days", {}).get(hour, 0) / days_obs) < ODD_HOUR_DAY_FRAC


def classify(record, baseline=None, now=None):
    """Raw A0 record ({sensor, ts, payload}) -> classified candidate obs, or None to DROP it."""
    sensor  = record.get("sensor")
    payload = record.get("payload") or {}
    ts      = str(record.get("ts", ""))
    hour    = int(ts[11:13]) if len(ts) >= 13 else time.localtime(now or time.time()).tm_hour
    base    = {"hour": hour, "ts": ts, "sensor": sensor}

    if sensor == "system_state":
        pct = payload.get("battery_pct")
        if pct is not None and not payload.get("plugged", False) and pct <= BATTERY_LOW_PCT:
            return {**base, "class": "battery_low", "battery_pct": pct,
                    "text": f"battery {pct}% and unplugged"}
        return None                                  # healthy / plugged battery is not a candidate

    if sensor == "active_window":
        proc = str(payload.get("process", "")).lower()
        if not proc:
            return None
        title = str(payload.get("title", ""))
        cls = "odd_hours" if _is_odd_hour(hour, baseline) else "new_app_seen"
        return {**base, "class": cls, "process": proc, "title": title, "text": title or proc}

    return None                                      # session_rhythm / unknown: no candidate in Step 1


def _iso_to_epoch(ts):
    """'2026-07-06T14:30:00' -> epoch seconds, or None. Local, dependency-free (ambient_loop has
    its own parser but importing it here would be circular — salience must stay pure)."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(ts)[:19]).timestamp()
    except (ValueError, TypeError):
        return None


def _inject_gap_breaks(events, now, gap_s):
    """Machine-sleep guard (2026-07-08, the '21.0h straight' bug): A0 heartbeats every few
    minutes while the machine is AWAKE (empirically ≤ ~22 min even in a single unchanged
    window), so a TOTAL-silence stretch ≥ gap_s means the machine was asleep/off — the lid
    closed while active, so no idle event ever fired, and the old walk let a session span the
    night. Inject a synthetic idle span over every such gap (and an OPEN idle if the silence
    reaches `now`): both detectors' existing idle logic then does the right thing — sessions
    break, unobserved time credits no app, a currently-unobserved user is never nudged."""
    out = []
    prev = None
    for ev in sorted(events, key=lambda e: e[0]):
        ts = ev[0]
        if prev is not None and (ts - prev) >= gap_s:
            out.append((prev, "idle_start", None))
            out.append((ts, "idle_end", None))
        out.append(ev)
        prev = ts
    if prev is not None and (now - prev) >= gap_s:
        out.append((prev, "idle_start", None))   # open idle — silence continues to 'now'
    return out


def detect_long_session(observations, now=None, break_tolerance_s=None, trigger_s=None):
    """long_session marker (agreed 2026-07-04; built 07-06): 'you've been heads-down for N hours
    straight — break?'. WINDOW-evaluated over the A0 timeline (like off_rhythm's design), NOT
    per-record — classify() stays stateless.

    Algorithm (fixed on paper with Alkama):
    - A session = continuous foreground engagement. **A0 records active_window only on CHANGE**,
      so a 3h unbroken VS Code stretch is ONE record — foreground PERSISTS between records; gaps
      between activity records are NOT breaks. The ONLY session-breaker is a session_rhythm idle
      stretch reaching break_tolerance (default 15 min — the sensor's 5-min idle events below
      tolerance, a tea pause, do not break).
    - FIRE when the current session reaches trigger (default 150 min) AND the user is not
      currently idle-beyond-tolerance. Novelty = min(1, duration/trigger) → with actionability
      0.5 the score crosses the 0.45 gate exactly at trigger. The 2h class cooldown makes
      re-fires ~once per further 2h of the SAME unbroken session (accepted v1 semantics —
      a second nudge after 4.5h straight is good anchoring).
    Knobs env-tunable: LONG_SESSION_BREAK_MIN / LONG_SESSION_TRIGGER_MIN.
    Returns an obs dict (class long_session) or None."""
    now = now or time.time()
    break_tolerance_s = break_tolerance_s or int(os.getenv("LONG_SESSION_BREAK_MIN", "15")) * 60
    trigger_s = trigger_s or int(os.getenv("LONG_SESSION_TRIGGER_MIN", "150")) * 60

    events = []
    for o in observations or []:
        ts = _iso_to_epoch(o.get("ts"))
        if ts is None or ts > now:
            continue
        s = o.get("sensor")
        p = o.get("payload") or {}
        if s == "active_window" and p.get("process"):
            events.append((ts, "activity", str(p["process"]).lower()))
        elif s == "session_rhythm":
            state = str(p.get("state") or p.get("event") or "").lower()
            if "idle" in state:
                events.append((ts, "idle_start", None))
            elif "active" in state:
                events.append((ts, "idle_end", None))
    if not events:
        return None
    gap_break_s = int(os.getenv("AMBIENT_GAP_BREAK_MIN", "45")) * 60
    events = _inject_gap_breaks(events, now, gap_break_s)

    session_start = None
    idle_since = None
    for ts, kind, proc in events:
        if kind == "activity":
            if session_start is None:
                session_start = ts
            idle_since = None                      # a foreground change proves engagement
        elif kind == "idle_start":
            idle_since = ts
        elif kind == "idle_end":
            if idle_since is not None and (ts - idle_since) >= break_tolerance_s:
                session_start = ts                 # the long gap ended the old session
            idle_since = None
    if session_start is None:
        return None
    if idle_since is not None and (now - idle_since) >= break_tolerance_s:
        return None                                # currently away — nobody to nudge
    duration = now - session_start
    if duration < trigger_s:
        return None

    # dominant foreground app of the session (span = record → next record / now)
    spans = {}
    acts = [(ts, proc) for ts, kind, proc in events if kind == "activity" and ts >= session_start]
    for i, (ts, proc) in enumerate(acts):
        end = acts[i + 1][0] if i + 1 < len(acts) else now
        spans[proc] = spans.get(proc, 0.0) + max(0.0, end - ts)
    dominant = max(spans, key=spans.get) if spans else ""

    from datetime import datetime
    return {
        "class": "long_session",
        "ts": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
        "hour": time.localtime(now).tm_hour,
        "sensor": "session_rhythm",
        "process": dominant,
        "duration_s": int(duration),
        "rhythm_dev": _clamp01(duration / trigger_s),   # novelty: 1.0 at trigger, grows past it
        "text": f"{duration / 3600:.1f}h continuous, mostly {dominant or 'one thing'}",
    }


def detect_off_rhythm(observations, baseline, now=None, window_s=None, dominance=None):
    """off_rhythm marker (agreed 2026-07-04; built 07-06): 'you've been mostly in X for the last
    15 minutes when this hour is normally something else' — the drift anchor. WINDOW-evaluated
    like detect_long_session; three gates fixed on paper with Alkama:
    - WINDOW-DOMINANCE: over the last window (default 15 min), ONE app must hold >= dominance
      (default 0.6) of the engaged held-span. A 10-second switch can never fire (his explicit
      worry); idle stretches credit no app.
    - HOUR-DEVIANCE: the dominant app must be off-baseline for THIS hour — recognition
      `1 - days_seen(proc,hour)/days_observed` becomes rhythm_dev, so lunch-hour Brave scores ~0
      and the gate (0.6 actionability) only SURFACEs at rhythm_dev >= 0.75, i.e. an app seen at
      this hour on <25% of observed days (mirrors ODD_HOUR_DAY_FRAC). NO baseline -> None: an
      immature system must not accuse drift.
    - STILL-DRIFTING: at fire-time the CURRENT foreground must still be the deviant app, and the
      user must not be idle — self-correction is invisible ('no nagging the self-corrected').
      Any capture/enrichment is strictly downstream of a committed fire (no fire -> no camera).
    Knobs env-tunable: OFF_RHYTHM_WINDOW_MIN / OFF_RHYTHM_DOMINANCE.
    Returns an obs dict (class off_rhythm, novelty via rhythm_dev) or None."""
    now = now or time.time()
    window_s = window_s or int(os.getenv("OFF_RHYTHM_WINDOW_MIN", "15")) * 60
    dominance = dominance if dominance is not None else float(os.getenv("OFF_RHYTHM_DOMINANCE", "0.6"))
    days_obs = (baseline or {}).get("days_observed") or 0
    if not days_obs:
        return None

    events = []
    for o in observations or []:
        ts = _iso_to_epoch(o.get("ts"))
        if ts is None or ts > now:
            continue
        s = o.get("sensor")
        p = o.get("payload") or {}
        if s == "active_window" and p.get("process"):
            events.append((ts, "activity", str(p["process"]).lower()))
        elif s == "session_rhythm":
            state = str(p.get("state") or p.get("event") or "").lower()
            if "idle" in state:
                events.append((ts, "idle_start", None))
            elif "active" in state:
                events.append((ts, "idle_end", None))
    if not events:
        return None
    events = _inject_gap_breaks(events, now, int(os.getenv("AMBIENT_GAP_BREAK_MIN", "45")) * 60)

    # Walk the FULL timeline so foreground/idle state carries INTO the window (A0 records on
    # change only — the window's opening state is set by the last event before it).
    win_start = now - window_s
    spans, current, idle = {}, None, False
    mark = win_start                                # left edge of the un-credited stretch
    def credit(upto):
        nonlocal mark
        if upto > mark:
            if current and not idle:
                spans[current] = spans.get(current, 0.0) + (upto - mark)
            mark = upto
    for ts, kind, proc in events:
        if ts > win_start:
            credit(min(ts, now))
        if kind == "activity":
            current, idle = proc, False
        elif kind == "idle_start":
            idle = True
        elif kind == "idle_end":
            idle = False
    credit(now)

    if idle or not current or not spans:
        return None                                 # away right now — nobody to anchor
    dom_proc = max(spans, key=spans.get)
    if spans[dom_proc] < dominance * window_s:
        return None                                 # no single app dominated — no drift story
    if dom_proc != current:
        return None                                 # still-drifting guard: he already snapped back

    hour = time.localtime(now).tm_hour
    seen = (baseline or {}).get("proc_hour_days", {}).get(f"{dom_proc}|{hour}", 0)
    rhythm_dev = _clamp01(1.0 - seen / days_obs)

    from datetime import datetime
    return {
        "class": "off_rhythm",
        "ts": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
        "hour": hour,
        "sensor": "active_window",
        "process": dom_proc,
        "window_min": int(window_s / 60),
        "dominance_frac": round(spans[dom_proc] / window_s, 2),
        "rhythm_dev": rhythm_dev,                   # novelty: the gate's off_rhythm branch reads this
        "text": f"mostly {dom_proc} for the last {int(window_s / 60)} min — unusual for this hour",
    }


class AmbientGate:
    def __init__(self, budget=None, threshold=0.45):
        # No daily cap (per_day=None) — the passive feed isn't interrupt-scarce; the cooldown still dedups.
        self.budget = budget or Budget(per_day=None, cooldowns=_AMBIENT_COOLDOWNS)
        self.threshold = threshold

    @staticmethod
    def novelty(obs, baseline):
        """PER-CLASS deviation from the A0 baseline (0..1), baseline-relative so it personalizes (Y1a):
        - new_app_seen -> RECOGNITION: 1 - days_seen(proc,hour)/days_observed. A daily 2pm habit -> ~0
          even if it's the minority app that hour (the share-based bug); a never-at-3am app -> ~1.
        - odd_hours    -> TIMING: 1 - days_active(hour)/days_observed. Active at an hour he rarely is -> ~1.
        - battery_low  -> trajectory: 1 - battery_pct/100 (lower = more novel/urgent; actionability leads).
        - off_rhythm   -> session-start deviation (rhythm_dev; default until the rhythm baseline lands).
        - default      -> legacy share signal (1 - process_hour_freq share), preserving old behavior."""
        baseline = baseline or {}
        cls = obs.get("class", "default")
        days_obs = baseline.get("days_observed") or baseline.get("meta", {}).get("days_covered", 0)

        if cls == "battery_low":
            pct = obs.get("battery_pct")
            return _clamp01(1.0 - pct / 100.0) if pct is not None else 0.7

        if cls == "odd_hours":
            if not days_obs:
                return 0.6
            active = baseline.get("hour_days", {}).get(obs.get("hour"), 0)
            return _clamp01(1.0 - active / days_obs)

        if cls == "new_app_seen":
            proc = str(obs.get("process", "")).lower()
            if not proc or not days_obs:
                return 0.5
            seen = baseline.get("proc_hour_days", {}).get(f"{proc}|{obs.get('hour')}", 0)
            return _clamp01(1.0 - seen / days_obs)

        if cls == "off_rhythm":
            return _clamp01(obs.get("rhythm_dev", 0.6))

        # default: legacy share-based fallback (frequency of (proc,hour) within that hour)
        proc = str(obs.get("process", "")).lower()
        p = baseline.get("process_hour_freq", {}).get(f"{proc}|{obs.get('hour')}")
        if p is None:
            return 1.0 if proc else 0.5
        return _clamp01(1.0 - p)

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

    # ── Timing (passive feed: only the manual-DND mute hook remains) ────────────
    check(timing_blocked({"dnd": True}) is not None, "manual DND mute blocks")
    check(timing_blocked(None) is None and timing_blocked({}) is None, "no mute -> never timing-blocked")

    # ── classify (Y1b) ────────────────────────────────────────────────────────
    cb = {"days_observed": 10, "hour_days": {10: 10, 3: 0}}        # active 10am daily, never 3am
    check(classify({"sensor": "system_state", "ts": "2026-06-23T14:00:00",
                    "payload": {"battery_pct": 100, "plugged": True}}) is None,
          "classify drops a plugged/healthy battery")
    bl = classify({"sensor": "system_state", "ts": "2026-06-23T14:00:00",
                   "payload": {"battery_pct": 15, "plugged": False}})
    check(bl and bl["class"] == "battery_low" and bl["battery_pct"] == 15,
          f"classify -> battery_low when low+unplugged (got {bl})")
    aw = classify({"sensor": "active_window", "ts": "2026-06-23T10:00:00",
                   "payload": {"process": "Code.exe", "title": "x"}}, cb)
    check(aw and aw["class"] == "new_app_seen" and aw["process"] == "code.exe",
          f"classify -> new_app_seen at a usual hour (got {aw})")
    odd = classify({"sensor": "active_window", "ts": "2026-06-23T03:00:00",
                    "payload": {"process": "Code.exe", "title": "x"}}, cb)
    check(odd and odd["class"] == "odd_hours", f"classify -> odd_hours at a rarely-active hour (got {odd})")
    check(classify({"sensor": "session_rhythm", "ts": "2026-06-23T10:00:00",
                    "payload": {"state": "active", "event": "watcher_start"}}) is None,
          "classify drops routine session_rhythm")

    # ── novelty: RECOGNITION (Y1a) — the daily-but-minority app must NOT read as novel ──
    recog = {"days_observed": 10, "proc_hour_days": {"code.exe|14": 10, "neverseen.exe|14": 0},
             "hour_days": {14: 10}}
    nv = AmbientGate.novelty({"process": "code.exe", "hour": 14, "class": "new_app_seen"}, recog)
    check(nv <= 0.05, f"recognition: daily app at usual hour -> ~0 novelty (got {nv})")
    nv2 = AmbientGate.novelty({"process": "neverseen.exe", "hour": 14, "class": "new_app_seen"}, recog)
    check(nv2 >= 0.95, f"recognition: never-seen app -> ~1 novelty (got {nv2})")

    # ── AmbientGate ───────────────────────────────────────────────────────────
    ag = AmbientGate(budget=Budget(per_day=4), threshold=0.45)
    base = {"days_observed": 10,
            "proc_hour_days": {"code.exe|10": 9},   # code at 10am seen 9 of 10 days = habitual
            "hour_days": {10: 10, 3: 0},            # active at 10am daily; never at 3am
            "process_hour_freq": {"code.exe|10": 0.9}}
    d, det = ag.evaluate({"process": "code.exe", "hour": 10, "class": "new_app_seen"}, base, now=t0)
    check(d == HOLD, f"ambient HOLDs the habitual app (recognition; got {d}, {det})")
    # new_app_seen is informational-only by design (actionability 0.25 caps it below threshold) —
    # even a never-seen app does NOT surface on its own.
    d, det = ag.evaluate({"process": "neverseen.exe", "hour": 12, "class": "new_app_seen"}, base, now=t0)
    check(d == HOLD, f"new_app_seen alone never surfaces (act 0.25 cap; got {d}, {det})")
    # battery_low (low + unplugged) clears: novelty 0.85 × act 0.9 = 0.765
    d, det = ag.evaluate({"class": "battery_low", "battery_pct": 15, "hour": 14, "text": "battery 15%"},
                         base, now=t0)
    check(d == SURFACE, f"ambient SURFACEs a low unplugged battery (got {d}, {det})")
    # odd_hours: active at 3am where days_active=0 -> novelty 1 × act 0.5 = 0.5 >= 0.45
    d, det = ag.evaluate({"process": "foo.exe", "hour": 3, "class": "odd_hours", "text": "foo at 3am"},
                         base, now=t0 + 10)
    check(d == SURFACE, f"ambient SURFACEs activity at a rarely-active hour (got {d}, {det})")
    # odd_hours at a USUAL hour holds (active 10am daily -> novelty 0)
    d, det = ag.evaluate({"process": "foo.exe", "hour": 10, "class": "odd_hours"}, base, now=t0 + 20)
    check(d == HOLD, f"odd_hours at a usual hour holds (got {d}, {det})")
    # budget exhaustion holds even a salient one
    ag2 = AmbientGate(budget=Budget(per_day=1), threshold=0.45)
    ag2.evaluate({"class": "battery_low", "battery_pct": 10, "hour": 3}, {}, now=t0)
    d, _ = ag2.evaluate({"class": "battery_low", "battery_pct": 10, "hour": 3}, {}, now=t0 + 1)
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
