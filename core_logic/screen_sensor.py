"""
core_logic/screen_sensor.py — Ambient Awareness A3 (screenshot -> Gemini description). Brief 36 F.7 / Y2-adjacent.

DELIBERATELY SEPARATE from core_logic/ambient.py (the A0 watcher), whose design rules forbid API keys AND
screenshots ("No GPU, no models, NO API KEYS anywhere in this module"; "no screenshots in A0/A1"). A3 is the
higher "earned-trust" tier: it runs in the BACKEND (which has the Gemini key + the vision tool), captures the
screen, asks Gemini for a ONE-LINE description of the high-level activity, and stores ONLY that text.

PRIVACY FLOOR (load-bearing — this sends screen content to a cloud model):
- OFF BY DEFAULT. Nothing is captured unless A3_SCREEN_SENSOR is explicitly 'on' (consent gate).
- Raw screenshots are NEVER persisted: captured in-memory, written to a temp PNG only for the Gemini call,
  deleted immediately afterwards. Only Gemini's TEXT description is stored.
- The prompt asks for high-level ACTIVITY only — explicitly NOT a transcription of text/code/passwords.
- Conservative cadence (A3_SCREEN_INTERVAL_MIN, default 15 min, floor 1 min).
- Its OWN store (ambient_screen.json, backend-owned) — the A0 watcher still single-owns ambient.json.

Self-test (mocks capture + Gemini, NEVER touches the real screen): python core_logic/screen_sensor.py
"""
import os
import json
import tempfile
from datetime import datetime

_SCREEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ambient_screen.json")
_MAX_OBS = 2000
_PROMPT = (
    "In ONE concise sentence, describe the high-level activity on this screen (which app, what kind of "
    "task). Do NOT transcribe or quote any text, code, messages, or private/sensitive content — report "
    "only the general activity, e.g. 'Editing a Python file in VS Code' or 'Reading email in a browser'."
)


def a3_enabled() -> bool:
    """Consent gate. A3 does NOTHING unless explicitly armed."""
    return os.getenv("A3_SCREEN_SENSOR", "").strip().lower() in ("on", "1", "true", "yes")


def interval_seconds() -> float:
    try:
        return max(60.0, float(os.getenv("A3_SCREEN_INTERVAL_MIN", "15")) * 60.0)
    except (TypeError, ValueError):
        return 900.0


def _capture_to_temp():
    """Grab the screen to a temp PNG. This file is the ONLY raw copy and the caller deletes it immediately.
    Returns the temp path, or None if capture is unavailable. Never raises."""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        if img.width > 1280 or img.height > 1280:
            img.thumbnail((1280, 1280))
        fd, tmp = tempfile.mkstemp(prefix="a3_screen_", suffix=".png")
        os.close(fd)
        try:
            img.convert("RGB").save(tmp, format="PNG")
        except Exception:
            # mkstemp already created the file; if the save fails we must NOT leave a partial/empty
            # raw screenshot on disk (the "raw screenshot NEVER persists" privacy floor).
            try:
                os.remove(tmp)
            except Exception:
                pass
            return None
        return tmp
    except Exception:
        return None


def capture_and_describe(_grab=None, _describe=None):
    """Capture the screen and return a one-line Gemini description; the raw image is deleted immediately.
    Test seams: _grab() -> temp_path (or None); _describe(path) -> text. Returns None on any failure."""
    grab = _grab or _capture_to_temp
    describe = _describe
    if describe is None:
        from .tools import analyze_image_grok  # lazy: only the backend path imports the vision tool
        def describe(path):
            return analyze_image_grok(None, path=path, question=_PROMPT)
    tmp = grab()
    if not tmp:
        return None
    try:
        desc = describe(tmp)
    finally:
        try:
            os.remove(tmp)   # the raw screenshot NEVER persists
        except Exception:
            pass
    if not desc or str(desc).strip().lower().startswith(("error", "vision error")):
        return None
    return " ".join(str(desc).split())[:300]


def run_once(_grab=None, _describe=None, store_path=None):
    """One A3 cycle: if armed, capture+describe and store the DESCRIPTION (not the image). Returns the
    description or None. Consent gate: NO capture happens unless A3_SCREEN_SENSOR is on."""
    if not a3_enabled():
        return None
    desc = capture_and_describe(_grab=_grab, _describe=_describe)
    if not desc:
        return None
    _append(desc, store_path or _SCREEN_PATH)
    return desc


def _append(desc: str, path: str) -> None:
    """Atomic append to the backend-owned ambient_screen.json ring (mkstemp -> fsync -> os.replace, the same
    crash/contention-proof pattern as crud._save_memory). Never raises."""
    try:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            obs = data.get("observations") if isinstance(data, dict) else None
            if not isinstance(obs, list):
                obs = []
        except (OSError, json.JSONDecodeError):
            obs = []
        obs.append({"ts": datetime.now().isoformat(timespec="seconds"), "sensor": "screen", "description": desc})
        obs = obs[-_MAX_OBS:]
        fd, tmp = tempfile.mkstemp(prefix=".ambient_screen.", suffix=".tmp", dir=os.path.dirname(path) or ".")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "observations": obs}, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        pass


if __name__ == "__main__":
    import shutil
    fails = []
    # (1) consent gate: OFF by default -> run_once does NOTHING (no capture).
    os.environ.pop("A3_SCREEN_SENSOR", None)
    if run_once(_grab=lambda: "x", _describe=lambda p: "desc") is not None:
        fails.append("OFF-by-default gate failed (captured while disabled)")

    os.environ["A3_SCREEN_SENSOR"] = "on"
    tmpdir = tempfile.mkdtemp(prefix="a3_test_")
    store = os.path.join(tmpdir, "ambient_screen.json")
    captured = {"path": None}
    def fake_grab():
        fd, p = tempfile.mkstemp(prefix="fake_screen_", suffix=".png", dir=tmpdir)
        os.close(fd)
        captured["path"] = p
        return p
    # (2) armed: capture+describe+store; raw temp deleted; description-only stored.
    desc = run_once(_grab=fake_grab, _describe=lambda p: "Editing a Python file in VS Code.", store_path=store)
    if not (desc and "VS Code" in desc):
        fails.append(f"description not returned when armed: {desc!r}")
    if captured["path"] and os.path.exists(captured["path"]):
        fails.append("PRIVACY: raw screenshot temp was NOT deleted")
    data = json.load(open(store, encoding="utf-8"))
    last = data["observations"][-1]
    if not (last["sensor"] == "screen" and last["description"] == desc and "image" not in last):
        fails.append(f"store row wrong (must be description-only): {last}")
    # (3) a vision error stores NOTHING.
    n = len(data["observations"])
    run_once(_grab=fake_grab, _describe=lambda p: "Vision error after retries: 503", store_path=store)
    if len(json.load(open(store, encoding="utf-8"))["observations"]) != n:
        fails.append("a vision error must store nothing")
    # (4) a capture/save failure must NOT leak a raw screenshot temp (privacy floor).
    try:
        import glob
        from PIL import ImageGrab as _IG
        class _BadImg:
            width = height = 100
            def thumbnail(self, *a): pass
            def convert(self, *a): return self
            def save(self, *a, **k): raise OSError("simulated save failure")
        _orig_grab = _IG.grab
        _IG.grab = lambda *a, **k: _BadImg()
        before = set(glob.glob(os.path.join(tempfile.gettempdir(), "a3_screen_*.png")))
        r = _capture_to_temp()
        leaked = set(glob.glob(os.path.join(tempfile.gettempdir(), "a3_screen_*.png"))) - before
        _IG.grab = _orig_grab
        for p in leaked:
            try: os.remove(p)
            except Exception: pass
        if r is not None:
            fails.append("_capture_to_temp must return None on save failure")
        if leaked:
            fails.append("PRIVACY: _capture_to_temp leaked a raw screenshot temp on save failure")
    except ImportError:
        pass  # PIL not importable in this env — skip; the delete-on-failure guard is still in place.
    shutil.rmtree(tmpdir, ignore_errors=True)

    if fails:
        print("screen_sensor (A3) self-test FAILED:")
        for f in fails:
            print("  -", f)
        raise SystemExit(1)
    print("screen_sensor (A3) self-test: all cases passed.")
