"""
src/analyzer.py
Snapshot Library Analyzer

Reads every .json file saved in snapshots/ and produces:
  - A Digital Menu table: Drink Name | Primary Tastes | Mood Tag
  - A Global Flavor Profile: dominant dimension, per-dimension averages, library stats

Run from the project root:
    python src/analyzer.py
"""

import json
import sys
from pathlib import Path

_SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "snapshots"

_DIMENSION_ORDER = [
    "Sourness", "Sweetness", "Spiciness", "Saltiness",
    "Umami", "Carbonation", "Bitterness", "Temperature",
]

# Mood tag rules: evaluated in order, first match wins.
_MOOD_RULES = [
    ("Spiciness",   0.50, "Aggressive / Exciting"),
    ("Sourness",    0.60, "Sharp / Awakening"),
    ("Umami",       0.50, "Deep / Satisfying"),
    ("Sweetness",   0.60, "Warm / Comforting"),
    ("Saltiness",   0.50, "Grounding / Mineral"),
    ("Bitterness",  0.60, "Complex / Sophisticated"),
    ("Carbonation", 0.60, "Bright / Effervescent"),
]

W = 78  # report line width


def _mood_tag(intensities: dict) -> str:
    for dim, thr, tag in _MOOD_RULES:
        if intensities.get(dim, 0.0) >= thr:
            return tag
    return "Neutral / Balanced"


def _primary_tastes(intensities: dict, n: int = 3) -> str:
    ranked = sorted(
        [(k, v) for k, v in intensities.items() if k != "Temperature" and v > 0.05],
        key=lambda x: x[1],
        reverse=True,
    )
    return ", ".join(f"{k}({v:.2f})" for k, v in ranked[:n]) if ranked else "-"


def load_snapshots() -> list[dict]:
    snapshots = []
    for path in sorted(_SNAPSHOTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            snapshots.append(data)
        except (json.JSONDecodeError, KeyError):
            print(f"  [WARN] Could not parse {path.name}, skipping.")
    return snapshots


def render_menu(snapshots: list[dict]) -> list[str]:
    col_name   = 26
    col_tastes = 36
    col_mood   = 25
    sep = (
        "+" + "-" * (col_name + 2)
        + "+" + "-" * (col_tastes + 2)
        + "+" + "-" * (col_mood + 2) + "+"
    )
    hdr = (
        f"| {'Drink Name':<{col_name}} "
        f"| {'Primary Tastes (top 3)':<{col_tastes}} "
        f"| {'Mood Tag':<{col_mood}} |"
    )

    lines = [sep, hdr, sep]
    for snap in snapshots:
        label  = snap.get("label", "?")[:col_name]
        ints   = snap.get("intensities", {})
        tastes = _primary_tastes(ints)[:col_tastes]
        mood   = _mood_tag(ints)[:col_mood]
        lines.append(
            f"| {label:<{col_name}} | {tastes:<{col_tastes}} | {mood:<{col_mood}} |"
        )
    lines.append(sep)
    return lines


def global_flavor_profile(snapshots: list[dict]) -> list[str]:
    if not snapshots:
        return ["  No snapshots to analyze."]

    counts = len(snapshots)
    totals: dict[str, float] = {k: 0.0 for k in _DIMENSION_ORDER}

    for snap in snapshots:
        for dim in _DIMENSION_ORDER:
            totals[dim] += snap.get("intensities", {}).get(dim, 0.0)

    averages  = {k: totals[k] / counts for k in _DIMENSION_ORDER}
    overall   = sum(averages.values()) / len(averages)

    non_temp  = {k: v for k, v in averages.items() if k != "Temperature"}
    flavor_mass = sum(non_temp.values())
    dominant  = max(non_temp, key=non_temp.get)
    dom_pct   = (non_temp[dominant] / flavor_mass * 100) if flavor_mass > 0 else 0.0

    bar_w = 22
    def _bar(v: float) -> str:
        filled = round(v * bar_w)
        return "[" + "#" * filled + "-" * (bar_w - filled) + "]"

    lines = [
        f"  Library size     : {counts} snapshot{'s' if counts != 1 else ''}",
        f"  Average intensity: {overall:.3f}  (all 8 dimensions combined)",
        f"  Dominant flavor  : {dominant} ({dom_pct:.0f}% of flavor mass)",
        f"",
        f"  Per-dimension averages:",
    ]
    for dim in _DIMENSION_ORDER:
        v = averages[dim]
        lines.append(f"    {dim:<13} {_bar(v)} {v:.4f}")
    return lines


def build_report(snapshots: list[dict]) -> str:
    rule = "+" + "=" * (W - 2) + "+"
    dash = "+" + "-" * (W - 2) + "+"

    lines = [
        rule,
        f"|  TASTEDATA SNAPSHOT LIBRARY ANALYZER".ljust(W - 1) + "|",
        f"|  Directory: snapshots/   ({len(snapshots)} file{'s' if len(snapshots) != 1 else ''} found)".ljust(W - 1) + "|",
        rule,
        "",
        f"+-- Digital Menu " + "-" * (W - 18) + "+",
    ]
    lines += render_menu(snapshots)
    lines += [
        "",
        f"+-- Global Flavor Profile " + "-" * (W - 27) + "+",
    ]
    lines += global_flavor_profile(snapshots)
    lines += ["", rule]
    return "\n".join(lines)


if __name__ == "__main__":
    snapshots = load_snapshots()

    if not snapshots:
        print(f"  No snapshots found in: {_SNAPSHOTS_DIR}")
        print("  Save snapshots during a session (S key in run_app.py) then re-run.")
        sys.exit(0)

    print(build_report(snapshots))
