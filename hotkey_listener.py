"""
hotkey_listener.py — global F10 push-to-talk for CLARA (Brief 44.1, Wave 2).

A STANDALONE process (sibling to ambient_watch.py). It registers a system-wide F10 hotkey, and the
mic is opened ONLY while F10 is held — closed the instant you release. This honors Alkama's hard
constraints: no always-listening, and the mic is never open during Clara's reply (so the
play-while-record distortion on this laptop can't happen — capture and playback are strictly
sequential). On release it sends the recorded WAV to the backend (/voice_query), which transcribes
with the already-loaded Whisper, runs the cancel-filter + full pipeline (channel='voice'), and speaks
the reply via Kokoro.

SETUP (run once):
    pip install keyboard          # global hotkey hook (sounddevice/soundfile/numpy/requests already present)
RUN:
    python hotkey_listener.py     # leave it running; press & hold F10, speak, release.
    python hotkey_listener.py --list-devices   # list input devices (to pick CLARA_MIC_DEVICE)
Stop: Ctrl+C.

If F10 yields empty transcripts ("captured near-silence"), the mic is delivering no signal — muted or gated
(on this laptop the ASUS/Intelligo AI noise-cancel can silence the default Realtek array). The listener now
detects this and refuses to send a dead WAV. Fix: `--list-devices`, then set CLARA_MIC_DEVICE to a working
index or name substring (e.g. the headset), or fix it in Windows Settings → Sound → Input.

NOTE / open item for Alkama to test: this listener owns the mic on-demand. The backend's
VoiceCoordinator also opens a PERSISTENT mic for the F4-browser path. On Windows (WASAPI shared mode)
two openers usually coexist, but if you hear distortion or capture fails, the fix is to NOT run the
browser voice at the same time, OR have the backend release its mic during TTS — flagged, not
blind-changed. If the reply audio distorts, set speak=False in the POST (a one-line change below).
"""
import sys
import os
import io
import base64
import time
import threading

try:
    import keyboard
except ImportError:
    print("hotkey_listener: missing dependency. Run:  pip install keyboard")
    sys.exit(1)
import sounddevice as sd
import soundfile as sf
import numpy as np
import requests

HOTKEY      = "f10"
SAMPLE_RATE = 16000
CHANNELS    = 1
BACKEND_URL = "http://localhost:8001/voice_query"
SPEAK_REPLY = True              # set False if simultaneous play/record distorts on your hardware
MAX_SECONDS = 60


def _resolve_device(spec):
    """CLARA_MIC_DEVICE → an int index, a name substring, or None (system default input)."""
    if spec is None or not str(spec).strip():
        return None
    spec = str(spec).strip()
    return int(spec) if spec.lstrip("-").isdigit() else spec


# Which input device to record from. None = the OS default. On this laptop the default Realtek
# array can be GATED to silence by the ASUS/Intelligo AI-noise-cancel virtual device (2026-06-23:
# F10 produced empty transcripts because capture peaked at ~3e-05 = digital silence). Set
# CLARA_MIC_DEVICE to an index or name substring (see --list-devices) to pick a working mic.
MIC_DEVICE   = _resolve_device(os.getenv("CLARA_MIC_DEVICE"))
# Captured peak below this ≈ silence — the true noise floor is ~3e-05 and real speech peaks ~0.1+,
# so 0.01 sits safely between: it catches a dead/muted/gated mic without tripping on a quiet voice.
SILENCE_PEAK = 0.01

_lock = threading.Lock()
_recording = False
_frames = []
_stream = None


def _start():
    """Open the mic and begin capture — called on F10 down (ignores key-repeat)."""
    global _recording, _frames, _stream
    with _lock:
        if _recording:
            return
        _frames = []
        try:
            _stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                     callback=_callback, dtype="float32", device=MIC_DEVICE)
            _stream.start()
            _recording = True
            print("● recording… (hold F10)")
        except Exception as e:
            print(f"hotkey_listener: mic open failed: {e}")
            _stream = None


def _callback(indata, frames, time_info, status):
    if _recording:
        _frames.append(indata.copy())
        if len(_frames) * frames / SAMPLE_RATE > MAX_SECONDS:
            threading.Thread(target=_stop_and_send, daemon=True).start()


def _stop_and_send():
    """Close the mic (mic OFF now) and POST the WAV — called on F10 up."""
    global _recording, _stream, _frames
    with _lock:
        if not _recording:
            return
        _recording = False
        try:
            if _stream:
                _stream.stop(); _stream.close()
        except Exception:
            pass
        _stream = None
        frames = _frames
        _frames = []
    if not frames:
        print("…nothing captured."); return
    try:
        audio = np.concatenate(frames, axis=0)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak < SILENCE_PEAK:
            print(f"  ⚠ captured near-silence (peak {peak:.4f}) — NOT sending; the mic delivered no signal.")
            print("    Fix: pick a working input via CLARA_MIC_DEVICE (run with --list-devices for indices),")
            print("    or check Windows Settings → Sound → Input and disable ASUS/Intelligo AI noise-cancelling.")
            return
        print("◼ stopped — transcribing + sending…")
        buf = io.BytesIO()
        sf.write(buf, audio, SAMPLE_RATE, format="WAV")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        r = requests.post(BACKEND_URL, json={"audio_b64": b64, "speak": SPEAK_REPLY}, timeout=600)
        data = r.json()
        t = data.get("transcript", ""); resp = data.get("response", "")
        if data.get("cancelled"):
            print(f'  you: "{t}"  → (false request, dismissed)')
        else:
            print(f'  you: "{t}"')
            print(f'  clara: {resp[:200]}')
    except Exception as e:
        print(f"hotkey_listener: send failed (backend up on :8001?): {e}")


def _print_input_devices():
    print("Input-capable audio devices (use the index or a name substring as CLARA_MIC_DEVICE):")
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = None
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            mark = "  <- default" if i == default_in else ""
            print(f"  [{i}] {d['name']}  (in_ch={d['max_input_channels']}, sr={int(d['default_samplerate'])}){mark}")


def main():
    if "--list-devices" in sys.argv:
        _print_input_devices()
        return
    dev = "system default" if MIC_DEVICE is None else f"CLARA_MIC_DEVICE={MIC_DEVICE!r}"
    print(f"CLARA hotkey listener — hold {HOTKEY.upper()} to talk, release to send. Ctrl+C to quit.")
    print(f"Backend: {BACKEND_URL}  |  speak reply: {SPEAK_REPLY}  |  mic: {dev}")
    print("Tip: if you see 'captured near-silence', run:  python hotkey_listener.py --list-devices")
    keyboard.on_press_key(HOTKEY, lambda e: _start())
    keyboard.on_release_key(HOTKEY, lambda e: threading.Thread(target=_stop_and_send, daemon=True).start())
    try:
        keyboard.wait()           # block forever
    except KeyboardInterrupt:
        print("\nbye.")


if __name__ == "__main__":
    main()
