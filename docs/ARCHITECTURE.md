# TasteData — Architecture Overview
Version 1.0 · 2026-04-20

This document is the canonical technical reference for the TasteData pipeline. A reader who has never seen the code should understand the full system from this file alone.

---

## 1. Purpose

TasteData is a synesthetic mapping system. It reads chemical and physical properties of food/drink from sensors (or simulation), converts raw measurements into **Perceived Intensities** using Stevens's Power Law, and emits the results as:

- **OSC messages** to TouchDesigner for real-time visual generation
- **Suno-formatted audio prompts** for AI music generation
- **CSV logs** for post-session analysis
- **JSON snapshots** for archiving notable taste frames on demand

---

## 2. File Structure

```
tasteData/
|
+-- config/
|   +-- settings.yaml         All tunable scientific constants (ranges, exponents, smoothing)
|
+-- docs/
|   +-- logic_manifesto.md    Research source: exponents, colors, cross-modal mappings
|   +-- ARCHITECTURE.md       This file
|   +-- validation_report.txt Output of tests/run_battery.py (regenerated on each run)
|
+-- logs/
|   +-- session_history.csv   Append-only CSV of every processed taste frame
|   +-- archive/              Old session files
|
+-- snapshots/                Per-label JSON snapshots (created on demand during runtime)
|
+-- src/
|   +-- brain.py              TasteMapper class — core scientific engine
|   +-- sensors.py            SensorReader class — serial / simulation data source
|   +-- bridge.py             OSC client — sends computed values to TouchDesigner
|   +-- logger.py             SessionLogger class — CSV append writer
|
+-- tests/
|   +-- run_battery.py        Validation battery: 7 standard food profiles
|
+-- requirements.txt          python-osc, pyserial, pyyaml
+-- run_app.py                Main entry point — orchestrates all modules
```

---

## 3. Data Flow

```
[Arduino / Simulation]
        |
        | CSV line: "ph,temp,brix,shu" @ 9600 baud  OR  bounded random walk
        v
src/sensors.py  (SensorReader)
  - Parses serial line into {"ph", "temp", "brix", "spicy"}
  - On disconnect or missing hardware: falls back to random-walk simulation
  - Simulation drifts within bounds that mirror settings.yaml normalization ranges
        |
        | raw frame dict
        v
src/brain.py  (TasteMapper.process_data)
  Step 1: Normalize each raw value to [0, 1] using YAML min/max bounds
  Step 2: Apply Stevens's Power Law   ->   Perception = normalized ^ exponent
  Step 3: Sourness special case       ->   sourness_input = 1.0 - normalized_pH
  Step 4: Apply EMA smoothing         ->   smoothed = alpha*new + (1-alpha)*prev
        |
        | intensities dict  (8 keys, all 0.0-1.0, EMA-smoothed)
        +--------------------------------------------+
        |                                            |
        v                                            v
TasteMapper.get_visual_params            TasteMapper.generate_audio_prompt
  - Weighted-average RGB colour            - Collect dimensions >= threshold (0.6)
    (Pink=Sweet, Yellow=Sour, Red=Spicy)   - Ranked by intensity, strongest first
  - Weighted-average angularity            - Tags + texture keywords concatenated
    (0=round/Sweet, 1=pointy/Spicy)        - Natural-language fusion sentence
  - Noise = Spicy*0.7 + Carbonation*0.3
        |                                            |
        +--------------------------------------------+
        |
        +---------> src/bridge.py  (send_osc_data)
        |           UDP to 127.0.0.1:7000
        |           /td/color/r|g|b  (float)
        |           /td/angularity   (float 0-1)
        |           /td/noise        (float 0-1)
        |           /td/audio_prompt (string via DAT)
        |
        +---------> src/logger.py  (SessionLogger.log_frame)
                    Appends one row to logs/session_history.csv

[On demand — via CLI 'S' key or direct call]
TasteMapper.save_flavor_snapshot(label, raw_data)
  -> calls process_data + generate_audio_prompt
  -> writes snapshots/{label}.json
```

---

## 4. Scientific Logic

### 4.1 Normalization Bounds (config/settings.yaml)

| Dimension   | Raw Unit        | Min   | Max    | Notes                              |
|-------------|-----------------|-------|--------|------------------------------------|
| pH          | pH scale        | 2.5   | 5.0    | Sourness = 1 - normalized_pH       |
| Temperature | degrees C       | 0.0   | 80.0   | Linear, no Stevens exponent        |
| Sweetness   | degrees Brix    | 0.0   | 20.0   |                                    |
| Spiciness   | SHU             | 0.0   | 50,000 |                                    |
| Carbonation | volumes CO2     | 0.0   | 5.0    | Linear, no Stevens exponent        |
| Bitterness  | IBU             | 0.0   | 100.0  |                                    |
| Saltiness   | g/L NaCl        | 0.0   | 10.0   |                                    |
| Umami       | glutamate units | 0.0   | 20.0   |                                    |

Values outside the range are silently clamped to [0, 1] before exponent application.

### 4.2 Stevens's Power Law Exponents (config/settings.yaml)

| Dimension   | Exponent | Perceptual Effect                                   |
|-------------|----------|-----------------------------------------------------|
| Sweetness   | 1.3      | Slightly compressed — sweetness builds slowly       |
| Sourness    | 1.1      | Near-linear                                         |
| Spiciness   | 0.8      | Expanded — pain/heat signals early and strongly     |
| Bitterness  | 1.3      | Matches sweetness compression                       |
| Saltiness   | 1.4      | Most compressed — salt perception saturates late    |
| Umami       | 1.0      | Perfectly linear passthrough                        |

Formula: `Perception = clamp(normalized, 0, 1) ^ exponent`

Safety guards in `_apply_power_law`:
- `value = 0`   ->  returns 0.0  (avoids 0^0 = 1 ambiguity)
- `exponent <= 0` ->  returns 1.0  (protects against bad YAML config)

### 4.3 EMA Smoothing (config/settings.yaml -> smoothing.alpha = 0.2)

```
smoothed[t] = 0.2 * raw[t]  +  0.8 * smoothed[t-1]
```

On the first frame (or after `reset_ema()`), `smoothed[t-1]` defaults to `raw[t]`,
so the first reading passes through unsmoothed with no phantom decay toward zero.

`reset_ema()` must be called between isolated calculations (e.g., the battery test
resets before each profile so profiles do not bleed into each other).

### 4.4 Audio Prompt Threshold

A taste dimension only contributes to the Suno prompt if its smoothed perceived
intensity >= 0.6 (configurable via `settings.yaml -> audio.threshold`).

---

## 5. Audio Descriptor Map (src/brain.py -> TasteMapper._DESCRIPTORS)

| Dimension   | Suno Tag                 | Texture Keyword              | Instrument                  |
|-------------|--------------------------|------------------------------|-----------------------------|
| Sweetness   | [Legato]                 | fragile, delicate textures   | soft, tinkling piano        |
| Sourness    | [Sharp Transients]       | jagged, shattered transients | staccato brass              |
| Spiciness   | [Fast Tempo]             | aggressive, dense energy     | industrial bit-crushed synth|
| Saltiness   | [Bright Articulation]    | crystalline textures         | staccato rhythms            |
| Umami       | [Low Frequency Dominant] | meaty, dark resonances       | deep bass sustain           |
| Carbonation | (none)                   | bright, tingling grain       | crackling harmonics         |
| Bitterness  | (none)                   | robust, dense bass           | distorted trombone          |

Output format:
  {tags}, {texture keywords}, A composition with {textures}, featuring {instruments}.

---

## 6. Snapshot Schema

File: snapshots/{label}.json

```json
{
  "label":     "string — the name provided at save time",
  "timestamp": "ISO 8601, second precision (e.g. 2026-04-20T15:04:57)",
  "raw_data": {
    "raw_ph":    0.0,
    "raw_temp":  0.0,
    "raw_brix":  0.0,
    "raw_spicy": 0.0,
    "raw_co2":   0.0,
    "raw_ibu":   0.0,
    "raw_salt":  0.0,
    "raw_umami": 0.0
  },
  "intensities": {
    "Sourness":    0.0,
    "Sweetness":   0.0,
    "Spiciness":   0.0,
    "Saltiness":   0.0,
    "Umami":       0.0,
    "Carbonation": 0.0,
    "Bitterness":  0.0,
    "Temperature": 0.0
  },
  "audio_prompt": "string — full Suno-formatted prompt"
}
```

All intensity values are EMA-smoothed and rounded to 6 decimal places.

---

## 7. CSV Log Schema

File: logs/session_history.csv

Columns (in order):
  timestamp, raw_ph, raw_temp, raw_brix, raw_spicy, raw_co2, raw_ibu,
  Sourness, Sweetness, Spiciness, Carbonation, Bitterness, Temperature,
  audio_prompt

One row per processed frame. Opened in append mode; header written once on first
creation. Each row is flushed immediately so no data is lost on crash.

---

## 8. TouchDesigner Wiring

OSC In CHOP: Network Port 7000, Local Address 127.0.0.1 (numeric channels)
OSC In DAT:  Network Port 7000 (string channel — audio_prompt)

| OSC Address      | Type   | Range   | Description                              |
|------------------|--------|---------|------------------------------------------|
| /td/color/r      | float  | 0-255   | Red channel of weighted taste colour     |
| /td/color/g      | float  | 0-255   | Green channel                            |
| /td/color/b      | float  | 0-255   | Blue channel                             |
| /td/angularity   | float  | 0.0-1.0 | Shape roundness (0) vs jaggedness (1)    |
| /td/noise        | float  | 0.0-1.0 | Visual grain / jitter intensity          |
| /td/audio_prompt | string | —       | Full Suno prompt (read via OSC In DAT)   |

---

## 9. Running the System

```bash
# Install dependencies
pip install -r requirements.txt

# Run with hardware (pass your serial port)
python run_app.py COM3            # Windows
python run_app.py /dev/ttyUSB0    # Linux / macOS

# Run in simulation mode (auto-fallback when no port is reachable)
python run_app.py

# Interactive commands while running:
#   S + Enter  ->  prompted for a label, saves snapshots/{label}.json
#   Q + Enter  ->  graceful shutdown
#   Ctrl+C     ->  immediate shutdown

# Validation battery (regenerates docs/validation_report.txt)
python tests/run_battery.py

# Test brain.py in isolation
python src/brain.py
```

---

## 10. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Config in YAML, not hardcoded | Scientific constants change during tuning; keeping them in code forces redeploys |
| EMA smoothing in brain.py, not sensors.py | Smoothing is a perceptual model choice, not a hardware concern |
| battery test calls reset_ema() per profile | Prevents EMA state from bleeding between isolated validation profiles |
| OSC color sent as 3 separate floats | TouchDesigner CHOPs map one OSC address to one numeric channel; tuples are not supported |
| send_osc_data() separated from send_to_touchdesigner() | Allows run_app.py to own the full pipeline (Sensors -> Brain -> OSC) without double-processing |
| logger.flush() after every row | Guarantees data survives a crash or Ctrl+C mid-session |

---

## 11. Perceptual Interactions

After Stevens's Power Law is applied but **before** EMA smoothing, `process_data` applies a set of cross-modal suppression and potentiation rules derived from psychophysical masking research. These rules model the fact that taste dimensions do not sum independently — certain combinations actively inhibit or amplify each other at the receptor level.

All thresholds and multipliers live in `config/settings.yaml → interactions` so they can be re-tuned without touching code.

### 11.1 Rules (evaluated on post-Power-Law, pre-EMA intensities)

| Rule | Condition | Effect | Scientific Basis |
|------|-----------|--------|-----------------|
| **Bitterness Suppression** | `Saltiness > 0.30` | `Bitterness × 0.80` (−20%) | NaCl selectively suppresses bitter transduction by competing at amiloride-sensitive channels (McBurney, 1969) |
| **Sourness Suppression** | `Sweetness > 0.50` | `Sourness × 0.85` (−15%) | Dissolved sugars elevate the perceived sourness threshold; the effect scales with sugar concentration (Breslin & Beauchamp, 1997) |
| **Spicy Boost (Heat)** | `Temperature > 0.70` | `Spiciness × 1.10` (+10%, clamped ≤ 1.0) | Elevated tissue temperature sensitises TRPV1 capsaicin receptors, lowering the capsaicin activation threshold and amplifying perceived heat (Caterina et al., 1997) |

### 11.2 Implementation in `process_data`

```
raw_intensities = {Power Law outputs for all 8 dimensions}

if Saltiness  > SALT_BITTER_THRESHOLD : Bitterness *= (1 - SALT_BITTER_REDUCTION)
if Sweetness  > SWEET_SOUR_THRESHOLD  : Sourness   *= (1 - SWEET_SOUR_REDUCTION)
if Temperature > HEAT_SPICY_THRESHOLD : Spiciness   = min(1.0, Spiciness * (1 + HEAT_SPICY_BOOST))

return EMA(raw_intensities)
```

Applying interactions **before** EMA ensures the smoothed output reflects the chemosensory reality of the current frame rather than smoothing a pre-interaction value. Applying them **after** Stevens's Law preserves the non-linear psychophysical compression/expansion before modifying the result.

### 11.3 Validation

The battery test profile `"Double Espresso (Salted)"` (IBU 80, Salt 5.0 g/L) demonstrates the bitterness suppression rule. Expected values:

| Profile | Raw IBU | Saltiness (post-law) | Suppression | Bitterness Output |
|---------|---------|---------------------|-------------|-------------------|
| Double Espresso | 80 | 0.000 | none | ~0.745 |
| Double Espresso (Salted) | 80 | ~0.379 (> 0.30) | −20% | ~0.596 |

Run `python tests/run_battery.py` to regenerate `docs/validation_report.txt` and confirm.
