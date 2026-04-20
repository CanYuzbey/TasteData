"""
Hardware interface for the TasteData Sensor Node.

Expected serial output from firmware/TasteData_Sensor_Node.ino (10 Hz, 9600 baud):

    ph,temp,brix,shu,co2,ibu,salt,glutamate

All values are floating-point in their native physical units. The firmware also
emits a startup banner beginning with "TASTEDATA_NODE" before streaming data;
this class detects that prefix and logs a hardware handshake confirmation. All
non-CSV lines are silently skipped so the parser is robust across firmware builds.
"""

import logging
import random

try:
    import serial
    import serial.tools.list_ports
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False

logger = logging.getLogger(__name__)

_HANDSHAKE_PREFIX = "TASTEDATA_NODE"

# Field names in the order the firmware transmits them.
# The 'shu' field maps to the key 'spicy' used downstream by brain.py / run_app.py.
_FIELD_NAMES = ["ph", "temp", "brix", "spicy", "co2", "ibu", "salt", "umami"]


class SensorReader:
    # Simulation baseline: a mild sparkling citrus drink
    _SIM_BASE = {
        "ph":    3.5,
        "temp":  18.0,
        "brix":  8.0,
        "spicy": 200.0,
        "co2":   2.5,
        "ibu":   15.0,
        "salt":  1.0,
        "umami": 2.0,
    }

    # Maximum random-walk step per frame
    _SIM_STEP = {
        "ph":    0.05,
        "temp":  0.40,
        "brix":  0.15,
        "spicy": 60.0,
        "co2":   0.06,
        "ibu":   0.50,
        "salt":  0.08,
        "umami": 0.10,
    }

    # Hard bounds that mirror the normalization ranges in config/settings.yaml
    _SIM_BOUNDS = {
        "ph":    (2.5,      5.0),
        "temp":  (0.0,     80.0),
        "brix":  (0.0,     20.0),
        "spicy": (0.0,  50_000.0),
        "co2":   (0.0,      5.0),
        "ibu":   (0.0,    100.0),
        "salt":  (0.0,     10.0),
        "umami": (0.0,     20.0),
    }

    def __init__(self, port: str = "COM3", baud: int = 9600):
        self.simulated = False
        self._serial   = None
        self._sim_state = dict(self._SIM_BASE)
        self._handshake_confirmed = False

        if not _SERIAL_AVAILABLE:
            logger.warning("pyserial not installed — running in simulation mode.")
            self.simulated = True
            return

        try:
            self._serial = serial.Serial(port, baud, timeout=2)
            print(f"[SensorReader] Connected to {port} at {baud} baud.")
        except (serial.SerialException, OSError) as exc:
            print(f"[SensorReader] Hardware not found on {port} ({exc}).")
            self._log_available_ports()
            print("[SensorReader] Falling back to simulation mode.\n")
            self.simulated = True

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_raw_frame(self) -> dict | None:
        """Return one sensor frame as a dict with keys matching _FIELD_NAMES, or None."""
        if self.simulated:
            return self._sim_step()
        return self._read_serial()

    def close(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
            print("[SensorReader] Serial port closed.")

    # -------------------------------------------------------------------------
    # Serial parsing
    # -------------------------------------------------------------------------

    def _read_serial(self) -> dict | None:
        try:
            raw = self._serial.readline().decode("utf-8", errors="replace").strip()
        except (serial.SerialException, OSError) as exc:
            logger.error(f"[SensorReader] Serial disconnected: {exc}. Switching to simulation.")
            self.simulated = True
            self._serial   = None
            return None

        if not raw:
            return None

        # Detect the firmware handshake banner — log once, then continue.
        if raw.startswith(_HANDSHAKE_PREFIX) or raw.startswith("==="):
            if not self._handshake_confirmed:
                print(f"[SensorReader] Hardware handshake received: {raw}")
                self._handshake_confirmed = True
            return None

        # Skip any other non-data lines (mode/rate/schema info lines).
        if not raw[0].isdigit() and raw[0] != '-':
            return None

        parts = raw.split(",")
        if len(parts) != 8:
            logger.warning(
                f"[SensorReader] Expected 8 CSV fields, got {len(parts)}: {raw!r}"
            )
            return None

        try:
            values = [float(p) for p in parts]
        except ValueError:
            logger.warning(f"[SensorReader] Non-numeric value in line: {raw!r}")
            return None

        return dict(zip(_FIELD_NAMES, values))

    # -------------------------------------------------------------------------
    # Simulation
    # -------------------------------------------------------------------------

    def _sim_step(self) -> dict:
        """Nudge each simulated dimension by a small random step (bounded random walk)."""
        for key in self._sim_state:
            delta      = random.uniform(-self._SIM_STEP[key], self._SIM_STEP[key])
            lo, hi     = self._SIM_BOUNDS[key]
            self._sim_state[key] = max(lo, min(hi, self._sim_state[key] + delta))
        return dict(self._sim_state)

    # -------------------------------------------------------------------------

    @staticmethod
    def _log_available_ports() -> None:
        if not _SERIAL_AVAILABLE:
            return
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if ports:
            print(f"[SensorReader] Available ports: {', '.join(ports)}")
        else:
            print("[SensorReader] No serial ports detected.")
