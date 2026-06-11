"""ambient_watch.py — CLARA Ambient Awareness A0: the standalone 24/7 perception
process (BRIEF_39, amended split design).

Featherweight by contract: no GPU, no models, NO API KEYS. Samples consent-gated
sensors (AMBIENT_SENSORS in core_logic/.env) and writes core_logic/ambient.json —
it is the ONLY writer of that file. The backend only reads.

Run manually:        python ambient_watch.py
Run 24/7 (Alkama):   Task Scheduler, at logon, restart-on-failure (see BRIEF_39)
Kill switch:         end this process (or remove sensors from AMBIENT_SENSORS
                     and restart) — ambient perception stops, fully and visibly.
Single instance:     guarded by a localhost socket bind; a second copy exits.
"""

import os
import socket
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, "core_logic", ".env"))

from core_logic.ambient import AmbientStore, SENSOR_CLASSES, enabled_sensors

SINGLETON_PORT = 8771            # bind fails -> another watcher is already running
LOG_PATH = os.path.join(ROOT, "logs", "ambient_watch.log")
LOG_MAX_BYTES = 2_000_000        # tiny self-rotation: truncate when oversized


def log(msg: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}\n"
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    try:
        print(line, end="")
    except Exception:
        pass


def main() -> int:
    # Single-instance guard
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        guard.bind(("127.0.0.1", SINGLETON_PORT))
    except OSError:
        log("[ambient] another watcher instance is running - exiting.")
        return 0

    names = enabled_sensors()
    if not names:
        log("[ambient] AMBIENT_SENSORS is empty/unset - nothing consented, exiting. "
            "(Set e.g. AMBIENT_SENSORS=active_window,system_state,session_rhythm "
            "in core_logic/.env to enable.)")
        return 0

    sensors = [SENSOR_CLASSES[n]() for n in names]
    store = AmbientStore()
    log(f"[ambient] watcher started. sensors={names} "
        f"store={len(store._data['observations'])} existing observations")

    next_due = {s.name: 0.0 for s in sensors}
    try:
        while True:
            now = time.monotonic()
            for s in sensors:
                if now < next_due[s.name]:
                    continue
                next_due[s.name] = now + s.interval_s
                try:
                    payload = s.sample()
                except Exception as e:
                    log(f"[ambient] sensor {s.name} error: {e}")
                    continue
                if payload is not None:
                    store.append(s.name, payload)
            store.flush()
            time.sleep(5)
    except KeyboardInterrupt:
        log("[ambient] stopped by user.")
    finally:
        store.flush(force=True)
        guard.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
