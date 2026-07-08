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


def _recent_duplicate(cls, remark, now=None, window_h=72):
    """True if an IDENTICAL (class, remark) nudge already sits in the ledger within window_h hours.
    The per-session cooldown legitimately re-allows a class on a later day, but the exact same
    sentence twice in three days is repetition, not information (observed: twin 'brave at 22:00'
    nudges on 06-25 + 06-27). Never raises."""
    try:
        now = now or time.time()
        for e in read_ledger(limit=25):
            # Compare the deterministic SEED (pre-LLM template): the polished display text varies
            # per call, so it can never be the dedup key. Rows older than 2026-07-03 lack the
            # seed field — their remark IS the template.
            if e.get("class") != cls or (e.get("remark_seed") or e.get("remark")) != remark:
                continue
            ep = _ts_to_epoch(e.get("ts"))
            if ep and (now - ep) < window_h * 3600:
                return True
    except Exception:
        pass
    return False


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


_llm_client = None


# Per-class register for the remark polish (2026-07-06, from Alkama's 07-04 calibration: nudges should
# have CHARACTER — his target example for odd_hours was literally a question, so the blanket no-questions
# rule is relaxed per-class rather than globally).
_REMARK_CHARACTER = {
    "odd_hours": ("Playfully tease him about the hour — the register of \"What are you doing so late, "
                  "night owl?\". One light rhetorical question is allowed for this one."),
    "long_session": ("Warm and looking-out-for-him — nudge a stretch or water without nagging or "
                     "guilt. No questions."),
    "off_rhythm": ("Observational and gentle — an anchor back to his usual rhythm, never scolding, "
                   "never guilt. State what you noticed, leave the choice to him. No questions."),
    "new_app_seen": ("Curious and observant, like noticing a new book on a friend's desk. No questions."),
    "battery_low": ("Dry and urgent, zero fluff — this is the one nudge that must be acted on now. "
                    "No questions."),
}


async def _llm_remark(entry):
    """One cheap non-reasoning call turns the template into a natural, personal remark — the
    'Live swaps in the LLM composer' the template docstring always promised (built 2026-07-03,
    Alkama: the template text is 'very very generic'). Returns None on ANY problem — the
    deterministic template always stands as the fallback. Kill switch: A2_REMARK_LLM=off."""
    global _llm_client
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        return None
    if _llm_client is None:
        from openai import AsyncOpenAI
        _llm_client = AsyncOpenAI(api_key=key, base_url="https://api.deepseek.com")
    character = _REMARK_CHARACTER.get(
        entry.get("class"), "Natural and personal. No questions.")
    prompt = (
        "You are CLARA, Alkama's personal ambient AI. Rewrite this observation as ONE short, natural, "
        "personal remark to him (max 22 words). Keep every concrete fact (app, number, time, day) "
        "EXACTLY as given — never add a fact, action, time, or detail that is not in the observation, "
        "and never round or restate a number. Rephrase only. "
        "12-hour time only; no emojis; at most one question and only if the register allows it; "
        "don't mention being an AI or 'observation'. "
        f"Register: {character}\n"
        f"Observation: {entry.get('remark')}"
    )
    r = await _llm_client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=1.1, max_tokens=60, stream=False,
    )
    text = " ".join((r.choices[0].message.content or "").strip().strip('"').split())
    if not _remark_fidelity_ok(entry.get("remark"), text):
        return None   # template stands — same numeric-fidelity principle as _run_fast's guard
    return text[:180] or None


def _remark_fidelity_ok(template, polished) -> bool:
    """Deterministic backstop for the polish (2026-07-06): at temp 1.1 the model can invent facts
    ('you checked the battery at 1:15 PM') or round numbers ('~2.7h' -> 'three hours'). Every number
    in the template must survive verbatim into the polish, and the polish must not introduce a
    clock-time that wasn't there. Fail -> the deterministic template ships instead."""
    import re
    t, p = str(template or ""), str(polished or "")
    if not p:
        return False
    if any(n not in p for n in re.findall(r"\d+(?:\.\d+)?", t)):
        return False
    t_nums = set(re.findall(r"\d+(?:\.\d+)?", t))
    return all(n in t_nums for n in re.findall(r"\d+(?:\.\d+)?", p))


async def _deliver(entry):
    """Async live delivery: optional LLM polish (bounded, fallback = template) → ledger → broadcast."""
    if os.getenv("A2_REMARK_LLM", "on").strip().lower() in ("on", "1", "true", "yes"):
        try:
            polished = await asyncio.wait_for(_llm_remark(entry), timeout=10)
            if polished:
                entry["remark"] = polished
        except Exception:
            pass   # template remark stands
    record_ledger(entry)
    if _broadcast_fn is not None:
        try:
            await _broadcast_fn({
                "type": "ambient_nudge", "id": entry.get("id"), "remark": entry.get("remark"),
                "category": entry.get("class"), "score": entry.get("score"), "ts": entry.get("ts"),
            })
        except Exception:
            pass


def _live_sink(entry):
    """A2_MODE=live delivery: record the nudge to the ledger AND broadcast it to any connected UI. No
    sound/poke — it just appears in the passive feed. Records even with no UI connected (the UI loads the
    ledger via /ambient_feed on connect). The async path adds the LLM remark polish; a sync context
    (one-shot replay) records the deterministic template directly."""
    try:
        asyncio.get_running_loop().create_task(_deliver(entry))
    except RuntimeError:
        record_ledger(entry)   # no running loop (e.g. one-shot) — the ledger record still stands


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


_PROC_NAMES = {
    "brave.exe": "Brave", "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox",
    "code.exe": "VS Code", "explorer.exe": "File Explorer", "searchhost.exe": "Windows Search",
    "spotify.exe": "Spotify", "discord.exe": "Discord", "utweb.exe": "µTorrent",
    "windowsterminal.exe": "Terminal", "notion.exe": "Notion", "notion calendar.exe": "Notion Calendar",
    "telegram.exe": "Telegram", "whatsapp.exe": "WhatsApp", "shellhost.exe": "Windows Shell",
}


def _friendly_proc(p) -> str:
    p = str(p or "").strip().lower()
    if p in _PROC_NAMES:
        return _PROC_NAMES[p]
    if p.endswith(".exe"):
        p = p[:-4]
    return p.capitalize() if p else "something"


def _friendly_hour(hh) -> str:
    """22 → '10 PM' — Alkama never does 24h conversions in his head (drill Q22's whole premise)."""
    if not isinstance(hh, int):
        return "just now"
    if hh == 0:
        return "midnight"
    if hh == 12:
        return "noon"
    return f"{hh - 12} PM" if hh > 12 else f"{hh} AM"


def _friendly_day(ts) -> str:
    """'' (today) / 'yesterday' / 'on Friday' (this week) / 'on Jun 27' (older)."""
    try:
        from datetime import datetime, date
        d = datetime.fromisoformat(str(ts)[:19]).date()
        delta = (date.today() - d).days
        if delta <= 0:
            return ""
        if delta == 1:
            return "yesterday"
        if delta < 7:
            return "on " + d.strftime("%A")
        return "on " + d.strftime("%b %d").replace(" 0", " ")
    except Exception:
        return ""


def _template_remark(obs) -> str:
    """Deterministic compose — humanized app names, 12-hour time, day-aware. This is both the
    shadow text and the fallback when the live LLM polish (A2_REMARK_LLM) is off/unavailable.
    (The old version leaked raw 'brave.exe' + '22:00' with no day — the 2026-07-03 complaint.)"""
    cls = obs.get("class")
    when = _friendly_hour(obs.get("hour"))
    day = _friendly_day(obs.get("ts"))
    day_sfx = f" {day}" if day else ""
    proc = _friendly_proc(obs.get("process"))
    if cls == "battery_low":
        return f"Battery's at {obs.get('battery_pct')}% and unplugged — flagging it before it bites."
    if cls == "odd_hours":
        return f"{proc} at {when}{day_sfx} — that's an unusual hour for you."
    if cls == "new_app_seen":
        return f"First time I've seen {proc} — it showed up around {when}{day_sfx}."
    if cls == "long_session":
        hrs = (obs.get("duration_s") or 0) / 3600
        return (f"You've been at it ~{hrs:.1f}h straight — mostly {proc}. "
                f"Worth a stretch and some water.")
    if cls == "off_rhythm":
        mins = obs.get("window_min", 15)
        return (f"Mostly {proc} for the last {mins} minutes — "
                f"not your usual rhythm for {when}.")
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
                remark = self.compose_fn(obs)
                # Cross-day content dedup (2026-07-03): the per-session cooldown correctly allows
                # "brave at 22:00" to re-surface on a LATER day — but an IDENTICAL remark within
                # 72h is repetition, not information (the feed showed twin nudges from 06-25 and
                # 06-27). Feed hygiene: suppress exact repeats inside the window.
                if _recent_duplicate(obs["class"], remark, now=now):
                    continue
                entry = {
                    "id": uuid.uuid4().hex[:12],
                    "ts": rec.get("ts"),
                    "class": obs["class"],
                    "category": obs["class"],   # consumer-facing alias — /ambient_feed returns raw
                                                 # ledger rows, and the UI reads `category` (rows
                                                 # recorded before 2026-07-03 lack it → blank label)
                    "score": detail.get("score"),
                    "novelty": detail.get("novelty"),
                    "actionability": detail.get("actionability"),
                    "remark": remark,
                    "remark_seed": remark,      # deterministic dedup key — the display remark may be
                                                 # LLM-polished (varies), the seed never does
                    "mode": mode,
                    "would_send": mode == "live",
                }
                self._emit(entry)
                surfaced.append(entry)
        # long_session (2026-07-06): WINDOW-evaluated over the FULL timeline (not per-record —
        # a 3h unbroken session is ONE A0 record). Same gate path as every other class:
        # evaluate → dedup-by-seed → emit; the 2h class cooldown + budget apply unchanged.
        try:
            from .salience import detect_long_session
            ls = detect_long_session(observations, now=self.now_fn())
            if ls is not None:
                decision, detail = self.gate.evaluate(ls, baseline=baseline,
                                                      discourse_vecs=discourse_vecs, encode=encode,
                                                      timing_ctx=timing_ctx, now=self.now_fn())
                if decision == SURFACE:
                    remark = self.compose_fn(ls)
                    if not _recent_duplicate(ls["class"], remark, now=self.now_fn()):
                        entry = {
                            "id": uuid.uuid4().hex[:12],
                            "ts": ls.get("ts"),
                            "class": ls["class"],
                            "category": ls["class"],
                            "score": detail.get("score"),
                            "novelty": detail.get("novelty"),
                            "actionability": detail.get("actionability"),
                            "remark": remark,
                            "remark_seed": remark,
                            "mode": mode,
                            "would_send": mode == "live",
                        }
                        self._emit(entry)
                        surfaced.append(entry)
        except Exception:
            pass   # the marker must never break the loop
        # off_rhythm (2026-07-06): same window-evaluated pattern. Three agreed gates live in the
        # detector (15-min dominance, hour-deviance vs baseline, still-drifting suppression);
        # the loop just routes it through the identical evaluate → dedup → emit path.
        try:
            from .salience import detect_off_rhythm
            orr = detect_off_rhythm(observations, baseline, now=self.now_fn())
            if orr is not None:
                decision, detail = self.gate.evaluate(orr, baseline=baseline,
                                                      discourse_vecs=discourse_vecs, encode=encode,
                                                      timing_ctx=timing_ctx, now=self.now_fn())
                if decision == SURFACE:
                    remark = self.compose_fn(orr)
                    if not _recent_duplicate(orr["class"], remark, now=self.now_fn()):
                        entry = {
                            "id": uuid.uuid4().hex[:12],
                            "ts": orr.get("ts"),
                            "class": orr["class"],
                            "category": orr["class"],
                            "score": detail.get("score"),
                            "novelty": detail.get("novelty"),
                            "actionability": detail.get("actionability"),
                            "remark": remark,
                            "remark_seed": remark,
                            "mode": mode,
                            "would_send": mode == "live",
                        }
                        self._emit(entry)
                        surfaced.append(entry)
        except Exception:
            pass   # the marker must never break the loop

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
