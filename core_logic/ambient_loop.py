"""
ambient_loop.py — A2 Step Y1c: the salience loop (DORMANT by default, SHADOW-first, Brief 40).

The loop that connects A0 perception to A2 proactivity. Each tick: pull the A0 observations not yet seen,
classify them (Y1b), score them through the AmbientGate (Y1a salience × budget × timing), and ACT by mode:

  A2_MODE=off    (default) — no-op. A2 is silent; the loop does nothing.
  A2_MODE=shadow           — LOG what it WOULD surface to ambient_shadow.jsonl. Sends NOTHING. This is how we
                             watch A2's "voice" against real data and tune thresholds before going live.
  A2_MODE=live             — compose + deliver (Telegram). NOT wired here: live delivery needs the
                             interrupt-model rebuild (Brief 40 §5) + Alkama arming it. The loop is
                             delivery-agnostic via an injected `sink`, so live is a sink swap, not a rewrite.

No new models: classify/novelty are pure code; relevance is the existing MiniLM (optional, neutral when there
is no discourse). Compose in shadow is a deterministic TEMPLATE (we tune SELECTION + FREQUENCY first; the real
LLM composer is injected for live). The cursor (last-seen ts) is persisted so a restart resumes instead of
re-flooding.

Pure + self-tested:  python core_logic/ambient_loop.py --selftest
One-shot SHADOW pass over the current A0 store + a tuning summary (near-misses):
                     python core_logic/ambient_loop.py
"""
import os
import json
import time
import uuid
import asyncio

try:                                                  # package vs. direct-run import
    from .salience import AmbientGate, Budget, classify, SURFACE, _ACTIONABILITY
except ImportError:                                   # python core_logic/ambient_loop.py
    from salience import AmbientGate, Budget, classify, SURFACE, _ACTIONABILITY

_DIR         = os.path.dirname(os.path.abspath(__file__))
_SHADOW_FILE = os.path.join(_DIR, "ambient_shadow.jsonl")
_STATE_FILE  = os.path.join(_DIR, "ambient_loop_state.json")
_LEDGER_FILE = os.path.join(_DIR, "ambient_ledger.json")   # live feed + 👍/👎 (Y1e calibration store)
_LEDGER_CAP  = 200


# ── Ledger: the live ambient feed + its 👍/👎 (Brief 40 §4 calibration store) ──────
def read_ledger(limit=50):
    """Recent feed entries (most recent last). limit=0 -> all (capped at _LEDGER_CAP on disk)."""
    try:
        with open(_LEDGER_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data[-limit:] if limit else data
    except Exception:
        return []


def _write_ledger(data):
    try:
        tmp = _LEDGER_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data[-_LEDGER_CAP:], f, ensure_ascii=False)
        os.replace(tmp, _LEDGER_FILE)
    except Exception:
        pass


def record_ledger(entry):
    data = read_ledger(limit=0)
    data.append({**entry, "feedback": entry.get("feedback")})
    _write_ledger(data)


def set_feedback(nudge_id, vote):
    """Record a 👍/👎 against a nudge id. Returns True if a matching entry was updated."""
    if vote not in ("up", "down"):
        return False
    data = read_ledger(limit=0)
    hit = False
    for e in data:
        if e.get("id") == nudge_id:
            e["feedback"] = vote
            hit = True
    if hit:
        _write_ledger(data)
    return hit


# ── Live sink: broadcast to the interface feed + record to the ledger ─────────────
_broadcast_fn = None   # injected by the backend (api.set_broadcast) — the WS broadcast primitive


def set_broadcast(fn):
    global _broadcast_fn
    _broadcast_fn = fn


def _live_sink(entry):
    """A2_MODE=live delivery: record the nudge to the ledger AND broadcast it to any connected UI. No
    sound/poke — it just appears in the passive feed. Records even with no UI connected (the UI loads the
    ledger via /ambient_feed on connect)."""
    record_ledger(entry)
    if _broadcast_fn is not None:
        try:
            asyncio.create_task(_broadcast_fn({
                "type": "ambient_nudge", "id": entry.get("id"), "remark": entry.get("remark"),
                "category": entry.get("class"), "score": entry.get("score"), "ts": entry.get("ts"),
            }))
        except RuntimeError:
            pass   # no running loop (e.g. one-shot) — the ledger record still stands


def a2_mode() -> str:
    """off | shadow | live — the dormant-by-default tri-state gate (env A2_MODE)."""
    m = os.getenv("A2_MODE", "off").strip().lower()
    return m if m in ("off", "shadow", "live") else "off"


def _ts_to_epoch(ts):
    """ISO 'YYYY-MM-DDTHH:MM:SS' -> epoch seconds, or None. Lets the gate score an observation at ITS
    OWN time (correct cooldown/budget spacing), which matters for the historical one-shot replay."""
    try:
        return time.mktime(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return None


# NOTE (2026-06-24 re-plan): the interrupt/timing layer (deep_work inference, clock-DND, min_quiet, the
# build_timing_ctx producer) was REMOVED. A2 delivers PASSIVELY to the interface — a nudge makes no sound
# and only appears when Alkama opens the panel, so it cannot interrupt; there is nothing to gate. The loop
# surfaces on NOVELTY + budget + the dedup cooldown only. A future MANUAL mute (DND) is just a flag passed
# as timing_ctx={"dnd": True}; no inference needed. (Removed work preserved in git history + TIMELINE.)


def _template_remark(obs) -> str:
    """Deterministic shadow compose — what A2 WOULD say. Live swaps in the LLM composer."""
    cls = obs.get("class")
    hh = obs.get("hour")
    hhmm = f"{hh:02d}:00" if isinstance(hh, int) else "now"
    if cls == "battery_low":
        return f"Battery's at {obs.get('battery_pct')}% and unplugged — flagging it before it bites."
    if cls == "odd_hours":
        return f"You're on {obs.get('process', 'something')} at {hhmm} — an unusual hour for you."
    if cls == "new_app_seen":
        return f"First time I've noticed {obs.get('process', 'that app')} around {hhmm}."
    return "Noticed something worth a glance."


class AmbientLoop:
    """One long-lived instance per process (it holds the day's budget AND the cursor)."""

    def __init__(self, baseline_fn, gate=None, compose_fn=None, sink=None,
                 mode_fn=a2_mode, now_fn=time.time, state_file=_STATE_FILE):
        self.baseline_fn = baseline_fn        # () -> baseline dict (refreshed each tick)
        # Default gate = AmbientGate() so it inherits the per-class COOLDOWNS (one nudge per session);
        # passing an explicit cooldown-less Budget here was the 2026-06-24 bug that spammed a session.
        self.gate = gate or AmbientGate(threshold=0.45)
        self.compose_fn = compose_fn or _template_remark
        self.sink = sink                      # (entry) -> None ; None -> default shadow-file sink
        self.mode_fn = mode_fn
        self.now_fn = now_fn
        self.state_file = state_file
        self._cursor = self._load_cursor()

    # ── cursor persistence (resume, don't re-flood, across restarts) ──────────────
    def _load_cursor(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f).get("cursor")
        except Exception:
            return None

    def _save_cursor(self):
        try:
            tmp = self.state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"cursor": self._cursor, "saved": self.now_fn()}, f)
            os.replace(tmp, self.state_file)
        except Exception:
            pass

    def _new_since_cursor(self, observations):
        if self._cursor is None:
            return list(observations)
        c = str(self._cursor)
        return [o for o in observations if str(o.get("ts", "")) > c]

    def _emit(self, entry):
        if self.sink:
            self.sink(entry)
            return
        try:
            with open(_SHADOW_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def tick(self, observations, discourse_vecs=None, encode=None, timing_ctx=None, advance=True,
             time_from_obs=False):
        """Process observations newer than the cursor; return the surfaced entries. mode=off -> []. With
        advance=False the cursor is not moved (the one-shot historical pass uses this). With
        time_from_obs=True each record is scored at ITS OWN timestamp (correct cooldown/budget spacing in
        a historical replay); live ticks leave it False and use now_fn (obs arrive ~immediately)."""
        mode = self.mode_fn()
        if mode == "off":
            return []
        baseline = self.baseline_fn() or {}
        new = self._new_since_cursor(observations)
        surfaced = []
        for rec in new:
            now = (_ts_to_epoch(rec.get("ts")) or self.now_fn()) if time_from_obs else self.now_fn()
            obs = classify(rec, baseline, now=now)
            if obs is None:
                continue
            decision, detail = self.gate.evaluate(
                obs, baseline=baseline, discourse_vecs=discourse_vecs, encode=encode,
                timing_ctx=timing_ctx, now=now)
            if decision == SURFACE:
                entry = {
                    "id": uuid.uuid4().hex[:12],
                    "ts": rec.get("ts"),
                    "class": obs["class"],
                    "score": detail.get("score"),
                    "novelty": detail.get("novelty"),
                    "actionability": detail.get("actionability"),
                    "remark": self.compose_fn(obs),
                    "mode": mode,
                    "would_send": mode == "live",
                }
                self._emit(entry)
                surfaced.append(entry)
        if advance and new:
            self._cursor = new[-1].get("ts")
            self._save_cursor()
        return surfaced


# ── Process-wide singleton (preserves the cursor + the day's budget across ticks) ──
_loop = None


def get_loop(baseline_fn=None, **kw):
    global _loop
    if _loop is None:
        _loop = AmbientLoop(baseline_fn=baseline_fn or (lambda: {}), **kw)
    elif baseline_fn is not None:
        _loop.baseline_fn = baseline_fn
    return _loop


async def ambient_shadow_loop(interval=300):
    """Backend background loop (Brief 40 Y1c) — started from api.py lifespan, dies with the backend.
    Every `interval`s, if A2_MODE != off, refresh the baseline and tick the loop. In SHADOW it LOGS
    candidate remarks to ambient_shadow.jsonl and sends nothing. Near-zero cost and a clean no-op while
    A2_MODE=off. Wrapped so a tick error never kills the loop.

    SAFETY FLOOR: the loop's default sink only WRITES (shadow file). Live delivery needs an injected
    notifier sink (+ the interrupt rebuild), so even A2_MODE=live cannot reach Telegram until that sink is
    wired — a wrong env value can never spam the phone."""
    try:
        from .ambient import load_observations, compute_baseline
        from .session_logger import slog
    except ImportError:
        from ambient import load_observations, compute_baseline
        from session_logger import slog
    slog.info(f"[A2] shadow loop started (A2_MODE={a2_mode()}, interval={interval}s).")
    while True:
        try:
            if a2_mode() != "off":
                obs = load_observations()
                base = compute_baseline(obs)
                loop = get_loop()
                loop.baseline_fn = lambda: base
                # live -> broadcast to the interface feed + ledger; shadow -> default file sink (log only).
                loop.sink = _live_sink if a2_mode() == "live" else None
                # Fresh start: watch FORWARD only — skip the historical backlog (use the one-shot for it).
                if loop._cursor is None and obs:
                    loop._cursor = obs[-1].get("ts")
                    loop._save_cursor()
                surfaced = loop.tick(obs)   # novelty + cooldown; no timing gate (passive feed)
                if surfaced:
                    slog.info(f"[A2:{a2_mode()}] surfaced x{len(surfaced)}: "
                              f"{[(e['class'], str(e['ts'])[:16]) for e in surfaced]}")
        except Exception as e:
            try:
                slog.warning(f"[A2] shadow loop tick error: {e}")
            except Exception:
                pass
        await asyncio.sleep(interval)


# ── Self-test ──────────────────────────────────────────────────────────────────
def _self_test():
    import tempfile
    fails = []

    def check(c, label):
        if not c:
            fails.append(label)

    t0 = time.mktime(time.strptime("2026-06-24 03:30:00", "%Y-%m-%d %H:%M:%S"))
    base = {"days_observed": 10, "proc_hour_days": {"code.exe|10": 9},
            "hour_days": {10: 10, 3: 0}, "process_hour_freq": {}}
    obs = [
        {"ts": "2026-06-24T10:00:00", "sensor": "active_window", "payload": {"process": "Code.exe", "title": "x"}},   # habitual 10am -> HOLD
        {"ts": "2026-06-24T03:05:00", "sensor": "active_window", "payload": {"process": "Code.exe", "title": "x"}},   # 3am (never) -> odd_hours SURFACE
        {"ts": "2026-06-24T03:06:00", "sensor": "system_state", "payload": {"battery_pct": 12, "plugged": False}},    # low+unplugged -> battery SURFACE
        {"ts": "2026-06-24T03:07:00", "sensor": "system_state", "payload": {"battery_pct": 95, "plugged": True}},     # healthy -> DROP
    ]
    sf = tempfile.mkstemp(suffix=".json")[1]

    # mode=off -> no-op
    off_sink = []
    loop_off = AmbientLoop(lambda: base, mode_fn=lambda: "off", sink=off_sink.append,
                           now_fn=lambda: t0, state_file=sf)
    check(loop_off.tick(obs) == [] and off_sink == [], "A2_MODE=off is a no-op (no surfacing, no emit)")

    # mode=shadow -> surfaces odd + battery only; never marks would_send
    sink = []
    loop = AmbientLoop(lambda: base, mode_fn=lambda: "shadow", sink=sink.append,
                       now_fn=lambda: t0, state_file=sf)
    out = loop.tick(obs)
    classes = sorted(e["class"] for e in out)
    check(classes == ["battery_low", "odd_hours"], f"shadow surfaces odd+battery only (got {classes})")
    check(out and all(e["would_send"] is False for e in out), "shadow never marks would_send")
    check(len(sink) == 2, f"shadow emitted both to the sink (got {len(sink)})")

    # cursor advanced -> re-ticking the SAME observations surfaces nothing new
    check(loop.tick(obs) == [], "cursor: already-seen observations are not re-surfaced")

    # budget cap: per_day=1 holds the second salient candidate
    sink2 = []
    loop_b = AmbientLoop(lambda: base, gate=AmbientGate(budget=Budget(per_day=1), threshold=0.45),
                         mode_fn=lambda: "shadow", sink=sink2.append, now_fn=lambda: t0,
                         state_file=tempfile.mkstemp(suffix=".json")[1])
    out_b = loop_b.tick(obs)
    check(len(out_b) == 1, f"budget per_day=1 caps surfacing to 1 (got {len(out_b)})")

    # ── Y1e: ledger record / read / feedback ─────────────────────────────────────
    import tempfile as _tf
    global _LEDGER_FILE
    _orig_ledger = _LEDGER_FILE
    _lfd, _LEDGER_FILE = _tf.mkstemp(suffix=".json")
    os.close(_lfd); os.remove(_LEDGER_FILE)                     # close the fd (Windows) + start empty
    record_ledger({"id": "abc123", "class": "odd_hours", "remark": "hi", "score": 0.5})
    record_ledger({"id": "def456", "class": "battery_low", "remark": "low", "score": 0.8})
    led = read_ledger(limit=0)
    check(len(led) == 2 and led[0]["feedback"] is None, "ledger records entries with feedback=None")
    check(set_feedback("abc123", "up") is True, "set_feedback hits an existing id")
    check(set_feedback("nope", "up") is False, "set_feedback misses an unknown id")
    check(set_feedback("def456", "sideways") is False, "set_feedback rejects an invalid vote")
    led = read_ledger(limit=0)
    check([e["feedback"] for e in led] == ["up", None], "feedback persisted on the right entry")
    try:
        os.remove(_LEDGER_FILE)
    except OSError:
        pass
    _LEDGER_FILE = _orig_ledger

    try:
        os.remove(sf)
    except OSError:
        pass

    if fails:
        print("ambient_loop self-test FAILED:")
        for f in fails:
            print("  -", f)
        raise SystemExit(1)
    print("ambient_loop self-test: all cases passed.")


# ── One-shot shadow pass + tuning summary ───────────────────────────────────────
def _one_shot():
    """Historical SHADOW pass over the current A0 store. Prints what WOULD surface now AND the top
    near-misses (held candidates by score) — the direct input to threshold/actionability tuning. Does
    not persist a cursor or write the real shadow file."""
    import collections
    try:
        from .ambient import compute_baseline, load_observations
    except ImportError:
        from ambient import compute_baseline, load_observations

    obs = load_observations()
    base = compute_baseline(obs)
    thresh = 0.45
    print(f"A0 baseline: days_observed={base.get('days_observed')}  "
          f"samples={base['meta']['samples']}  mature={base['meta']['mature']}")

    # Real surfaces (full gate, fresh budget) via the loop with a list sink, forced shadow, no cursor.
    sink = []
    loop = AmbientLoop(lambda: base, mode_fn=lambda: "shadow", sink=sink.append,
                       state_file=os.path.join(_DIR, ".ambient_loop_oneshot.tmp"))
    loop._cursor = None
    loop.tick(obs, advance=False, time_from_obs=True)   # score each record at its own time
    print(f"\nWOULD SURFACE across the window (full gate: salience + cooldown + 4/day budget): {len(sink)}")
    for e in sink[:10]:
        print(f"  {e['score']:.3f}  {e['class']:<13} {str(e['ts'])[:16]}  \"{e['remark']}\"")

    # Tuning view: top held candidates by RAW score (novelty × actionability), to see the near-misses.
    scored = []
    cls_count = collections.Counter()
    for rec in obs:
        c = classify(rec, base)
        if c is None:
            continue
        cls_count[c["class"]] += 1
        nv = AmbientGate.novelty(c, base)
        act = _ACTIONABILITY.get(c["class"], _ACTIONABILITY["default"])
        scored.append((round(nv * act, 3), c["class"], str(c.get("ts", ""))[:16],
                       c.get("process") or f"battery {c.get('battery_pct')}%"))
    scored.sort(reverse=True)
    print(f"\ncandidate classes: {dict(cls_count)}   threshold={thresh}")
    print("top candidates by raw score (novelty × actionability — near-misses show the tuning gap):")
    for s, cls, ts, what in scored[:12]:
        mark = "  <= would surface" if s >= thresh else ""
        print(f"  {s:>5}  {cls:<13} {ts}  {what}{mark}")
    try:
        os.remove(os.path.join(_DIR, ".ambient_loop_oneshot.tmp"))
    except OSError:
        pass


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _self_test()
    else:
        os.environ.setdefault("A2_MODE", "shadow")    # force shadow for the historical pass
        _one_shot()
