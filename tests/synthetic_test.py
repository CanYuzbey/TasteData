"""
TasteData Synthetic Test Suite
Verifies brain.py against analytically computed expected values.

Each test case is self-contained:
  1. Define raw sensor inputs.
  2. Compute expected intensities by hand (documented inline).
  3. Run TasteMapper.process_data() with reset_ema() between cases.
  4. Compare with absolute tolerance TOL = 1e-4.

NOTE: EMA first-frame identity
  After reset_ema(), _prev_intensities is empty.
  _apply_ema uses: a * val + (1-a) * prev.get(key, val)
  When key is absent, default = val  =>  result = a*val + (1-a)*val = val.
  Therefore: first frame after reset = power-law + interaction values, no smoothing.

Run from project root:
    python tests/synthetic_test.py
"""

import sys
import math
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.brain import TasteMapper

TOL      = 1e-4   # absolute tolerance for float comparison
W        = 70     # report line width
PASS_SYM = "PASS"
FAIL_SYM = "FAIL"


# ---------------------------------------------------------------------------
# Helper: power law (mirrors brain.py exactly)
# ---------------------------------------------------------------------------

def _pl(v: float, n: float) -> float:
    """Stevens's Power Law with brain.py's safety guards."""
    c = max(0.0, min(1.0, v))
    if c == 0.0:
        return 0.0
    if n <= 0.0:
        return 1.0
    return math.pow(c, n)


def _norm(raw, lo, hi):
    return (raw - lo) / (hi - lo)


# ---------------------------------------------------------------------------
# Settings (mirrors config/settings.yaml -- duplicated here so the test is
# self-documenting; if you change the YAML, update these constants too).
# ---------------------------------------------------------------------------

PH_MIN, PH_MAX         = 2.5, 5.0
TEMP_MIN, TEMP_MAX     = 0.0, 80.0
BRIX_MIN, BRIX_MAX     = 0.0, 20.0
SHU_MIN, SHU_MAX       = 0.0, 50_000.0
CO2_MIN, CO2_MAX       = 0.0, 5.0
IBU_MIN, IBU_MAX       = 0.0, 100.0
SALT_MIN, SALT_MAX     = 0.0, 10.0
GLUT_MIN, GLUT_MAX     = 0.0, 20.0

N_SWEET  = 1.3
N_SPICY  = 0.8
N_SOUR   = 1.1
N_BITTER = 1.3
N_SALT   = 1.4
N_UMAMI  = 1.0
N_CARB   = 1.1

SALT_BITTER_THRESH = 0.30
SALT_BITTER_REDUCE = 0.20
SWEET_SOUR_THRESH  = 0.50
SWEET_SOUR_REDUCE  = 0.15
HEAT_SPICY_THRESH  = 0.70
HEAT_SPICY_BOOST   = 0.10


def _base(raw_ph, raw_temp, raw_brix, raw_spicy,
          raw_co2=0.0, raw_ibu=0.0, raw_salt=0.0, raw_umami=0.0):
    """Compute expected intensities analytically (pre-EMA, since first frame = identity)."""
    sourness_in = 1.0 - _norm(raw_ph,    PH_MIN,   PH_MAX)
    norm_temp   = _norm(raw_temp,  TEMP_MIN, TEMP_MAX)
    norm_brix   = _norm(raw_brix,  BRIX_MIN, BRIX_MAX)
    norm_spicy  = _norm(raw_spicy, SHU_MIN,  SHU_MAX)
    norm_co2    = _norm(raw_co2,   CO2_MIN,  CO2_MAX)
    norm_ibu    = _norm(raw_ibu,   IBU_MIN,  IBU_MAX)
    norm_salt   = _norm(raw_salt,  SALT_MIN, SALT_MAX)
    norm_glut   = _norm(raw_umami, GLUT_MIN, GLUT_MAX)

    clamp = lambda v: max(0.0, min(1.0, v))

    r = {
        "Sourness":    _pl(clamp(sourness_in), N_SOUR),
        "Sweetness":   _pl(clamp(norm_brix),   N_SWEET),
        "Spiciness":   _pl(clamp(norm_spicy),  N_SPICY),
        "Saltiness":   _pl(clamp(norm_salt),   N_SALT),
        "Umami":       _pl(clamp(norm_glut),   N_UMAMI),
        "Carbonation": _pl(clamp(norm_co2),    N_CARB),
        "Bitterness":  _pl(clamp(norm_ibu),    N_BITTER),
        "Temperature": clamp(norm_temp),
    }

    # --- Interaction rules (same order as brain.py) ---
    if r["Saltiness"] > SALT_BITTER_THRESH:
        r["Bitterness"] *= (1.0 - SALT_BITTER_REDUCE)
    if r["Sweetness"] > SWEET_SOUR_THRESH:
        r["Sourness"] *= (1.0 - SWEET_SOUR_REDUCE)
    if r["Temperature"] > HEAT_SPICY_THRESH:
        r["Spiciness"] = min(1.0, r["Spiciness"] * (1.0 + HEAT_SPICY_BOOST))

    return r


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

TESTS: list[dict] = []


def _add(name: str, note: str, raw: dict, expected: dict):
    TESTS.append({"name": name, "note": note, "raw": raw, "expected": expected})


# -- 1. Pure Dimensions (isolate one input at a time) ----------------------

_add(
    "Pure Sweetness",
    "Max brix, flat pH (neutral), room temp -- only Sweetness should saturate",
    raw=dict(raw_ph=5.0, raw_temp=20, raw_brix=20.0, raw_spicy=0,
             raw_co2=0, raw_ibu=0, raw_salt=0, raw_umami=0),
    # norm_brix=1.0 -> Sweet = 1.0^1.3 = 1.0
    # sourness_in = 1-(5.0-2.5)/2.5 = 0.0 -> Sour = 0.0
    # temp = 20/80 = 0.25, no interactions
    expected=_base(5.0, 20, 20.0, 0),
)

_add(
    "Pure Sourness",
    "Minimum pH (2.5) -> max sourness inversion, zero everything else",
    raw=dict(raw_ph=2.5, raw_temp=20, raw_brix=0, raw_spicy=0,
             raw_co2=0, raw_ibu=0, raw_salt=0, raw_umami=0),
    # norm_ph=0.0 -> sourness_in=1.0 -> Sour = 1.0^1.1 = 1.0
    expected=_base(2.5, 20, 0, 0),
)

_add(
    "Pure Bitterness",
    "Max IBU, neutral pH, no other dimensions",
    raw=dict(raw_ph=5.0, raw_temp=20, raw_brix=0, raw_spicy=0,
             raw_co2=0, raw_ibu=100, raw_salt=0, raw_umami=0),
    # norm_ibu=1.0 -> Bitter = 1.0^1.3 = 1.0
    expected=_base(5.0, 20, 0, 0, raw_ibu=100),
)

_add(
    "Pure Spiciness",
    "Max SHU, no heat, no other dimensions",
    raw=dict(raw_ph=5.0, raw_temp=20, raw_brix=0, raw_spicy=50_000,
             raw_co2=0, raw_ibu=0, raw_salt=0, raw_umami=0),
    # norm_spicy=1.0 -> Spicy = 1.0^0.8 = 1.0; temp=0.25 < 0.70 -> no boost
    expected=_base(5.0, 20, 0, 50_000),
)

_add(
    "Pure Saltiness",
    "Max salt, all else neutral",
    raw=dict(raw_ph=5.0, raw_temp=20, raw_brix=0, raw_spicy=0,
             raw_co2=0, raw_ibu=0, raw_salt=10.0, raw_umami=0),
    # norm_salt=1.0 -> Salt = 1.0^1.4 = 1.0
    # IBU=0 so bitterness=0 -- salt interaction still fires but 0*0.8=0
    expected=_base(5.0, 20, 0, 0, raw_salt=10.0),
)

_add(
    "Pure Umami",
    "Max glutamate, all else neutral",
    raw=dict(raw_ph=5.0, raw_temp=20, raw_brix=0, raw_spicy=0,
             raw_co2=0, raw_ibu=0, raw_salt=0, raw_umami=20.0),
    # norm_glut=1.0 -> Umami = 1.0^1.0 = 1.0
    expected=_base(5.0, 20, 0, 0, raw_umami=20.0),
)

_add(
    "Pure Carbonation",
    "Max CO2, all else neutral",
    raw=dict(raw_ph=5.0, raw_temp=20, raw_brix=0, raw_spicy=0,
             raw_co2=5.0, raw_ibu=0, raw_salt=0, raw_umami=0),
    # norm_co2=1.0 -> Carb = 1.0^1.1 = 1.0
    expected=_base(5.0, 20, 0, 0, raw_co2=5.0),
)

# -- 2. Interaction Rules ---------------------------------------------------

_add(
    "Interaction: Salt suppresses Bitter",
    "Salt=5g/L (norm=0.5 -> psi=0.3794 > 0.30) reduces IBU=80 bitterness by 20%",
    raw=dict(raw_ph=5.0, raw_temp=20, raw_brix=0, raw_spicy=0,
             raw_co2=0, raw_ibu=80, raw_salt=5.0, raw_umami=0),
    # Bitter_raw = 0.8^1.3 ~= 0.7482;  Salt_psi = 0.5^1.4 ~= 0.3794
    # 0.3794 > 0.30 -> Bitter *= 0.80 -> ~= 0.5986
    expected=_base(5.0, 20, 0, 0, raw_ibu=80, raw_salt=5.0),
)

_add(
    "Interaction: Sweet suppresses Sour",
    "Brix=12 (norm=0.6 -> psi=0.5150 > 0.50) reduces min-pH sourness by 15%",
    raw=dict(raw_ph=2.5, raw_temp=20, raw_brix=12, raw_spicy=0,
             raw_co2=0, raw_ibu=0, raw_salt=0, raw_umami=0),
    # Sour_raw = 1.0^1.1 = 1.0;  Sweet_psi = 0.6^1.3 ~= 0.5150
    # 0.5150 > 0.50 -> Sour *= 0.85 -> 0.85
    expected=_base(2.5, 20, 12, 0),
)

_add(
    "Interaction: Heat boosts Spicy",
    "Temp=80C (norm=1.0 > 0.70) boosts SHU=10000 spiciness by 10%",
    raw=dict(raw_ph=5.0, raw_temp=80, raw_brix=0, raw_spicy=10_000,
             raw_co2=0, raw_ibu=0, raw_salt=0, raw_umami=0),
    # Spicy_raw = 0.2^0.8 ~= 0.2759;  Temp = 1.0 > 0.70
    # -> Spicy = min(1.0, 0.2759 * 1.10) ~= 0.3035
    expected=_base(5.0, 80, 0, 10_000),
)

_add(
    "Interaction: Salt threshold not met (no suppression)",
    "Salt=2g/L (norm=0.2 -> psi~=0.1742 < 0.30): bitterness unchanged",
    raw=dict(raw_ph=5.0, raw_temp=20, raw_brix=0, raw_spicy=0,
             raw_co2=0, raw_ibu=80, raw_salt=2.0, raw_umami=0),
    # Salt_psi = 0.2^1.4 = e^(1.4*ln(0.2)) ~= 0.1742 < 0.30 -> no interaction
    expected=_base(5.0, 20, 0, 0, raw_ibu=80, raw_salt=2.0),
)

_add(
    "Interaction: Sweet threshold not met (no sourness suppression)",
    "Brix=8 (norm=0.4 -> psi~=0.3281 < 0.50): sourness unchanged",
    raw=dict(raw_ph=2.5, raw_temp=20, raw_brix=8, raw_spicy=0,
             raw_co2=0, raw_ibu=0, raw_salt=0, raw_umami=0),
    # Sweet_psi = 0.4^1.3 = e^(1.3*ln(0.4)) ~= 0.3281 < 0.50 -> no interaction
    expected=_base(2.5, 20, 8, 0),
)

_add(
    "Interaction: All three fire simultaneously",
    "Max everything: salt>0.3 + sweet>0.5 + temp>0.7 all apply",
    raw=dict(raw_ph=2.5, raw_temp=80, raw_brix=20, raw_spicy=50_000,
             raw_co2=5.0, raw_ibu=100, raw_salt=10.0, raw_umami=20.0),
    # Salt=1.0>0.30 -> Bitter*=0.80; Sweet=1.0>0.50 -> Sour*=0.85; Temp=1.0>0.70 -> Spicy=min(1,1.0*1.1)=1.0
    expected=_base(2.5, 80, 20, 50_000, raw_co2=5.0, raw_ibu=100, raw_salt=10.0, raw_umami=20.0),
)

# -- 3. Real-world food profiles -------------------------------------------

_add(
    "Classic Cola",
    "High acid, moderate sugar, strong carbonation, trace bitterness",
    raw=dict(raw_ph=2.8, raw_temp=4, raw_brix=11.0, raw_spicy=0,
             raw_co2=3.5, raw_ibu=2.0, raw_salt=0, raw_umami=0),
    expected=_base(2.8, 4, 11.0, 0, raw_co2=3.5, raw_ibu=2.0),
)

_add(
    "Double Espresso",
    "High IBU bitterness, very hot, trace sweetness (Brix=1), neutral sourness",
    raw=dict(raw_ph=5.0, raw_temp=90, raw_brix=1.0, raw_spicy=0,
             raw_co2=0, raw_ibu=80, raw_salt=0, raw_umami=0),
    # temp=90 clamped -> norm=(90-0)/80=1.125 -> clamped to 1.0
    expected=_base(5.0, 90, 1.0, 0, raw_ibu=80),
)

_add(
    "Miso Soup",
    "High umami + salt, warm temperature, near-neutral pH",
    raw=dict(raw_ph=4.9, raw_temp=68, raw_brix=2.0, raw_spicy=0,
             raw_co2=0, raw_ibu=0, raw_salt=8.5, raw_umami=16.0),
    # Salt=8.5 -> norm=0.85 -> psi=0.85^1.4 > 0.30 -> Bitter (=0) *= 0.80 (still 0)
    # Temp=68 -> norm=0.85 > 0.70 -> Spicy=min(1, 0*1.1)=0.0
    expected=_base(4.9, 68, 2.0, 0, raw_salt=8.5, raw_umami=16.0),
)

_add(
    "Double Espresso (Salted)",
    "Demonstrates salt-bitter suppression on a real drink profile",
    raw=dict(raw_ph=5.0, raw_temp=90, raw_brix=1.0, raw_spicy=0,
             raw_co2=0, raw_ibu=80, raw_salt=5.0, raw_umami=0),
    expected=_base(5.0, 90, 1.0, 0, raw_ibu=80, raw_salt=5.0),
)

# -- 4. Edge Cases ---------------------------------------------------------

_add(
    "All-zero inputs",
    "Plain neutral water: pH=5.0 (no sourness), everything else zero",
    raw=dict(raw_ph=5.0, raw_temp=0, raw_brix=0, raw_spicy=0,
             raw_co2=0, raw_ibu=0, raw_salt=0, raw_umami=0),
    # Only Temperature=0.0; all taste dims=0.0
    expected=_base(5.0, 0, 0, 0),
)

_add(
    "Out-of-range temp (clamped at 1.0)",
    "raw_temp=90 exceeds TEMP_MAX=80; norm=1.125 clamped to 1.0",
    raw=dict(raw_ph=5.0, raw_temp=90, raw_brix=0, raw_spicy=0,
             raw_co2=0, raw_ibu=0, raw_salt=0, raw_umami=0),
    # norm_temp=1.125 -> clamped to 1.0
    expected=_base(5.0, 90, 0, 0),
)

_add(
    "Mid-range all dimensions",
    "0.5 normalized across every input -- tests power-law curves at the inflection zone",
    raw=dict(raw_ph=3.75, raw_temp=40, raw_brix=10, raw_spicy=25_000,
             raw_co2=2.5, raw_ibu=50, raw_salt=5.0, raw_umami=10),
    # All norms = 0.5; salt_psi = 0.5^1.4 ~= 0.3794 > 0.30 -> Bitter *= 0.80
    # sweet_psi = 0.5^1.3 ~= 0.4061 < 0.50 -> no sourness suppression
    # temp = 0.5 < 0.70 -> no heat boost
    expected=_base(3.75, 40, 10, 25_000, raw_co2=2.5, raw_ibu=50, raw_salt=5.0, raw_umami=10),
)

_add(
    "EMA first-frame identity",
    "After reset_ema(), first frame output equals computed values (no smoothing lag)",
    raw=dict(raw_ph=3.0, raw_temp=30, raw_brix=5, raw_spicy=5_000,
             raw_co2=1.5, raw_ibu=20, raw_salt=3.0, raw_umami=4.0),
    expected=_base(3.0, 30, 5, 5_000, raw_co2=1.5, raw_ibu=20, raw_salt=3.0, raw_umami=4.0),
)


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests() -> tuple[int, int, list[str]]:
    """Returns (passed, failed, lines_for_report)."""
    mapper  = TasteMapper()
    passed  = 0
    failed  = 0
    lines: list[str] = []

    sep      = "+" + "-" * (W - 2) + "+"
    thick    = "+" + "=" * (W - 2) + "+"
    dims     = ["Sourness", "Sweetness", "Spiciness", "Saltiness",
                "Umami", "Carbonation", "Bitterness", "Temperature"]

    lines.append(thick)
    lines.append(f"|  TASTEDATA SYNTHETIC TEST SUITE".ljust(W - 1) + "|")
    lines.append(f"|  {len(TESTS)} test cases  |  tolerance = {TOL:.0e}".ljust(W - 1) + "|")
    lines.append(thick)

    for idx, tc in enumerate(TESTS, start=1):
        mapper.reset_ema()
        result = mapper.process_data(**tc["raw"])
        exp    = tc["expected"]

        failures: list[tuple[str, float, float]] = []
        for dim in dims:
            got  = result.get(dim, 0.0)
            want = exp.get(dim, 0.0)
            if abs(got - want) > TOL:
                failures.append((dim, got, want))

        status = PASS_SYM if not failures else FAIL_SYM
        if not failures:
            passed += 1
        else:
            failed += 1

        lines.append(sep)
        lines.append(f"|  [{status}] #{idx:02d}: {tc['name']}".ljust(W - 1) + "|")
        lines.append(f"|       {tc['note']}".ljust(W - 1) + "|")
        lines.append("|")

        def _bar(v: float, width: int = 22) -> str:
            filled = round(v * width)
            return "[" + "#" * filled + "-" * (width - filled) + "]"

        for dim in dims:
            got  = result.get(dim, 0.0)
            want = exp.get(dim, 0.0)
            diff = abs(got - want)
            flag = " !! MISMATCH !!" if diff > TOL else ""
            lines.append(
                f"|    {dim:<13} got={got:.6f}  exp={want:.6f}  "
                f"d={diff:.1e}{flag}".ljust(W - 1) + "|"
            )

        if failures:
            lines.append("|")
            lines.append(f"|  FAILED dimensions: {', '.join(d for d,_,_ in failures)}".ljust(W - 1) + "|")

    lines.append(thick)
    lines.append(f"|  Results: {passed} passed  {failed} failed  ({len(TESTS)} total)".ljust(W - 1) + "|")
    lines.append(thick)
    return passed, failed, lines


if __name__ == "__main__":
    passed, failed, lines = run_tests()
    report = "\n".join(lines)
    print(report)

    out = Path(__file__).resolve().parent.parent / "docs" / "synthetic_test_report.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\n  Report saved to {out.relative_to(Path(__file__).resolve().parent.parent)}")

    sys.exit(0 if failed == 0 else 1)
