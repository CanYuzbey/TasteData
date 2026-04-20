import csv
import datetime
from pathlib import Path

_LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FILE = _LOGS_DIR / "session_history.csv"

_RAW_FIELDS = ["raw_ph", "raw_temp", "raw_brix", "raw_spicy", "raw_co2", "raw_ibu"]
_INTENSITY_FIELDS = ["Sourness", "Sweetness", "Spiciness", "Carbonation", "Bitterness", "Temperature"]
_FIELDNAMES = ["timestamp"] + _RAW_FIELDS + _INTENSITY_FIELDS + ["audio_prompt"]


class SessionLogger:
    def __init__(self) -> None:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        write_header = not _LOG_FILE.exists()
        self._fh = _LOG_FILE.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=_FIELDNAMES)
        if write_header:
            self._writer.writeheader()

    def log_frame(
        self,
        raw_data: dict,
        intensities: dict[str, float],
        audio_prompt: str,
    ) -> None:
        row: dict = {"timestamp": datetime.datetime.now().isoformat(timespec="seconds")}

        raw_keys = {"ph": "raw_ph", "temp": "raw_temp", "brix": "raw_brix",
                    "spicy": "raw_spicy", "co2": "raw_co2", "ibu": "raw_ibu"}
        for src, dst in raw_keys.items():
            row[dst] = raw_data.get(src, 0.0)

        for field in _INTENSITY_FIELDS:
            row[field] = round(intensities.get(field, 0.0), 6)

        row["audio_prompt"] = audio_prompt

        self._writer.writerow(row)
        self._fh.flush()  # persist every frame so a crash loses nothing

    def close(self) -> None:
        self._fh.close()
