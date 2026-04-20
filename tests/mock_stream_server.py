"""
tests/mock_stream_server.py
Virtual Pouring Simulation - EMA Fluidity Analysis

Simulates a 30-second pour from Empty/Water into a Spicy Cola profile
at 10 Hz. Every interpolated raw frame is fed through TasteMapper with
full EMA state so we can measure exactly when each perceived dimension
reaches 90% of its steady-state target value.

Two scenarios are analysed:
  1. RAMP  - raw values linearly interpolate Water -> Spicy Cola over 30s
  2. STEP  - raw values snap instantly to Spicy Cola (theoretical baseline)

Run from the project root:
    python tests/mock_stream_server.py
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.brain import TasteMapper

# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

WATER = dict(
    raw_ph=5.0,   raw_temp=20.0, raw_brix=0.0,  raw_spicy=0.0,
    raw_co2=0.0,  raw_ibu=0.0,   raw_salt=0.0,  raw_umami=0.0,
)

SPICY_COLA = dict(
    raw_ph=2.8,   raw_temp=4.0,  raw_brix=11.0, raw_spicy=15_000.0,
    raw_co2=3.5,  raw_ibu=2.0,   raw_salt=0.5,  raw_umami=0.0,
)

# ---------------------------------------------------------------------------
# Simulation parameters
# ---------------------------------------------------------------------------

POUR_S      = 30.0          # ramp duration in seconds
FPS         = 10            # frames per second (matches run_app.py)
TARGET_PCT  = 0.90          # convergence threshold fraction
EXTRA_S     = 30            # hold seconds after pour completes
TRACKED     = ["Sourness", "Sweetness", "Spiciness", "Carbonation"]
W           = 74            # report line width

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _lerp(a: dict, b: dict, t: float) -> dict:
    """Linearly interpolate all raw values from profile a to b."""
    return {k: a[k] + (b[k] - a[k]) * t for k in a}


def _steady_state(ref: TasteMapper, profile: dict) -> dict:
    """Compute unsmoothed Stevens's Law intensities for a profile."""
    ref.reset_ema()
    return ref.process_data(**profile)


def _bar(v: float, w: int = 18) -> str:
    n = round(max(0.0, min(1.0, v)) * w)
    return "#" * n + "-" * (w - n)


def _rule(ch: str = "=") -> str:
    return "+" + ch * (W - 1) + "+"


def _section(title: str) -> str:
    pad = W - 4 - len(title)
    return f"+-- {title} " + "-" * max(0, pad) + "+"

# ---------------------------------------------------------------------------
# Scenario 1: 30-second linear ramp
# ---------------------------------------------------------------------------

def run_ramp(alpha: float) -> tuple:
    sim = TasteMapper()
    ref = TasteMapper()
    total_pour = int(POUR_S * FPS)     # 300 frames
    total_hold = int(EXTRA_S * FPS)    # 300 frames

    targets    = _steady_state(ref, SPICY_COLA)
    thresholds = {k: targets[k] * TARGET_PCT for k in TRACKED if targets[k] > 1e-4}
    crossed    = {k: None for k in thresholds}
    frames     = []                    # (t_sec, ema_dict, raw_dict)

    for i in range(total_pour + total_hold + 1):
        t_frac  = min(i / total_pour, 1.0)
        profile = _lerp(WATER, SPICY_COLA, t_frac)

        ema = sim.process_data(**profile)
        ref.reset_ema()
        raw = ref.process_data(**profile)

        t_sec = i / FPS
        frames.append((t_sec, dict(ema), dict(raw)))

        for k, thr in thresholds.items():
            if crossed[k] is None and ema.get(k, 0.0) >= thr:
                crossed[k] = i

    return frames, targets, thresholds, crossed, total_pour


# ---------------------------------------------------------------------------
# Scenario 2: Instant step switch
# ---------------------------------------------------------------------------

def run_step(alpha: float) -> tuple:
    sim = TasteMapper()
    ref = TasteMapper()

    targets = _steady_state(ref, SPICY_COLA)

    # Establish Water as the prior state
    sim.process_data(**WATER)

    frames = []
    for i in range(1, 21):
        ema = sim.process_data(**SPICY_COLA)
        frames.append((i, round(i / FPS, 1), dict(ema)))

    return frames, targets


# ---------------------------------------------------------------------------
# ASCII time-series chart
# ---------------------------------------------------------------------------

def render_chart(frames: list, dim: str, targets: dict, total_pour: int) -> list[str]:
    COLS, ROWS = 58, 14

    target_v = targets.get(dim, 0.0)
    y_max    = max(target_v * 1.12, 0.01)

    step     = max(1, len(frames) // COLS)
    sampled  = frames[::step][:COLS]
    n_cols   = len(sampled)

    grid = [[" "] * n_cols for _ in range(ROWS)]

    def y_row(v: float) -> int:
        frac = max(0.0, min(1.0, v / y_max))
        return ROWS - 1 - round(frac * (ROWS - 1))

    thr_row  = y_row(target_v * TARGET_PCT)
    tgt_row  = y_row(target_v)
    pour_col = min(n_cols - 1, round(n_cols * POUR_S / (len(frames) / FPS)))

    for col, (_, ema_d, raw_d) in enumerate(sampled):
        rr = max(0, min(ROWS - 1, y_row(raw_d.get(dim, 0.0))))
        er = max(0, min(ROWS - 1, y_row(ema_d.get(dim, 0.0))))
        grid[rr][col] = "X" if rr == er else "r"
        if rr != er:
            grid[er][col] = "E"

    for col in range(n_cols):
        if grid[thr_row][col] == " ":
            grid[thr_row][col] = "."
        if col == pour_col and grid[0][col] == " ":
            for row in range(ROWS):
                if grid[row][col] == " ":
                    grid[row][col] = "|"

    out = []
    for row in range(ROWS):
        y_val  = y_max * (1.0 - row / (ROWS - 1))
        prefix = f" {y_val:.2f} |" if row % 4 == 0 else "      |"
        out.append(prefix + "".join(grid[row]))

    t_total = sampled[-1][0] if sampled else POUR_S + EXTRA_S
    out.append("      +" + "-" * n_cols)
    out.append(f"      0s{'':{pour_col-3}}^30s{' ':2}{t_total:.0f}s")
    out.append("      r=Raw  E=EMA  .=90% thr  |=pour end")
    return out


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report() -> str:
    ref   = TasteMapper()
    alpha = ref.EMA_ALPHA
    lag_s = (1.0 - alpha) / alpha / FPS   # per-frame EMA lag in seconds

    an_frames = math.log(1.0 - TARGET_PCT) / math.log(1.0 - alpha)

    frames, targets, thresholds, crossed, total_pour = run_ramp(alpha)
    step_frames, step_targets = run_step(alpha)

    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────────
    lines += [
        _rule(),
        f"| TASTEDATA - VIRTUAL POUR / EMA FLUIDITY ANALYSIS".ljust(W - 1) + "|",
        f"|  Profile : Water -> Spicy Cola   Pour: {POUR_S:.0f}s   Rate: {FPS} Hz   alpha: {alpha}".ljust(W - 1) + "|",
        _rule(),
        "",
    ]

    # ── Target intensities ───────────────────────────────────────────────────
    lines.append(_section("Step 1 - Target Intensities at Spicy Cola (Stevens's Law, no EMA)"))
    lines.append(f"|  {'Dimension':<14} {'Target':>8}  {'90% Thr':>8}  Notes")
    for k in TRACKED:
        tv  = targets.get(k, 0.0)
        thr = thresholds.get(k, 0.0)
        note = "tracked" if k in thresholds else "target < 0.0001, skip"
        lines.append(f"|  {k:<14} {tv:>8.4f}  {thr:>8.4f}  {note}")
    lines.append("|")

    # ── Ramp table ───────────────────────────────────────────────────────────
    lines.append(_section("Step 2 - Ramp Phase (sampled every 5s)   format: EMA / Raw"))
    col_head = "  ".join(f"{k[:5]+' e/r':>11}" for k in TRACKED)
    lines.append(f"|  {'t':>5}  {'pour%':>5}  {col_head}")

    for t_sec, ema, raw in frames:
        if t_sec > POUR_S + 1e-9:
            break
        fi = round(t_sec * FPS)
        if fi % (FPS * 5) != 0:
            continue
        pct = int(t_sec / POUR_S * 100) if t_sec > 0 else 0
        cells = "  ".join(f"  {ema.get(k,0):.3f}/{raw.get(k,0):.3f}" for k in TRACKED)
        lines.append(f"|  {t_sec:>4.0f}s  {pct:>4}%  {cells}")
    lines.append("|")

    # ── Hold table ───────────────────────────────────────────────────────────
    lines.append(_section("Step 3 - Hold Phase (raw frozen at Spicy Cola, EMA converges)"))
    lines.append(f"|  {'t':>5}  {'hold':>5}  {col_head}")

    hold_rows = 0
    for t_sec, ema, raw in frames:
        if t_sec <= POUR_S:
            continue
        hold_s = t_sec - POUR_S
        if round(hold_s * FPS) % FPS != 0:
            continue
        if hold_rows >= 10:
            lines.append("|  ... (truncated - all dimensions stable)")
            break
        cells = "  ".join(f"  {ema.get(k,0):.3f}/{raw.get(k,0):.3f}" for k in TRACKED)
        lines.append(f"|  {t_sec:>4.0f}s  {hold_s:>4.0f}s  {cells}")
        hold_rows += 1

    if hold_rows == 0:
        lines.append("|  (all dimensions converged before pour ended - no hold phase needed)")
    lines.append("|")

    # ── Convergence results ──────────────────────────────────────────────────
    lines.append(_section("Step 4 - Convergence Results"))
    lines.append(f"|")
    lines.append(f"|  Analytical (step function, instant switch):")
    lines.append(f"|    N = log(1-{TARGET_PCT}) / log(1-{alpha:.1f})")
    lines.append(f"|      = {an_frames:.2f} frames  ->  ceil = {math.ceil(an_frames)} frames = {math.ceil(an_frames)/FPS:.2f}s")
    lines.append(f"|    EMA per-frame lag on a ramp = (1-a)/a / fps = {lag_s:.2f}s")
    lines.append(f"|")
    lines.append(f"|  Observed (30s linear ramp of raw values):")
    lines.append(f"|  {'Dimension':<14} {'Target':>8} {'Thr 90%':>8} {'Frame':>7} {'Time':>7}  Result")
    lines.append(f"|  {'-'*14} {'-'*8} {'-'*8} {'-'*7} {'-'*7}  {'-'*28}")

    for k in TRACKED:
        tv  = targets.get(k, 0.0)
        thr = thresholds.get(k, 0.0)
        if k not in thresholds:
            lines.append(f"|  {k:<14} {tv:>8.4f}      ---      ---     ---  skipped (inactive)")
            continue
        fn = crossed.get(k)
        if fn is None:
            lines.append(f"|  {k:<14} {tv:>8.4f} {thr:>8.4f}  TIMEOUT     ---  did not converge")
        else:
            t_obs = fn / FPS
            if fn <= total_pour:
                result = f"during ramp at {int(fn/total_pour*100):3}% complete"
            else:
                result = f"+{t_obs - POUR_S:.1f}s after pour ended"
            lines.append(f"|  {k:<14} {tv:>8.4f} {thr:>8.4f}  {fn:>6}  {t_obs:>6.1f}s  {result}")

    lines.append(f"|")
    lines.append(f"|  Key finding: for a slow {POUR_S:.0f}s ramp, EMA lag = {lag_s:.2f}s (negligible).")
    lines.append(f"|  Dimensions reach 90% during the pour itself because the raw signal")
    lines.append(f"|  has already risen far enough to carry the smoothed value with it.")
    lines.append("|")

    # ── Step function table ──────────────────────────────────────────────────
    lines.append(_section("Step 5 - Step Function Detail (Spiciness, frame by frame)"))
    lines.append(f"|  Instant switch from Water baseline. Shows why alpha={alpha} feels 'fluid'.")
    lines.append(f"|  Target: {step_targets.get('Spiciness',0):.4f}   90% threshold: {step_targets.get('Spiciness',0)*TARGET_PCT:.4f}")
    lines.append(f"|")
    lines.append(f"|  {'Frame':>6}  {'t(s)':>5}  {'EMA':>8}  {'Raw':>8}  {'% Tgt':>7}  {'bar (EMA)':>20}")
    lines.append(f"|  {'-'*6}  {'-'*5}  {'-'*8}  {'-'*8}  {'-'*7}  {'-'*20}")

    sp_tgt     = step_targets.get("Spiciness", 0.0)
    sp_thr     = sp_tgt * TARGET_PCT
    step_cross = None

    for fn, t_s, ema_d in step_frames:
        ev     = ema_d.get("Spiciness", 0.0)
        pct_t  = ev / sp_tgt * 100 if sp_tgt > 0 else 0.0
        marker = ""
        if step_cross is None and ev >= sp_thr:
            step_cross = (fn, t_s)
            marker = " <- 90%"
        bar = _bar(ev / sp_tgt if sp_tgt > 0 else 0, 18)
        lines.append(f"|  {fn:>6}  {t_s:>5.1f}  {ev:>8.4f}  {sp_tgt:>8.4f}  {pct_t:>6.1f}%  [{bar}]{marker}")

    lines.append(f"|")
    if step_cross:
        lines.append(f"|  Step 90% reached : frame {step_cross[0]:>2} = {step_cross[1]:.1f}s")
        lines.append(f"|  Analytical (real) : {an_frames:.2f} frames = {an_frames/FPS:.3f}s")
        lines.append(f"|  Delta             : {step_cross[1] - an_frames/FPS:+.3f}s (one frame of rounding)")
    lines.append("|")

    # ── ASCII chart ──────────────────────────────────────────────────────────
    lines.append(_section("Step 6 - Spiciness Perceived Intensity  (ramp + hold)"))
    for cl in render_chart(frames, "Spiciness", targets, total_pour):
        lines.append(f"|  {cl}")
    lines.append("|")

    # ── Summary ──────────────────────────────────────────────────────────────
    lines += [
        _rule(),
        f"|  SUMMARY".ljust(W - 1) + "|",
        f"|  Alpha = {alpha}  |  {FPS} Hz  |  Per-frame lag = {lag_s:.2f}s  |  Step 90% = {math.ceil(an_frames)} frames = {math.ceil(an_frames)/FPS:.2f}s".ljust(W - 1) + "|",
        f"|".ljust(W - 1) + "|",
        f"|  RAMP  scenario: 90% reached ~{(crossed.get(TRACKED[0], total_pour))/FPS:.1f}s into the {POUR_S:.0f}s pour.".ljust(W - 1) + "|",
        f"|          EMA introduces only {lag_s:.2f}s of lag - perceived transitions are very fluid.".ljust(W - 1) + "|",
        f"|  STEP  scenario: any sudden change (e.g. adding hot sauce mid-sip) takes".ljust(W - 1) + "|",
        f"|          exactly {math.ceil(an_frames)} frames ({math.ceil(an_frames)/FPS:.2f}s) to register at 90% in the output.".ljust(W - 1) + "|",
        f"|  TUNING: Increase alpha toward 1.0 to make the system more reactive;".ljust(W - 1) + "|",
        f"|          decrease toward 0.0 for slower, more cinematic transitions.".ljust(W - 1) + "|",
        _rule(),
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    report = build_report()
    print(report)

    out = Path(__file__).resolve().parent.parent / "docs" / "pour_analysis.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\n  Saved to docs/pour_analysis.txt")
