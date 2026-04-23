"""
tests/demo_comparison.py
Hand-computed expected values vs. actual engine output.

Three profiles chosen for maximum contrast:
  1. Sparkling Lemonade  -- max Sourness + Carbonation, ice-cold
  2. Miso Soup           -- max Umami + Saltiness, very hot
  3. Extreme Hot Sauce   -- near-max Spiciness + high Sourness, room temp
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.brain import TasteMapper
from src.prompt_engine import compute_axes, select_genre, generate_bundle, _bpm, _key_mood, _channel_count


# ---------------------------------------------------------------------------
# Hand-computed expected values
# (all derived analytically -- see comments for derivation)
# ---------------------------------------------------------------------------

# Settings constants (from config/settings.yaml)
PH_MIN, PH_MAX       = 2.5, 5.0
BRIX_MIN, BRIX_MAX   = 0.0, 20.0
TEMP_MIN, TEMP_MAX   = 0.0, 80.0
SHU_MIN, SHU_MAX     = 0.0, 50000.0
CO2_MIN, CO2_MAX     = 0.0, 5.0
SALT_MIN, SALT_MAX   = 0.0, 10.0
GLU_MIN, GLU_MAX     = 0.0, 20.0
IBU_MIN, IBU_MAX     = 0.0, 100.0

def pl(v, n):
    """Stevens's Power Law with guards (mirrors brain.py)."""
    v = max(0.0, min(1.0, v))
    if v == 0.0: return 0.0
    if n <= 0.0: return 1.0
    return v ** n

def clamp(v):
    return max(0.0, min(1.0, v))


EXPECTED = {
    # -----------------------------------------------------------------------
    # 1. Sparkling Lemonade
    # raw_ph=2.5 -> sourness_in = 1 - (2.5-2.5)/2.5 = 1.0
    # norm_brix  = 10/20 = 0.50,  pl(0.50, 1.3) = 0.50^1.3
    # norm_co2   = 4.0/5.0 = 0.80  (linear, no power law)
    # norm_temp  = 4/80   = 0.05   (linear, no power law)
    # NO interactions trigger (salt<0.30, sweet<0.50, temp<0.70)
    # -----------------------------------------------------------------------
    "Sparkling Lemonade": {
        "raw": dict(raw_ph=2.5, raw_temp=4, raw_brix=10.0,
                    raw_spicy=0, raw_co2=4.0, raw_ibu=0, raw_salt=0, raw_umami=0),
        "intensities": {
            "Sourness":    round(pl(1.0,  1.1), 4),     # = 1.0000
            "Sweetness":   round(pl(0.50, 1.3), 4),     # = 0.4061
            "Spiciness":   0.0,
            "Saltiness":   0.0,
            "Umami":       0.0,
            "Carbonation": round(pl(0.80, 1.1), 4),   # 0.80^1.1, was linear before fix
            "Bitterness":  0.0,
            "Temperature": 0.05,
        },
        "axes": {
            # energy = 0*0.40 + 1.0*0.25 + pl(0.80,1.1)*0.20 + 0.05*0.10 + 0*0.05
            "energy":   round(clamp(0*0.40 + 1.0*0.25 + pl(0.80,1.1)*0.20 + 0.05*0.10 + 0*0.05), 3),
            # warmth = 0.4061*0.40 + 0*0.30 + 0.05*0.20 - 0*0.10 = 0.1724
            "warmth":   round(clamp(pl(0.50,1.3)*0.40 + 0*0.30 + 0.05*0.20 - 0*0.10), 3),
            # darkness = 0*0.45 + 1.0*0.25 + (1-0.4061)*0.20 + (1-0.05)*0.10 = 0.464
            "darkness": round(clamp(0*0.45 + 1.0*0.25 + (1-pl(0.50,1.3))*0.20 + (1-0.05)*0.10), 3),
            # texture = pl(0.80,1.1)*0.50 + 0*0.30 + 0*0.20
            "texture":  round(clamp(pl(0.80,1.1)*0.50 + 0*0.30 + 0*0.20), 3),
            # richness = 0*0.45 + 0.4061*0.30 + 0*0.25 = 0.122
            "richness": round(clamp(0*0.45 + pl(0.50,1.3)*0.30 + 0*0.25), 3),
            "temp_feel": 0.05,
        },
        "genre":    "Minimal Techno",
        "bpm":      122,
        "key":      "Dorian",
        "n_channels": 3,
    },

    # -----------------------------------------------------------------------
    # 2. Miso Soup
    # norm_ph   = (4.9-2.5)/2.5 = 0.96 -> sourness_in = 0.04
    # norm_temp = 68/80 = 0.85
    # norm_brix = 2/20  = 0.10
    # norm_salt = 8.5/10 = 0.85,  pl(0.85, 1.4)
    # norm_glu  = 16/20  = 0.80,  pl(0.80, 1.0) = 0.80
    # Interactions: salt>0.30 -> bitterness*=0.80 (bitterness=0, no effect)
    #               temp>0.70 -> spiciness*=1.10  (spiciness=0, no effect)
    # -----------------------------------------------------------------------
    "Miso Soup": {
        "raw": dict(raw_ph=4.9, raw_temp=68, raw_brix=2.0,
                    raw_spicy=0, raw_co2=0, raw_ibu=0, raw_salt=8.5, raw_umami=16.0),
        "intensities": {
            "Sourness":    round(pl(0.04, 1.1), 4),    # ~0.0290
            "Sweetness":   round(pl(0.10, 1.3), 4),    # ~0.0501
            "Spiciness":   0.0,
            "Saltiness":   round(pl(0.85, 1.4), 4),    # ~0.7962
            "Umami":       0.80,
            "Carbonation": 0.0,
            "Bitterness":  0.0,
            "Temperature": 0.85,
        },
        "axes": {
            # energy = 0*0.40 + 0.0290*0.25 + 0*0.20 + 0.85*0.10 + 0.7962*0.05 = 0.132
            "energy":   round(clamp(pl(0.04,1.1)*0.25 + 0.85*0.10 + pl(0.85,1.4)*0.05), 3),
            # warmth = 0.0501*0.40 + 0.80*0.30 + 0.85*0.20 = 0.430
            "warmth":   round(clamp(pl(0.10,1.3)*0.40 + 0.80*0.30 + 0.85*0.20), 3),
            # darkness = 0*0.45 + 0.0290*0.25 + (1-0.0501)*0.20 + (1-0.85)*0.10 = 0.212
            "darkness": round(clamp(pl(0.04,1.1)*0.25 + (1-pl(0.10,1.3))*0.20 + (1-0.85)*0.10), 3),
            # texture = 0*0.50 + 0.7962*0.30 + 0*0.20 = 0.239
            "texture":  round(clamp(pl(0.85,1.4)*0.30), 3),
            # richness = 0.80*0.45 + 0.0501*0.30 + 0.7962*0.25 = 0.574
            "richness": round(clamp(0.80*0.45 + pl(0.10,1.3)*0.30 + pl(0.85,1.4)*0.25), 3),
            "temp_feel": 0.85,
        },
        "genre":    "Ambient Electronic",
        "bpm":      62,
        "key":      "natural major",
        "n_channels": 4,
    },

    # -----------------------------------------------------------------------
    # 3. Extreme Hot Sauce
    # norm_ph    = (3.2-2.5)/2.5 = 0.28 -> sourness_in = 0.72
    # norm_spicy = 45000/50000 = 0.90,  pl(0.90, 0.8)
    # norm_salt  = 2.0/10 = 0.20,       pl(0.20, 1.4)
    # norm_temp  = 28/80  = 0.35
    # NO interactions trigger (salt<0.30, sweet<0.50, temp<0.70)
    # -----------------------------------------------------------------------
    "Extreme Hot Sauce": {
        "raw": dict(raw_ph=3.2, raw_temp=28, raw_brix=2.0,
                    raw_spicy=45000, raw_co2=0, raw_ibu=0, raw_salt=2.0, raw_umami=0),
        "intensities": {
            "Sourness":    round(pl(0.72, 1.1), 4),   # ~0.6967
            "Sweetness":   round(pl(0.10, 1.3), 4),   # ~0.0501
            "Spiciness":   round(pl(0.90, 0.8), 4),   # ~0.9192
            "Saltiness":   round(pl(0.20, 1.4), 4),   # ~0.1048
            "Umami":       0.0,
            "Carbonation": 0.0,
            "Bitterness":  0.0,
            "Temperature": 0.35,
        },
        "axes": {
            # energy = 0.9192*0.40 + 0.6967*0.25 + 0*0.20 + 0.35*0.10 + 0.1048*0.05 = 0.582
            "energy":   round(clamp(pl(0.90,0.8)*0.40 + pl(0.72,1.1)*0.25 + 0.35*0.10 + pl(0.20,1.4)*0.05), 3),
            # warmth = 0.0501*0.40 + 0*0.30 + 0.35*0.20 = 0.090
            "warmth":   round(clamp(pl(0.10,1.3)*0.40 + 0.35*0.20), 3),
            # darkness = 0*0.45 + 0.6967*0.25 + (1-0.0501)*0.20 + (1-0.35)*0.10 = 0.429
            "darkness": round(clamp(pl(0.72,1.1)*0.25 + (1-pl(0.10,1.3))*0.20 + (1-0.35)*0.10), 3),
            # texture = 0*0.50 + 0.1048*0.30 + 0.9192*0.20 = 0.215
            "texture":  round(clamp(pl(0.20,1.4)*0.30 + pl(0.90,0.8)*0.20), 3),
            # richness = 0*0.45 + 0.0501*0.30 + 0.1048*0.25 = 0.041
            "richness": round(clamp(pl(0.10,1.3)*0.30 + pl(0.20,1.4)*0.25), 3),
            "temp_feel": 0.35,
        },
        "genre":    "Minimal Techno",
        "bpm":      124,
        "key":      "Dorian",
        "n_channels": 3,
    },
}


# ---------------------------------------------------------------------------
# Run actual engine and compare
# ---------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
TOL = 1e-3   # tolerance for float comparisons (rounding to 4dp)

def _check(label, expected, actual, tol=TOL):
    if isinstance(expected, str):
        ok = expected == actual
    elif isinstance(expected, float):
        ok = abs(expected - actual) <= tol
    else:
        ok = expected == actual
    status = PASS if ok else FAIL
    return status, f"{status}  {label}: expected={expected!r}  got={actual!r}"


def run():
    mapper = TasteMapper()
    all_pass = True
    lines = []

    for food, spec in EXPECTED.items():
        lines.append("")
        lines.append("=" * 72)
        lines.append(f"  {food}")
        lines.append("=" * 72)

        mapper.reset_ema()
        actual_int = mapper.process_data(**spec["raw"])
        bundle = generate_bundle(actual_int)
        axes   = bundle.axes

        # -- Intensities --
        lines.append("\n  [Taste Intensities]")
        for dim, exp_val in spec["intensities"].items():
            act_val = round(actual_int.get(dim, 0.0), 4)
            st, msg = _check(dim, exp_val, act_val)
            if st == FAIL: all_pass = False
            lines.append(f"    {msg}")

        # -- Axes --
        lines.append("\n  [Flavor Axes]")
        ax_map = {
            "energy":   axes.energy,
            "warmth":   axes.warmth,
            "darkness": axes.darkness,
            "texture":  axes.texture,
            "richness": axes.richness,
            "temp_feel": axes.temp_feel,
        }
        for ax, exp_val in spec["axes"].items():
            act_val = round(ax_map[ax], 3)
            st, msg = _check(ax, exp_val, act_val)
            if st == FAIL: all_pass = False
            lines.append(f"    {msg}")

        # -- High-level decisions --
        lines.append("\n  [Music Decisions]")
        checks = [
            ("Genre",    spec["genre"],     bundle.genre_name),
            ("BPM",      spec["bpm"],       bundle.bpm),
            ("Key",      spec["key"],       bundle.key_mood),
            ("Channels", spec["n_channels"],len(bundle.channels)),
        ]
        for lbl, exp, act in checks:
            st, msg = _check(lbl, exp, act)
            if st == FAIL: all_pass = False
            lines.append(f"    {msg}")

        # -- Per-channel prompts (printed for inspection, not compared) --
        lines.append("\n  [Generated Prompts]")
        for ch in bundle.channels:
            lines.append(f"\n    >> {ch.label}")
            wrapped = ch.prompt
            while len(wrapped) > 68:
                cut = wrapped[:68].rfind(" ")
                cut = cut if cut > 10 else 68
                lines.append(f"       {wrapped[:cut]}")
                wrapped = wrapped[cut:].lstrip()
            lines.append(f"       {wrapped}")

        lines.append("\n  [Master Prompt]")
        for raw_line in bundle.master_prompt.splitlines():
            if not raw_line.strip():
                lines.append("")
                continue
            remaining = raw_line
            while len(remaining) > 68:
                cut = remaining[:68].rfind(" ")
                cut = cut if cut > 10 else 68
                lines.append(f"    {remaining[:cut]}")
                remaining = remaining[cut:].lstrip()
            lines.append(f"    {remaining}")

    lines.append("")
    lines.append("=" * 72)
    result = "ALL TESTS PASSED" if all_pass else "SOME TESTS FAILED"
    lines.append(f"  {result}")
    lines.append("=" * 72)

    for line in lines:
        print(line)

    return all_pass


if __name__ == "__main__":
    run()
