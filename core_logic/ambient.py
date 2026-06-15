"""Ambient Awareness — Phase A0 sensors + observation store (BRIEF_39).

Shared by ambient_watch.py (the standalone 24/7 watcher — the ONLY writer of
ambient.json) and the backend (read-only consumer; A1 recall, A2 salience later).

Design rules (BRIEF_39, amended 2026-06-11):
- No GPU, no models, NO API KEYS anywhere in this module.
- Consent-gated: a sensor runs ONLY if its name is listed in the AMBIENT_SENSORS
  env var (comma-separated). Absent/empty = everything off.
- Single writer per file: the watcher owns ambient.json; the backend's derived
  baseline goes to ambient_patterns.json (written backend-side, never here).
- Atomic flushes (mkstemp -> fsync -> os.replace with PermissionError retry) —
  the same crash/contention-proof pattern as crud._save_memory.
- Privacy floor: window TITLES and process NAMES only. No keystrokes, no
  clipboard, no screenshots in A0/A1.
"""

import ctypes
import ctypes.wintypes
import json
import os
import re
import tempfile
import time
from datetime import datetime

AMBIENT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ambient.json")
SCHEMA_VERSION = 1
MAX_OBSERVATIONS = 2000          # FIFO ring cap
FLUSH_EVERY_S = 30               # flush dirty store at most this often
IDLE_THRESHOLD_S = 300           # session_rhythm: 5 min without input = idle

VALID_SENSORS = ("active_window", "system_state", "session_rhythm")


def enabled_sensors() -> list:
    """Consent gate: only sensors explicitly listed in AMBIENT_SENSORS run."""
    raw = os.getenv("AMBIENT_SENSORS", "")
    return [s.strip() for s in raw.split(",") if s.strip() in VALID_SENSORS]


# ── Store ─────────────────────────────────────────────────────────────────────

class AmbientStore:
    """Ring-buffered observation store. Writer-side use only (ambient_watch.py).
    The backend reads the file directly via load_observations()."""

    def __init__(self, path: str = AMBIENT_PATH):
        self.path = path
        self._data = self._load()
        self._dirty = False
        self._last_flush = 0.0

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("observations"), list):
                return d
        except (OSError, json.JSONDecodeError):
            pass
        return {"schema": SCHEMA_VERSION, "observations": []}

    def append(self, sensor: str, payload: dict) -> None:
        self._data["observations"].append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "sensor": sensor,
            "payload": payload,
        })
        if len(self._data["observations"]) > MAX_OBSERVATIONS:
            del self._data["observations"][:-MAX_OBSERVATIONS]
        self._dirty = True

    def flush(self, force: bool = False) -> bool:
        """Atomic write if dirty and the flush interval elapsed. Returns True if written."""
        now = time.monotonic()
        if not self._dirty or (not force and now - self._last_flush < FLUSH_EVERY_S):
            return False
        d = os.path.dirname(self.path) or "."
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(prefix=".ambient.json.", suffix=".tmp", dir=d)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(10):
                try:
                    os.replace(tmp, self.path)
                    tmp = None
                    break
                except PermissionError:   # backend reading mid-swap (Windows)
                    time.sleep(0.02 * (attempt + 1))
            else:
                return False
            self._dirty = False
            self._last_flush = now
            return True
        except Exception:
            return False
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def load_observations(path: str = AMBIENT_PATH) -> list:
    """Backend-side read-only accessor (A1 recall / A2 salience / baseline stats)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d.get("observations", []) if isinstance(d, dict) else []
    except (OSError, json.JSONDecodeError):
        return []


_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"]) if i}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})


def _parse_date_anchor(s: str):
    """Resolve a date phrase to 'YYYY-MM-DD', or None if it isn't a date.
    Handles: ISO (2026-06-11), 'June 11' / '11 June' / 'Jun 11', and the
    relative 'today'/'yesterday'/'day before yesterday'. (Brief 39 / Q1 fix B)"""
    from datetime import datetime, timedelta
    if not s:
        return None
    t = str(s).strip().lower()
    now = datetime.now()
    if t in ("today",):
        return now.strftime("%Y-%m-%d")
    if t in ("yesterday",):
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if t in ("day before yesterday", "two days ago"):
        return (now - timedelta(days=2)).strftime("%Y-%m-%d")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)            # ISO anywhere
    if m:
        return m.group(0)
    m = re.search(r"\b([a-z]{3,9})\s+(\d{1,2})\b", t)        # "june 11"
    if m and m.group(1) in _MONTHS:
        return f"{now.year:04d}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"\b(\d{1,2})\s+([a-z]{3,9})\b", t)        # "11 june"
    if m and m.group(2) in _MONTHS:
        return f"{now.year:04d}-{_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return None


def recall(window_hours: float = 24, query: str = "", date: str = "") -> str:
    """A1 grounded recall (BRIEF_39): formatted view of the observation store.

    Scope is EITHER a specific calendar day (`date`, e.g. '2026-06-11' / 'June 11' /
    'yesterday' — overrides window_hours) OR the last `window_hours` (default). This
    removes the interpreter's error-prone hours-back math for "what was I doing on
    June 11" (Q1 fix B). Rule-19 parity: an empty scope says so explicitly — recall
    NEVER reconstructs unobserved time. Read-only; the watcher owns all writes."""
    from datetime import datetime, timedelta

    obs = load_observations()
    if not obs:
        return ("No ambient observations exist. Either the ambient watcher is not "
                "running or no sensors are enabled — I have not been watching.")

    # ── Scope: date anchor (preferred when given) or hours-back window ──────────
    day = _parse_date_anchor(date) if date else None
    if day:
        window = [o for o in obs if o.get("ts", "").startswith(day)]
        scope = f"on {day}"
    else:
        try:
            wh = float(window_hours)
        except (TypeError, ValueError):
            wh = 24.0
        cutoff = (datetime.now() - timedelta(hours=wh)).isoformat(timespec="seconds")
        window = [o for o in obs if o.get("ts", "") >= cutoff]
        scope = f"in the last {wh:g}h"

    filter_note = ""
    if query:
        q = str(query).lower()
        filtered = [o for o in window if q in json.dumps(o.get("payload", {})).lower()]
        # Graceful fallback: the interpreter sometimes passes descriptive phrases
        # ("foreground app") as keywords that match nothing. Showing the unfiltered
        # window is honest; an empty result is only correct when the window is empty.
        if filtered or not window:
            window = filtered
        else:
            filter_note = (f" (keyword '{query}' matched nothing — showing ALL "
                           f"observations in scope instead)")
            query = ""

    if not window:
        first, last = obs[0]["ts"], obs[-1]["ts"]
        return (f"No observations {scope}"
                + (f" matching '{query}'" if query else "")
                + f" — I wasn't watching then (store spans {first} to {last}). "
                  "I will not reconstruct unobserved time.")

    lines = [f"Ambient observations — {scope}"
             + (f", filtered by '{query}'" if query else "")
             + f" ({len(window)} records, timestamps exact){filter_note}:"]

    # Per-app rollup over the FULL window (never truncated — answers "which apps").
    apps = {}
    for o in window:
        if o["sensor"] == "active_window":
            p = o["payload"].get("process", "?")
            apps[p] = apps.get(p, 0) + 1
    if apps:
        top = sorted(apps.items(), key=lambda kv: -kv[1])[:6]
        lines.append("App activity (foreground changes): "
                     + ", ".join(f"{p} x{n}" for p, n in top))

    # Detail. The OLD tail-cap (window[-40:]) hid in-window records when the window
    # was busy — so "what was I doing at 21:00" returned only recent hours (Q1 fix B).
    # Small windows → full raw list; large windows → an HOUR-BY-HOUR rollup over the
    # WHOLE scope (so 21:00 is always present as its own row), never a tail slice.
    if len(window) <= 50:
        for o in window:
            pl = o.get("payload", {})
            if o["sensor"] == "active_window":
                desc = f"{pl.get('process', '?')} — {pl.get('title', '')[:90]}"
            elif o["sensor"] == "system_state":
                desc = f"battery {pl.get('battery_pct', '?')}%, {'plugged in' if pl.get('plugged') else 'on battery'}"
            else:
                desc = f"{pl.get('event', pl.get('state', '?'))}" + (f" (idle {pl.get('idle_s')}s)" if pl.get("idle_s") else "")
            lines.append(f"  {o['ts']}  [{o['sensor']}]  {desc}")
    else:
        from collections import defaultdict
        by_hour = defaultdict(lambda: defaultdict(int))
        for o in window:
            if o["sensor"] == "active_window":
                by_hour[o["ts"][:13]][o["payload"].get("process", "?")] += 1
        lines.append(f"Hour-by-hour foreground apps ({len(window)} records — full scope, not a tail):")
        for hr in sorted(by_hour):
            tops = sorted(by_hour[hr].items(), key=lambda kv: -kv[1])[:3]
            lines.append(f"  {hr}:00  " + ", ".join(f"{p}({n})" for p, n in tops))
    return "\n".join(lines)


# ── Sensors (Windows; each returns an observation payload ON CHANGE, else None) ──

class ActiveWindowSensor:
    """Foreground window title + process name. Records on change only."""
    name = "active_window"
    interval_s = 30

    def __init__(self):
        self._last = None

    def sample(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = ""
            try:
                import psutil
                proc = psutil.Process(pid.value).name()
            except Exception:
                pass
            if not title and not proc:
                return None
            current = (title, proc)
            if current == self._last:
                return None
            self._last = current
            return {"title": title[:200], "process": proc}
        except Exception:
            return None


class SystemStateSensor:
    """Battery %, AC plugged. Records on meaningful change (5% step or plug toggle)."""
    name = "system_state"
    interval_s = 60

    def __init__(self):
        self._last = None

    def sample(self):
        try:
            import psutil
            batt = psutil.sensors_battery()
            if batt is None:
                return None
            state = (int(batt.percent) // 5, bool(batt.power_plugged))
            if state == self._last:
                return None
            self._last = state
            return {"battery_pct": int(batt.percent), "plugged": bool(batt.power_plugged)}
        except Exception:
            return None


class SessionRhythmSensor:
    """Input-presence transitions: active <-> idle (5 min without input)."""
    name = "session_rhythm"
    interval_s = 60

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.wintypes.UINT), ("dwTime", ctypes.wintypes.DWORD)]

    def __init__(self):
        self._last_state = None

    def _idle_seconds(self) -> float:
        info = self._LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0

    def sample(self):
        try:
            idle = self._idle_seconds()
            state = "idle" if idle >= IDLE_THRESHOLD_S else "active"
            if state == self._last_state:
                return None
            prev = self._last_state
            self._last_state = state
            if prev is None:
                return {"state": state, "event": "watcher_start"}
            return {"state": state,
                    "event": "went_idle" if state == "idle" else "resumed",
                    "idle_s": int(idle)}
        except Exception:
            return None


SENSOR_CLASSES = {
    "active_window": ActiveWindowSensor,
    "system_state": SystemStateSensor,
    "session_rhythm": SessionRhythmSensor,
}
