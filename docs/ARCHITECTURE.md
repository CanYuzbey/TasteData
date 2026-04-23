# TasteData — Architecture Overview
Version 2.0 · 2026-04-23

This document is the canonical technical reference for the TasteData pipeline. A reader who has never seen the code should understand the full system from this file alone.

---

## 1. Purpose

TasteData is a synesthetic mapping system. It reads chemical and physical properties of food/drink from sensors (or simulation), converts raw measurements into **Perceived Intensities** using Stevens's Power Law, and emits the results as:

- **OSC messages** to TouchDesigner for real-time visual generation
- **Suno-formatted PromptBundle** (per-channel + master prompt) for AI music generation
- **CSV logs** for post-session analysis
- **JSON snapshots** for archiving notable taste frames on demand

---

## 2. File Structure

```
tasteData/
|
+-- config/
|   +-- settings.yaml         All tunable scientific constants (ranges, exponents,
|                             smoothing, interaction thresholds)
|
+-- docs/
|   +-- ARCHITECTURE.md       This file — canonical pipeline reference
|   +-- logic_manifesto.md    Research source: all exponents, interaction rules,
|                             FlavorAxes formulas, prompt engine design
|   +-- validation_report.txt Output of tests/run_battery.py (regenerated on each run)
|   +-- pour_analysis.txt     Output of tests/mock_stream_server.py — EMA fluidity study
|   +-- synthetic_test_report.txt
|                             Output of tests/synthetic_test.py — 21 analytical tests
|
+-- logs/
|   +-- session_history.csv   Append-only CSV of every processed taste frame
|   +-- archive/              Old session files
|
+-- snapshots/                Per-label JSON snapshots (created on demand during runtime)
|
+-- src/
|   +-- brain.py              TasteMapper class — core scientific engine
|   +-- prompt_engine.py      Multi-Channel Suno Prompt Engine — standalone module
|   +-- sensors.py            SensorReader class — serial / simulation data source
|   +-- bridge.py             OSC client — sends computed values to TouchDesigner
|   +-- logger.py             SessionLogger class — CSV append writer
|   +-- analyzer.py           Snapshot Library Analyzer
|
+-- tests/
|   +-- run_battery.py        Validation battery: 8 standard food profiles
|   +-- synthetic_test.py     Synthetic test suite: 21 analytically verified cases
|   +-- demo_comparison.py    3-profile integration test (brain + prompt_engine)
|   +-- mock_stream_server.py EMA fluidity simulation (virtual 30s pour)
|
+-- firmware/
|   +-- TasteData_Sensor_Node.ino  Arduino firmware (CSV @ 9600 baud, 10 Hz)
|
+-- requirements.txt          python-osc, pyserial, pyyaml
+-- run_app.py                Main entry point — orchestrates all modules
```

---

## 3. Data Flow

```
[Arduino / Simulation]
        |
        | CSV line: "ph,temp,brix,shu,co2,ibu,salt,glutamate" @ 9600 baud
        v
src/sensors.py  (SensorReader)
  - Parses serial line into {"ph", "temp", "brix", "spicy", "co2", "ibu", "salt", "umami"}
  - On disconnect or missing hardware: falls back to random-walk simulation
        |
        | raw frame dict (8 keys)
        v
src/brain.py  (TasteMapper.process_data)
  Step 1: Normalize each raw value to [0, 1] using YAML min/max bounds
  Step 2: Apply Stevens's Power Law   ->  Perception = normalized ^ exponent
  Step 3: Sourness special case       ->  sourness_input = 1.0 - normalized_pH
  Step 4: Perceptual Interaction Rules (post Power Law, pre EMA)
  Step 5: Apply EMA smoothing         ->  smoothed = 0.2*new + 0.8*prev
        |
        | intensities dict  (8 keys, all 0.0–1.0, EMA-smoothed)
        |
        +-----> TasteMapper.get_visual_params
        |         - Weighted-average RGB  (Pink=Sweet, Yellow=Sour, Red=Spicy)
        |         - Weighted-average angularity  (0=round, 1=pointy)
        |         - Noise = Spiciness*0.7 + Carbonation*0.3
        |                 |
        |                 +-----> src/bridge.py  (send_osc_data)
        |                         UDP to 127.0.0.1:7000
        |                         /td/color/r|g|b  (float)
        |                         /td/angularity   (float 0–1)
        |                         /td/noise        (float 0–1)
        |
        +-----> src/prompt_engine.py  (generate_bundle)
                  Stage 1: compute_axes    (8 dims -> 5 FlavorAxes + temp_feel)
                  Stage 2: select_genre    (MSE score against 12 genre profiles)
                  Stage 3: channel_count   (3–max, scaled by energy + richness)
                  Stage 4: render_channel  (all 8 dims -> timbre, articulation, FX)
                          |
                          v  PromptBundle
                            .channels[]    (per-channel Suno prompts)
                            .master_prompt (combined master prompt)
                          |
                          +-----> src/bridge.py  (/td/audio_prompt via OSC DAT)
                          +-----> src/logger.py  (logged to CSV as audio_prompt column)

[On demand — via CLI 'S' key]
TasteMapper.save_flavor_snapshot(label, raw_data, intensities, audio_prompt)
  -> uses last frame's already-computed intensities and bundle.master_prompt
  -> writes snapshots/{label}.json  (no second EMA call)
```

---

## 4. Scientific Logic

### 4.1 Normalization Bounds (config/settings.yaml)

| Dimension   | Raw Unit        | Min   | Max    | Notes                              |
|-------------|-----------------|-------|--------|------------------------------------|
| pH          | pH scale        | 2.5   | 5.0    | Sourness = 1.0 − normalized_pH     |
| Temperature | degrees C       | 0.0   | 80.0   | Linear passthrough, no exponent    |
| Sweetness   | degrees Brix    | 0.0   | 20.0   |                                    |
| Spiciness   | SHU             | 0.0   | 50,000 |                                    |
| Carbonation | volumes CO₂     | 0.0   | 5.0    | Stevens exponent 1.1 applied       |
| Bitterness  | IBU             | 0.0   | 100.0  |                                    |
| Saltiness   | g/L NaCl        | 0.0   | 10.0   |                                    |
| Umami       | glutamate units | 0.0   | 20.0   |                                    |

Values outside the calibrated range are silently clamped to [0, 1] before exponent application.

### 4.2 Stevens's Power Law Exponents (config/settings.yaml → exponents)

Formula: `Perception = clamp(normalized, 0, 1) ^ exponent`

| Dimension   | Exponent | Curve type   | Perceptual Effect                                                   |
|-------------|----------|--------------|---------------------------------------------------------------------|
| Sweetness   | 1.3      | Compressive  | Sweetness builds slowly; sugar perception saturates late            |
| Sourness    | 1.1      | Compressive  | Near-linear; acid detection is relatively proportional              |
| Spiciness   | 0.8      | Expansive    | Capsaicin pain signals strongly at low concentrations               |
| Bitterness  | 1.3      | Compressive  | Matches sweetness; bitter is a slow-building warning signal         |
| Saltiness   | 1.4      | Compressive  | Most compressive — NaCl perception saturates latest of all          |
| Umami       | 1.0      | Linear       | Glutamate detection passes through unchanged                        |
| Carbonation | 1.1      | Compressive  | More CO₂ required per unit perception than linear; builds gradually |

Temperature uses `clamp(norm_temp)` — linear passthrough, no exponent — because its role
is sensory context rather than a discrete chemical taste signal.

Safety guards in `_apply_power_law()`:
- `value == 0.0` → returns 0.0 (avoids 0^0 = 1 ambiguity)
- `exponent <= 0.0` → returns 1.0 (protects against invalid YAML config)

### 4.3 Perceptual Interaction Rules (config/settings.yaml → interactions)

Applied **after** Stevens's Power Law, **before** EMA smoothing, in-place on the intensities dict:

| Rule | Condition | Effect | Scientific basis |
|------|-----------|--------|-----------------|
| Salt suppresses Bitter | `Saltiness > 0.30` | `Bitterness × 0.80` | NaCl competes at amiloride-sensitive channels (McBurney, 1969) |
| Sweet suppresses Sour | `Sweetness > 0.50` | `Sourness × 0.85` | Sugar elevates acid perception threshold (Breslin & Beauchamp, 1997) |
| Heat potentiates Spicy | `Temperature > 0.70` | `Spiciness × 1.10` (clamped ≤ 1.0) | Elevated temp sensitises TRPV1 capsaicin receptors (Caterina et al., 1997) |

### 4.4 EMA Smoothing (config/settings.yaml → smoothing.alpha = 0.2)

```
smoothed[t] = 0.2 * raw[t]  +  0.8 * smoothed[t-1]
```

- **Per-frame lag on ramp:** `(1−α)/α/fps = 0.40 s`
- **Step-function 90% convergence:** `ceil(log(0.1)/log(0.8)) = 11 frames = 1.10 s`

First-frame boundary: when no prior state exists, `smoothed[t-1]` defaults to `raw[t]`, so the
first reading passes through with no phantom decay toward zero. `reset_ema()` clears the
state dict for isolated analytical runs.

---

## 5. Multi-Channel Prompt Engine (src/prompt_engine.py)

`generate_bundle(intensities)` is the primary audio output path in the live pipeline.
It replaces the legacy `TasteMapper.generate_audio_prompt()` threshold-gated single string.

### Stage 1 — FlavorAxes

Eight perceived intensities are compressed into five aesthetic axes:

| Axis | Formula |
|------|---------|
| `energy`   | `Spiciness×0.40 + Sourness×0.25 + Carbonation×0.20 + Temperature×0.10 + Saltiness×0.05` |
| `warmth`   | `Sweetness×0.40 + Umami×0.30 + Temperature×0.20 − Bitterness×0.10` |
| `darkness` | `Bitterness×0.45 + Sourness×0.25 + (1−Sweetness)×0.20 + (1−Temperature)×0.10` |
| `texture`  | `Carbonation×0.50 + Saltiness×0.30 + Spiciness×0.20` |
| `richness` | `Umami×0.45 + Sweetness×0.30 + Saltiness×0.25` |

`temp_feel` is preserved as a raw value alongside the axes.

### Stage 2 — Genre Selection

Twelve genre profiles are scored by weighted MSE against the current axes. Energy and
darkness carry the highest weights (0.28, 0.24); temp_feel the lowest (0.05). The minimum
MSE genre determines BPM range, key/mode tendency, channel role roster, and mix aesthetic.

### Stage 3 — Channel Roster

Active channel count = `max(3, round(roster_size × (0.55 + density×0.45)))` where
`density = richness×0.60 + energy×0.40`. Foundation channels (kick, bass) always render;
atmosphere channels are first to drop for sparse profiles.

### Stage 4 — Per-Channel Rendering (three passes, all 8 dims contribute to each)

1. **Timbral adjectives** — continuous ranges, no threshold gating. Every dimension contributes
   a descriptive word even at low intensities. Temperature is handled in five bands:
   `te > 0.80` → "hot and saturated"; `te > 0.60` → "warm and slightly hazy";
   `te > 0.40` → "room-temperature"; `te > 0.20` → "cool and crisp";
   `te ≤ 0.20` → "cold and sterile — icy precision".

2. **Articulation** — role-aware playing style. Rhythmic roles (kick, perc) get transient/decay
   language; sustained roles (pad, drone, atmo) get attack/bloom/release language.
   Temperature shapes both: cold → tight decay, crystalline sustain; hot → extended decay,
   dense sustained body.

3. **FX chain** — Temperature is the primary reverb driver (weight 0.50 in reverb formula,
   vs Sweetness 0.25, Umami 0.15). `te > 0.75` → dense plate reverb + wide M-S stereo;
   `te < 0.20` → almost dry, narrow mono. Spiciness → distortion/bitcrusher; Sourness →
   rhythmic delay + HPF; Bitterness → LPF sweep; Saltiness → chorus/ensemble detune;
   Carbonation → granular synthesis (grain pitch 2–20 kHz proportional to CO₂ intensity).

### Output: PromptBundle

```python
@dataclass
class PromptBundle:
    genre_name:    str
    bpm:           int
    key_mood:      str
    axes:          FlavorAxes
    channels:      list[RenderedChannel]   # per-channel Suno prompts
    master_prompt: str                     # combined master prompt
```

---

## 6. Snapshot Schema

File: `snapshots/{label}.json`

```json
{
  "label":     "string — name provided at save time",
  "timestamp": "ISO 8601, second precision",
  "raw_data": {
    "raw_ph": 0.0, "raw_temp": 0.0, "raw_brix": 0.0, "raw_spicy": 0.0,
    "raw_co2": 0.0, "raw_ibu": 0.0, "raw_salt": 0.0, "raw_umami": 0.0
  },
  "intensities": {
    "Sourness": 0.0, "Sweetness": 0.0, "Spiciness": 0.0, "Saltiness": 0.0,
    "Umami": 0.0, "Carbonation": 0.0, "Bitterness": 0.0, "Temperature": 0.0
  },
  "audio_prompt": "string — PromptBundle.master_prompt at time of capture"
}
```

All intensity values are EMA-smoothed and rounded to 6 decimal places. Snapshots are
saved using the already-computed intensities from the most recent frame to avoid a
second `process_data()` call that would re-apply EMA.

---

## 7. CSV Log Schema

File: `logs/session_history.csv`

Columns (in order):
```
timestamp, raw_ph, raw_temp, raw_brix, raw_spicy, raw_co2, raw_ibu, raw_salt, raw_umami,
Sourness, Sweetness, Spiciness, Saltiness, Umami, Carbonation, Bitterness, Temperature,
audio_prompt
```

One row per processed frame. `audio_prompt` column contains `PromptBundle.master_prompt`.
Opened in append mode; header written once on first creation; each row is flushed
immediately so no data is lost on crash.

---

## 8. OSC Output Map

OSC In CHOP: Network Port 7000, Local Address 127.0.0.1 (numeric channels)
OSC In DAT:  Network Port 7000 (string channel — audio_prompt)

| OSC Address | Type | Range | Description |
|-------------|------|-------|-------------|
| `/td/color/r` | float | 0–255 | Red channel of weighted taste colour |
| `/td/color/g` | float | 0–255 | Green channel |
| `/td/color/b` | float | 0–255 | Blue channel |
| `/td/angularity` | float | 0.0–1.0 | Shape: 0 = circular (sweet), 1 = jagged (spicy) |
| `/td/noise` | float | 0.0–1.0 | Visual grain: `Spiciness×0.7 + Carbonation×0.3` |
| `/td/audio_prompt` | string | — | `PromptBundle.master_prompt` (read via OSC In DAT) |

---

## 9. Running the System

```bash
# Install dependencies
pip install -r requirements.txt

# Validation battery (8 food profiles, regenerates docs/validation_report.txt)
python tests/run_battery.py

# Synthetic test suite (21 analytically verified cases, exit code 1 on failure)
python tests/synthetic_test.py

# Integration test (3 profiles through brain + prompt_engine)
python tests/demo_comparison.py

# Prompt engine demo (5 food profiles with full PromptBundle output)
python src/prompt_engine.py

# EMA fluidity analysis (regenerates docs/pour_analysis.txt)
python tests/mock_stream_server.py

# Main application — hardware mode
python run_app.py COM3            # Windows
python run_app.py /dev/ttyUSB0   # Linux / macOS

# Main application — simulation mode (auto-fallback when no hardware)
python run_app.py

# Interactive commands while running:
#   S + Enter  ->  save a labeled snapshot to snapshots/{label}.json
#   Q + Enter  ->  graceful shutdown
#   Ctrl+C     ->  immediate shutdown

# Snapshot library analysis
python src/analyzer.py
```

---

## 10. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Config in YAML, not hardcoded | Scientific constants change during tuning; YAML avoids source redeploys |
| EMA in brain.py, not sensors.py | Smoothing is a perceptual model choice, not a hardware concern |
| Interactions after Power Law, before EMA | Preserves the chemosensory reality of the current frame in the smoothed output |
| `reset_ema()` in battery tests | Prevents EMA state from bleeding between isolated validation profiles |
| Carbonation uses Stevens n=1.1, not linear | Matches the compressive perceptual build of CO₂ prickling with concentration |
| Snapshot passes last intensities + prompt | Avoids a second `process_data()` call that would misapply EMA to the same frame |
| `generate_bundle()` replaces `generate_audio_prompt()` in live pipeline | Prompt engine produces per-channel prompts covering all 8 dims including Temperature |
| OSC colour as 3 separate floats | TouchDesigner CHOPs map one address to one numeric channel; tuples not supported |
| `send_osc_data()` decoupled from `send_to_touchdesigner()` | Allows `run_app.py` to own the full pipeline without double-processing |
| `logger.flush()` after every row | Guarantees data survives a crash or Ctrl+C mid-session |

---

## 11. Perceptual Interactions (full detail)

After Stevens's Power Law and before EMA, `process_data()` applies cross-modal masking rules.
All thresholds and multipliers are tunable in `config/settings.yaml → interactions`.

### 11.1 Rules

| Rule | Condition | Effect | Basis |
|------|-----------|--------|-------|
| **Bitterness Suppression** | `Saltiness > 0.30` | `Bitterness × 0.80` (−20%) | NaCl competes at amiloride-sensitive epithelial sodium channels (McBurney, 1969) |
| **Sourness Suppression** | `Sweetness > 0.50` | `Sourness × 0.85` (−15%) | Sugar elevates the sourness threshold via type III taste receptor adaptation (Breslin & Beauchamp, 1997) |
| **Spicy Potentiation** | `Temperature > 0.70` | `Spiciness × 1.10` (+10%, ≤ 1.0) | Heat lowers TRPV1 capsaicin activation threshold (Caterina et al., 1997) |

### 11.2 Validation

The battery profile `"Double Espresso (Salted)"` (IBU 80, Salt 5.0 g/L) demonstrates Rule 1:

| Profile | Raw IBU | Saltiness (post-law) | Bitterness output |
|---------|---------|---------------------|-------------------|
| Double Espresso | 80 | 0.000 | ~0.748 |
| Double Espresso (Salted) | 80 | ~0.379 (> 0.30) | ~0.599 (−20%) |

Run `python tests/run_battery.py` to regenerate `docs/validation_report.txt` and confirm.
