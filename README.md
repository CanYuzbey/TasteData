# TasteData: A Gastrophysics-to-Generative-Art Pipeline

**Sabancı University — IF201**  
**Version 1.0 — April 2026**

---

## Table of Contents

1. [Project Vision](#1-project-vision)
2. [Scientific Architecture](#2-scientific-architecture)
   - 2.1 [Stevens's Power Law](#21-stevenss-power-law)
   - 2.2 [EMA Signal Processing](#22-ema-signal-processing-fluid-perception)
   - 2.3 [Perceptual Interaction Layer](#23-perceptual-interaction-layer)
3. [The Data Pipeline: Hardware to Art](#3-the-data-pipeline-hardware-to-art)
   - 3.1 [Serial Input Format](#31-serial-input-format)
   - 3.2 [Processing Chain](#32-processing-chain)
   - 3.3 [OSC Output Map](#33-osc-output-map)
4. [Project Structure](#4-project-structure)
5. [Execution Guide](#5-execution-guide)
6. [Future Vision](#6-future-vision)
7. [References](#7-references)

---

## 1. Project Vision

TasteData is a real-time synesthetic mapping system that dissolves the boundary between gastrophysics and generative art. The system reads chemical and physical properties of food and beverages — acidity, sweetness, heat, salinity, umami, carbonation, and bitterness — using an Arduino-based sensor array, and converts those raw measurements into the language of perception using established models from psychophysics. The resulting *Perceived Intensity* values drive two parallel creative outputs: a live visual environment rendered in TouchDesigner, where color, angularity, and noise respond continuously to the evolving taste profile of whatever liquid is placed on the sensor platform, and a structured natural-language prompt delivered to an AI music generation system, instructing it to compose music whose timbre, texture, and tempo are determined by the chemical reality of the food being tasted. The core proposition is that taste is not a subjective, ineffable experience but a measurable, reproducible signal — and that signal, processed through the same mathematical laws that govern all human perception, can be made to speak directly to the eye and the ear. TasteData is both a scientific instrument and an artistic interface.

---

## 2. Scientific Architecture

### 2.1 Stevens's Power Law

The fundamental problem in translating raw sensor readings into perceptual outputs is that human sensation is not linear. A doubling of physical stimulus intensity does not produce a doubling of perceived sensation. This non-linearity is not random — it follows a precise mathematical form described by S.S. Stevens in 1957 following decades of magnitude estimation experiments across all sensory modalities:

```
Ψ(I) = k · I^n
```

where `Ψ(I)` is the perceived magnitude, `I` is the physical stimulus intensity (normalized to `[0, 1]`), `k` is a scaling constant (set to 1 in this system by the normalization step), and `n` is the **modality-specific exponent** calibrated through psychophysical research (Stevens, 1957).

The exponent is the scientific core of the model. Values below 1.0 produce an *expansive* curve — perception rises sharply at low stimulus intensities and saturates slowly. Values above 1.0 produce a *compressive* curve — perception builds gradually and saturates late. Each taste dimension in TasteData carries its own exponent, sourced from the sensory science literature:

| Dimension   | Exponent | Perceptual Interpretation |
|-------------|----------|---------------------------|
| Sweetness   | 1.3      | Compressive — sweetness builds slowly; sugar perception saturates late |
| Sourness    | 1.1      | Near-linear — acid detection is relatively proportional |
| Spiciness   | 0.8      | Expansive — capsaicin pain signals strongly at low concentrations |
| Bitterness  | 1.3      | Compressive — matches sweetness; bitter is a slow-building warning signal |
| Saltiness   | 1.4      | Most compressive — NaCl perception saturates latest of all taste dimensions |
| Umami       | 1.0      | Linear — glutamate detection passes through unchanged |

Two dimensions — Temperature and Carbonation — are treated as linear physical percepts (exponent 1.0) because their primary role is sensory context rather than chemical taste signal.

A critical implementation detail: sourness is derived not from a direct sensor reading but from the *inverse* of normalized pH. Because pH is a logarithmic inverse scale of acidity, lower pH values correspond to greater perceived sourness. The transformation `sourness_input = 1.0 − normalized_pH` maps the pH scale onto an intuitive 0-to-1 sourness axis before the power law is applied.

All normalization bounds and exponent values are stored externally in `config/settings.yaml`, making them re-tuneable without modifying source code — a design decision that treats the scientific constants of the model as configuration, not implementation.

---

### 2.2 EMA Signal Processing: Fluid Perception

Raw sensor data arriving from the Arduino is inherently noisy. Frame-to-frame jitter — caused by thermal drift, electrochemical equilibration delay, and ADC quantization — would produce perceived intensities that flicker rapidly even when the physical stimulus is constant. Passing this directly to TouchDesigner would generate incoherent visual output; passing it to the audio prompt generator would produce meaningless prompt variation.

The solution is an **Exponential Moving Average (EMA)**, applied per dimension after the power law and after the perceptual interaction rules:

```
smoothed[t] = α · raw[t]  +  (1 − α) · smoothed[t − 1]
```

The parameter `α` (alpha) controls the trade-off between responsiveness and stability. At `α = 0.2` and a frame rate of 10 Hz, the system exhibits two analytically predictable behaviours:

**Per-frame lag on a continuous ramp:**

```
lag = (1 − α) / α / fps  =  (0.8 / 0.2) / 10  =  0.40 seconds
```

This means that when a beverage is being poured and its properties change gradually, the perceived output trails the physical reality by only 400 milliseconds — imperceptible to an observer watching the visual output in real time.

**Step-function convergence (sudden change):**

When a stimulus changes instantaneously (for example, a drop of hot sauce added to a drink), the number of frames required for the EMA output to reach 90% of the new target is:

```
N = log(1 − 0.9) / log(1 − α) = log(0.1) / log(0.8) ≈ 10.32  →  11 frames  =  1.1 seconds
```

This 1.1-second rise time was chosen deliberately. It is fast enough to feel responsive during live performance but slow enough to prevent single-frame noise spikes from reaching the output. The result is what the project calls *Fluid Perception* — the output behaves as if the system is tasting, not merely measuring.

The first-frame boundary condition is handled carefully: when no prior state exists, `smoothed[t-1]` defaults to `raw[t]`, so the very first reading passes through unsmoothed with no phantom decay toward zero. Between isolated analytical runs (such as the validation battery), `reset_ema()` clears the state to prevent cross-contamination.

The validation script `tests/mock_stream_server.py` provides a full empirical analysis of both the ramp and step scenarios, confirming that the analytical predictions match the simulated behaviour to within one frame of rounding error.

---

### 2.3 Perceptual Interaction Layer

Human taste perception is not a simple sum of independent dimensions. Chemical compounds interact at the receptor level and in cortical processing, causing certain taste dimensions to suppress or amplify others. TasteData implements three of the best-documented interactions from the sensory science literature, applied after the power law and before EMA smoothing:

**Rule 1 — Salt Suppresses Bitterness**

> *Condition:* `Saltiness > 0.30`  
> *Effect:* `Bitterness × 0.80` (−20%)

Sodium chloride selectively reduces bitter transduction by competing at amiloride-sensitive epithelial sodium channels, effectively raising the bitterness detection threshold. The phenomenon has been replicated across concentration ranges consistent with culinary use (McBurney, 1969). This is the scientific principle behind the folk practice of adding a pinch of salt to coffee.

**Rule 2 — Sweetness Suppresses Sourness**

> *Condition:* `Sweetness > 0.50`  
> *Effect:* `Sourness × 0.85` (−15%)

Dissolved sugars elevate the threshold at which acid is perceived as sour, through a mechanism believed to involve peripheral adaptation at type III taste receptor cells. The suppression effect has been measured to scale with sugar concentration, with the threshold for onset at approximately moderate sweetness levels (Breslin & Beauchamp, 1997). This models the experience of sweetened citrus drinks tasting less sharp than unsweetened counterparts at the same pH.

**Rule 3 — Heat Potentiates Spiciness**

> *Condition:* `Temperature > 0.70`  
> *Effect:* `Spiciness × 1.10` (+10%, clamped to 1.0)

The TRPV1 (Transient Receptor Potential Vanilloid 1) ion channel is the primary receptor for both capsaicin and noxious heat. Elevated tissue temperature reduces the activation threshold of TRPV1, meaning that the same capsaicin concentration is perceived as more intense when the food is served hot. This has been confirmed at the molecular level by Caterina et al. (1997), who showed that TRPV1 is a polymodal nociceptor responding to both chemical and thermal stimuli.

All three thresholds and reduction factors are stored in `config/settings.yaml → interactions` and can be re-calibrated without touching source code.

---

## 3. The Data Pipeline: Hardware to Art

### 3.1 Serial Input Format

The Arduino sensor platform transmits a single comma-separated line at 9600 baud at 10 Hz. Each line encodes one complete taste frame:

```
ph,temp,brix,shu,co2,ibu,salt,glutamate
```

| Field | Sensor Type | Unit | Normalization Range |
|-------|-------------|------|---------------------|
| `ph` | pH electrode | pH scale | 2.5 – 5.0 |
| `temp` | NTC thermistor | degrees Celsius | 0.0 – 80.0 |
| `brix` | optical refractometer | degrees Brix | 0.0 – 20.0 |
| `shu` | capsaicin sensor | Scoville Heat Units | 0 – 50,000 |
| `co2` | dissolved CO₂ sensor | volumes CO₂ | 0.0 – 5.0 |
| `ibu` | spectrophotometric IBU | IBU | 0.0 – 100.0 |
| `salt` | conductivity probe | g/L NaCl | 0.0 – 10.0 |
| `glutamate` | glutamate biosensor | arbitrary sensor units | 0.0 – 20.0 |

Values outside the calibrated range are silently clamped to `[0, 1]` before entering the processing chain. The system falls back automatically to a bounded random-walk simulation if no serial device is detected, preserving full pipeline functionality for development and exhibition use without hardware.

---

### 3.2 Processing Chain

```
[Arduino @ 9600 baud]
        |
        |  "ph,temp,brix,shu,co2,ibu,salt,glutamate\n"
        v
src/sensors.py  (SensorReader)
  Parse CSV line into typed dict
  Fallback: bounded random-walk simulation
        |
        |  raw frame: {"ph": float, "temp": float, ...}
        v
src/brain.py  (TasteMapper.process_data)
  Step 1 — Normalize each field to [0, 1] using YAML bounds
  Step 2 — Stevens's Power Law: Perception = normalized ^ exponent
  Step 3 — Sourness inversion: sourness_input = 1.0 - normalized_pH
  Step 4 — Perceptual Interactions (suppression / boost rules)
  Step 5 — EMA Smoothing: smoothed = 0.2 * new + 0.8 * prev
        |
        |  intensities: {"Sourness": float, "Sweetness": float, ...}  (all in [0, 1])
        |
        +---------> TasteMapper.get_visual_params  -----> src/bridge.py (OSC to TouchDesigner)
        |
        +---------> TasteMapper.generate_audio_prompt -----> src/bridge.py (OSC string channel)
        |
        +---------> src/logger.py (SessionLogger)   -----> logs/session_history.csv
```

---

### 3.3 OSC Output Map

The bridge module (`src/bridge.py`) transmits all computed values as UDP packets to `127.0.0.1:7000` using the Open Sound Control (OSC) protocol. TouchDesigner receives these on two node types:

- **OSC In CHOP** — handles numeric channels (one OSC address = one named CHOP channel)
- **OSC In DAT** — handles the string payload of the audio prompt

| OSC Address | Type | Range | Description |
|-------------|------|-------|-------------|
| `/td/color/r` | float | 0 – 255 | Red channel of the weighted taste colour |
| `/td/color/g` | float | 0 – 255 | Green channel |
| `/td/color/b` | float | 0 – 255 | Blue channel |
| `/td/angularity` | float | 0.0 – 1.0 | Shape morphology: 0 = circular (sweet), 1 = jagged (spicy) |
| `/td/noise` | float | 0.0 – 1.0 | Visual grain intensity: `Spiciness × 0.7 + Carbonation × 0.3` |
| `/td/audio_prompt` | string | — | Full Suno V4-formatted prompt, read via OSC In DAT |

The colour is computed as an intensity-weighted average of three anchor colours — Pink (255, 182, 193) for Sweetness, Yellow (255, 255, 0) for Sourness, Red (255, 0, 0) for Spiciness — producing a continuous chromatic space that reflects the dominant taste character of each frame. A neutral gray (200, 200, 200) is returned when all three anchor dimensions are below noise floor.

---

## 4. Project Structure

```
tasteData/
|
+-- config/
|   +-- settings.yaml         All scientific constants: normalization bounds, Stevens
|                             exponents, EMA alpha, interaction thresholds.
|                             Editing this file re-tunes the algorithm without
|                             touching any source code.
|
+-- docs/
|   +-- logic_manifesto.md    Primary research document: citations, exponent
|                             derivations, cross-modal mapping rationale.
|   +-- ARCHITECTURE.md       Full technical reference for the pipeline (10 sections).
|   +-- validation_report.txt Output of run_battery.py — regenerated on every run.
|   +-- pour_analysis.txt     Output of mock_stream_server.py — EMA fluidity study.
|
+-- logs/
|   +-- session_history.csv   Append-only CSV log of every processed taste frame.
|   +-- archive/              Rotated session files from previous runs.
|
+-- snapshots/
|                             Per-label JSON files saved on demand during a live
|                             session (CLI 'S' key). Each file captures: raw sensor
|                             values, all 8 perceived intensities, and the full
|                             audio prompt at the moment of capture.
|
+-- src/
|   +-- brain.py              TasteMapper — the core scientific engine. Contains the
|                             Stevens's Law implementation, EMA, perceptual interaction
|                             rules, visual parameter computation, audio prompt
|                             generation, and snapshot serialisation.
|   +-- sensors.py            SensorReader — serial device abstraction with automatic
|                             hardware/simulation fallback.
|   +-- bridge.py             OSC client — transmits all outputs to TouchDesigner.
|   +-- logger.py             SessionLogger — CSV append writer with per-frame flush.
|   +-- analyzer.py           Snapshot Library Analyzer — reads snapshots/ and
|                             generates a Digital Menu table and Global Flavor Profile.
|
+-- tests/
|   +-- run_battery.py        Validation battery — 8 standard food profiles processed
|                             in isolation. Confirms correctness of each pipeline
|                             stage and documents the effect of interaction rules.
|   +-- mock_stream_server.py EMA fluidity study — simulates a 30-second beverage
|                             pour at 10 Hz and measures convergence behaviour.
|
+-- requirements.txt          python-osc, pyserial, pyyaml
+-- run_app.py                Main entry point — full pipeline orchestration with
                              interactive CLI (S = snapshot, Q = quit).
```

---

## 5. Execution Guide

**Prerequisites**

```bash
pip install -r requirements.txt
```

---

**Validation Battery** — runs 8 food profiles through the full pipeline and saves a formatted report:

```bash
python tests/run_battery.py
```

Output is printed to the terminal and written to `docs/validation_report.txt`. Each profile shows all 8 perceived intensities, the computed visual parameters, and the generated Suno audio prompt. The battery calls `reset_ema()` between profiles to guarantee isolation.

---

**Snapshot Library Analyzer** — reads all saved snapshots and generates a statistical overview:

```bash
python src/analyzer.py
```

Prints a Digital Menu table (Drink Name | Primary Tastes | Mood Tag) and a Global Flavor Profile showing the dominant dimension and per-dimension average intensities across the entire snapshot library. Run this after accumulating snapshots from live sessions to analyse the collective taste character of a recorded event.

---

**Main Application** — starts the real-time pipeline:

```bash
# Hardware mode (pass your serial port)
python run_app.py COM3             # Windows
python run_app.py /dev/ttyUSB0    # Linux / macOS

# Simulation mode (auto-fallback when no hardware is present)
python run_app.py
```

Interactive commands while running:

| Key | Action |
|-----|--------|
| `S` + Enter | Prompted for a label; saves a full snapshot to `snapshots/{label}.json` |
| `Q` + Enter | Graceful shutdown — flushes the CSV log and closes all resources |
| Ctrl+C | Immediate shutdown |

---

**EMA Fluidity Analysis** — runs the virtual pour simulation and saves an analysis report:

```bash
python tests/mock_stream_server.py
```

Output is saved to `docs/pour_analysis.txt`. Useful for understanding EMA behaviour before adjusting `alpha` in `settings.yaml`.

---

## 6. Future Vision

The current audio output of TasteData is a structured natural-language prompt — a carefully engineered string of Suno tags, texture descriptors, and instrument references that instructs a cloud-based AI music system to compose within the parameters defined by the taste data. This approach is effective and produces coherent, contextually appropriate music, but it introduces a fundamental latency: the round-trip time to the generation API means that the audio cannot be considered truly real-time. The taste data changes frame by frame at 10 Hz; the music changes on the timescale of minutes.

Phase X of the project envisions closing this gap entirely by moving from *prompt-based* audio generation to *direct real-time synthesis*. In this model, the 8 perceived intensity values would map continuously to synthesis parameters — oscillator frequency ratios, filter cutoff frequencies, reverb decay times, granular synthesis density, spectral tilt — within a local audio synthesis engine such as SuperCollider or a WebAudio-based custom synthesizer. The audio would respond to the taste data at the same 10 Hz frame rate as the visual output, creating a fully synchronized three-channel synesthetic experience: chemical reality driving light, shape, and sound simultaneously and without latency.

The scientific architecture is already designed for this transition. The `intensities` dictionary produced by `TasteMapper.process_data` is a normalized, smoothed, interaction-corrected 8-dimensional vector that maps cleanly onto any parameter space. Replacing the OSC string channel carrying the Suno prompt with a set of OSC float channels carrying synthesis parameters requires changes only to `src/bridge.py` and the downstream synthesis patch — the core psychophysical engine remains untouched.

---

## 7. References

Breslin, P. A. S., & Beauchamp, G. K. (1997). Salt enhances flavour by suppressing bitterness. *Nature*, *387*(6633), 563. https://doi.org/10.1038/42388

Caterina, M. J., Schumacher, M. A., Tominaga, M., Rosen, T. A., Levine, J. D., & Julius, D. (1997). The capsaicin receptor: A heat-activated ion channel in the pain pathway. *Nature*, *389*(6653), 816–824. https://doi.org/10.1038/39807

McBurney, D. H. (1969). Effects of adaptation on human taste function. In C. Pfaffmann (Ed.), *Olfaction and Taste III* (pp. 407–419). Rockefeller University Press.

Stevens, S. S. (1957). On the psychophysical law. *Psychological Review*, *64*(3), 153–181. https://doi.org/10.1037/h0046162

---

*TasteData is developed as coursework for IF201 at Sabancı University. All scientific constants and calibration values reflect published psychophysical literature and are stored externally in `config/settings.yaml` to support ongoing empirical refinement.*
