"""
TasteData Validation Battery
Run from the project root: python tests/run_battery.py
Prints a report to the terminal and writes docs/validation_report.txt.
"""

import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.brain import TasteMapper

# ---------------------------------------------------------------------------
# Standard Food Profiles
# Values are real-world approximations for cross-laboratory validation.
# ---------------------------------------------------------------------------
PROFILES: dict[str, dict] = {
    "Double Espresso": {
        "raw_ph": 5.0, "raw_temp": 90, "raw_brix": 1.0,
        "raw_spicy": 0, "raw_co2": 0.0, "raw_ibu": 80.0,
        "note": "High bitterness, near-neutral pH, very hot",
    },
    "Classic Cola": {
        "raw_ph": 2.8, "raw_temp": 4, "raw_brix": 11.0,
        "raw_spicy": 0, "raw_co2": 3.5, "raw_ibu": 2.0,
        "note": "High acidity, moderate sweetness, strong carbonation",
    },
    "Extreme Hot Sauce": {
        "raw_ph": 3.5, "raw_temp": 22, "raw_brix": 3.0,
        "raw_spicy": 40_000, "raw_co2": 0.0, "raw_ibu": 0.0,
        "note": "Habanero-level SHU, mildly acidic, almost no sweetness",
    },
    "Tonic Water": {
        "raw_ph": 2.5, "raw_temp": 4, "raw_brix": 8.0,
        "raw_spicy": 0, "raw_co2": 4.2, "raw_ibu": 35.0,
        "note": "Maximum sourness, quinine bitterness, high carbonation",
    },
    "Sparkling Bitter-Lemon": {
        "raw_ph": 2.8, "raw_temp": 5, "raw_brix": 8.0,
        "raw_spicy": 0, "raw_co2": 4.0, "raw_ibu": 40.0,
        "note": "Reference profile from development sessions",
    },
    "Miso Soup": {
        "raw_ph": 4.9, "raw_temp": 68, "raw_brix": 2.0,
        "raw_spicy": 0, "raw_co2": 0.0, "raw_ibu": 0.0,
        "raw_salt": 8.5, "raw_umami": 16.0,
        "note": "High glutamate umami, strong salt, near-neutral pH",
    },
    "Sea Water": {
        "raw_ph": 4.5, "raw_temp": 15, "raw_brix": 0.0,
        "raw_spicy": 0, "raw_co2": 0.0, "raw_ibu": 0.0,
        "raw_salt": 10.0, "raw_umami": 2.0,
        "note": "Extreme salt (clamped at range ceiling), minimal other dimensions",
    },
    "Double Espresso (Salted)": {
        "raw_ph": 5.0, "raw_temp": 90, "raw_brix": 1.0,
        "raw_spicy": 0, "raw_co2": 0.0, "raw_ibu": 80.0,
        "raw_salt": 5.0, "raw_umami": 0.0,
        "note": "Suppression validation: salt reduces perceived bitterness by 20%",
    },
}

BAR_WIDTH   = 24   # character width of intensity bar
LINE_WIDTH  = 66   # total report width


def _bar(value: float) -> str:
    filled = round(value * BAR_WIDTH)
    return "[" + "#" * filled + "-" * (BAR_WIDTH - filled) + "]"


def _section(title: str) -> str:
    pad = LINE_WIDTH - 4 - len(title)
    return f"+-- {title} " + "-" * max(0, pad) + "+"


def _render_profile(index: int, name: str, raw: dict, mapper: TasteMapper) -> list[str]:
    note = raw.pop("note", "")
    intensities = mapper.process_data(**raw)
    audio       = mapper.generate_audio_prompt(intensities)
    visual      = mapper.get_visual_params(intensities)

    lines: list[str] = []
    lines.append(_section(f"{index}. {name}"))
    if note:
        lines.append(f"|  Note   : {note}")

    raw_str = (
        f"pH={raw['raw_ph']:.1f}  Temp={raw['raw_temp']}C  "
        f"Brix={raw['raw_brix']:.1f}  SHU={int(raw['raw_spicy'])}  "
        f"CO2={raw['raw_co2']:.1f}vol  IBU={raw['raw_ibu']:.0f}"
    )
    lines.append(f"|  Input  : {raw_str}")
    salt  = raw.get("raw_salt",  0.0)
    umami = raw.get("raw_umami", 0.0)
    if salt or umami:
        lines.append(f"|           Salt={salt:.1f}g/L  Umami={umami:.1f}gu")
    lines.append("|")

    intensity_order = ["Sourness", "Sweetness", "Spiciness", "Saltiness", "Umami",
                       "Carbonation", "Bitterness", "Temperature"]
    for key in intensity_order:
        val = intensities.get(key, 0.0)
        marker = " <" if val >= mapper._AUDIO_THRESHOLD else "  "
        lines.append(f"|  {key:<13} {_bar(val)} {val:.4f}{marker}")

    lines.append("|")
    r, g, b = visual["color_rgb"]
    lines.append(f"|  Visual : RGB({r:3d},{g:3d},{b:3d})  angularity={visual['shape_angularity']:.3f}  noise={visual['noise_level']:.3f}")
    lines.append("|")
    lines.append(f"|  Sonic Seasoning:")

    # Word-wrap the audio prompt at LINE_WIDTH - 5
    wrap = LINE_WIDTH - 5
    prompt = audio
    while len(prompt) > wrap:
        cut = prompt[:wrap].rfind(" ")
        cut = cut if cut > 0 else wrap
        lines.append(f"|    {prompt[:cut]}")
        prompt = prompt[cut:].lstrip()
    lines.append(f"|    {prompt}")

    lines.append("+" + "-" * (LINE_WIDTH - 1) + "+")
    return lines


def build_report(mapper: TasteMapper) -> str:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = [
        "+" + "=" * (LINE_WIDTH - 1) + "+",
        f"|  TASTEDATA VALIDATION BATTERY".ljust(LINE_WIDTH - 1) + "|",
        f"|  Generated : {timestamp}".ljust(LINE_WIDTH - 1) + "|",
        f"|  Threshold : intensity >= {mapper._AUDIO_THRESHOLD:.2f} marked with <".ljust(LINE_WIDTH - 1) + "|",
        "+" + "=" * (LINE_WIDTH - 1) + "+",
        "",
    ]

    body: list[str] = []
    for i, (name, raw) in enumerate(PROFILES.items(), start=1):
        mapper.reset_ema()          # isolate each profile from prior EMA state
        raw_copy = dict(raw)        # _render_profile pops 'note'
        body.extend(_render_profile(i, name, raw_copy, mapper))
        body.append("")

    footer = [
        f"  {len(PROFILES)} profiles processed.",
        f"  Settings loaded from: config/settings.yaml",
    ]

    return "\n".join(header + body + footer)


if __name__ == "__main__":
    mapper = TasteMapper()
    report = build_report(mapper)

    print(report)

    out_path = Path(__file__).resolve().parent.parent / "docs" / "validation_report.txt"
    out_path.write_text(report, encoding="utf-8")
    print(f"\n  Report saved to {out_path.relative_to(Path(__file__).resolve().parent.parent)}")
