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


def recall(window_hours: float = 24, query: str = "") -> str:
    """A1 grounded recall (BRIEF_39): formatted slice of the observation store.

    Returns timestamped observations from the last `window_hours`, optionally
    keyword-filtered, plus a per-app activity rollup. Rule-19 parity is built into
    the output: an empty window says so explicitly — recall NEVER reconstructs
    unobserved time. Read-only; the watcher process owns all writes."""
    from datetime import datetime, timedelta

    obs = load_observations()
    if not obs:
        return ("No ambient observations exist. Either the ambient watcher is not "
                "running or no sensors are enabled — I have not been watching.")
    try:
        wh = float(window_hours)
    except (TypeError, ValueError):
        wh = 24.0
    cutoff = (datetime.now() - timedelta(hours=wh)).isoformat(timespec="seconds")
    window = [o for o in obs if o.get("ts", "") >= cutoff]
    filter_note = ""
    if query:
        q = str(query).lower()
        filtered = [o for o in window if q in json.dumps(o.get("payload", {})).lower()]
        # Graceful fallback: the interpreter sometimes passes descriptive phrases
        # ("foreground app") as keywords that match no payload text. If filtering
        # emptied a NON-empty window, show the window unfiltered with a note —
        # honest-empty is only correct when the window itself is empty.
        if filtered or not window:
            window = filtered
        else:
            filter_note = (f" (keyword '{query}' matched nothing — showing ALL "
                           f"observations in the window instead)")
            query = ""

    if not window:
        first, last = obs[0]["ts"], obs[-1]["ts"]
        return (f"No observations in the last {wh:g}h"
                + (f" matching '{query}'" if query else "")
                + f" — I wasn't watching during that window (store spans {first} to {last}). "
                  "I will not reconstruct unobserved time.")

    lines = [f"Ambient observations — last {wh:g}h"
             + (f", filtered by '{query}'" if query else "")
             + f" ({len(window)} records, timestamps exact){filter_note}:"]
    # Per-app rollup from window-change events
    apps = {}
    for o in window:
        if o["sensor"] == "active_window":
            p = o["payload"].get("process", "?")
            apps[p] = apps.get(p, 0) + 1
    if apps:
        top = sorted(apps.items(), key=lambda kv: -kv[1])[:6]
        lines.append("App activity (foreground changes): "
                     + ", ".join(f"{p} x{n}" for p, n in top))
    shown = window if len(window) <= 40 else window[-40:]
    if len(window) > 40:
        lines.append(f"[showing the most recent 40 of {len(window)}]")
    for o in shown:
        pl = o.get("payload", {})
        if o["sensor"] == "active_window":
            desc = f"{pl.get('process', '?')} — {pl.get('title', '')[:90]}"
        elif o["sensor"] == "system_state":
            desc = f"battery {pl.get('battery_pct', '?')}%, {'plugged in' if pl.get('plugged') else 'on battery'}"
        else:
            desc = f"{pl.get('event', pl.get('state', '?'))}" + (f" (idle {pl.get('idle_s')}s)" if pl.get("idle_s") else "")
        lines.append(f"  {o['ts']}  [{o['sensor']}]  {desc}")
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
