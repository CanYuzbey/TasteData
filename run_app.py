"""
TasteData — main entry point
Usage:
    python run_app.py           # auto-detects hardware, falls back to simulation
    python run_app.py COM3      # Windows serial port
    python run_app.py /dev/ttyUSB0  # Linux / macOS

Interactive commands while running:
    S + Enter  ->  save a labeled snapshot to snapshots/
    Q + Enter  ->  graceful shutdown
    Ctrl+C     ->  immediate shutdown
"""

import queue
import sys
import threading
import time

from src.sensors import SensorReader
from src.brain import TasteMapper
from src.bridge import send_osc_data
from src.logger import SessionLogger

POLL_INTERVAL_SEC = 0.1  # 10 Hz — matches the Arduino delay(100)


def _cli_thread(cmd_queue: queue.Queue, stop: threading.Event) -> None:
    """Daemon thread: reads stdin and puts (command, arg) pairs on the queue."""
    while not stop.is_set():
        try:
            key = input().strip().upper()
        except EOFError:
            break
        if key == "Q":
            cmd_queue.put(("quit", None))
            break
        elif key == "S":
            try:
                label = input("  Snapshot label > ").strip()
            except EOFError:
                break
            if label:
                cmd_queue.put(("snapshot", label))


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "COM3"

    reader = SensorReader(port=port)
    mapper = TasteMapper()
    logger = SessionLogger()

    mode = "SIMULATION" if reader.simulated else f"HARDWARE ({port})"
    print(f"TasteData running in {mode} mode. Logging to logs/session_history.csv.")
    print("Commands: [S] Save snapshot   [Q] Quit\n")

    cmd_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()
    cli = threading.Thread(target=_cli_thread, args=(cmd_queue, stop_event), daemon=True)
    cli.start()

    last_raw: dict = {}

    try:
        while True:
            # --- Process CLI commands (non-blocking) ---
            try:
                cmd, arg = cmd_queue.get_nowait()
                if cmd == "quit":
                    print("Shutting down.")
                    break
                elif cmd == "snapshot":
                    if not last_raw:
                        print("  [Snapshot] No frame received yet — try again in a moment.")
                    else:
                        # Convert sensor-key frame to process_data keyword args
                        snapshot_data = {
                            "raw_ph":    last_raw["ph"],
                            "raw_temp":  last_raw["temp"],
                            "raw_brix":  last_raw["brix"],
                            "raw_spicy": last_raw["spicy"],
                            "raw_co2":   last_raw.get("co2",   0.0),
                            "raw_ibu":   last_raw.get("ibu",   0.0),
                            "raw_salt":  last_raw.get("salt",  0.0),
                            "raw_umami": last_raw.get("umami", 0.0),
                        }
                        path = mapper.save_flavor_snapshot(arg, snapshot_data)
                        print(f"\n  [Snapshot] '{arg}' saved -> {path.name}\n")
            except queue.Empty:
                pass

            # --- Pipeline: Sensors -> Brain -> TouchDesigner + Logger ---
            frame = reader.get_raw_frame()

            if frame is None:
                time.sleep(POLL_INTERVAL_SEC)
                continue

            last_raw = frame

            intensities = mapper.process_data(
                raw_ph=frame["ph"],
                raw_temp=frame["temp"],
                raw_brix=frame["brix"],
                raw_spicy=frame["spicy"],
                raw_co2=frame.get("co2", 0.0),
                raw_ibu=frame.get("ibu", 0.0),
                raw_salt=frame.get("salt", 0.0),
                raw_umami=frame.get("umami", 0.0),
            )
            visual = mapper.get_visual_params(intensities)
            audio_prompt = mapper.generate_audio_prompt(intensities)
            send_osc_data(visual, audio_prompt)
            logger.log_frame(frame, intensities, audio_prompt)
            # ------------------------------------------------------------

            time.sleep(POLL_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stop_event.set()
        reader.close()
        logger.close()


if __name__ == "__main__":
    main()
