# TasteData: A Gastrophysics-to-Generative-Art Pipeline

**Sabancı University — IF201**  
**Version 2.0 — April 2026**

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
   - 3.4 [Multi-Channel Prompt Engine](#34-multi-channel-prompt-engine)
4. [Project Structure](#4-project-structure)
5. [Execution Guide](#5-execution-guide)
6. [Future Vision](#6-future-vision)
7. [References](#7-references)

---

## 1. Project Vision

TasteData is a real-time synesthetic mapping system that dissolves the boundary between gastrophysics and generative art. The system reads chemical and physical properties of food and beverages — acidity, sweetness, heat, salinity, umami, carbonation, and bitterness — using an Arduino-based sensor array, and converts those raw measurements into the language of perception using established models from psychophysics. The resulting *Perceived Intensity* values drive two parallel creative outputs: a live visual environment rendered in TouchDesigner, where color, angularity, and noise respond continuously to the evolving taste profile of whatever liquid is placed on the sensor platform, and a structured natural-language prompt bundle delivered to an AI music generation system, instructing it to compose music whose timbre, texture, tempo, and per-channel arrangement are determined by the chemical reality of the food being tasted.

The core proposition is that taste is not a subjective, ineffable experience but a measurable, reproducible signal — and that signal, processed through the same mathematical laws that govern all human perception, can be made to speak directly to the eye and the ear. TasteData is both a scientific instrument and an artistic interface.

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
| Carbonation | 1.1      | Slightly compressive — CO₂ prickle crosses a sharp perceptual threshold |

Temperature is treated as a linear physical percept (no power law applied) because its primary role is sensory context rather than a discrete chemical taste signal. Critically, temperature is not filtered out of the output pipeline — it is a first-class input to the prompt engine and visual parameter system, where it governs reverb character, articulation tightness, mix density, and stereo field width.

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
        +---------> TasteMapper.get_visual_params  ──────────> src/bridge.py  (OSC to TouchDesigner)
        |
        +---------> src/prompt_engine.py  (generate_bundle)
        |              Stage 1: compute_axes    ─ 8 dims → 5 aesthetic axes + temp_feel
        |              Stage 2: select_genre    ─ MSE score against 12 genre profiles
        |              Stage 3: build_roster    ─ 3–12 channels scaled by richness/energy
        |              Stage 4: render_channel  ─ all 8 dims contribute to every channel
        |                                       ↓
        |                               PromptBundle
        |                                 .channels[]   ─ per-channel Suno prompts
        |                                 .master_prompt ─ combined master prompt
        |                                       ↓
        |                               src/bridge.py  (OSC string channel)
        |
        +---------> src/logger.py (SessionLogger)  ──────────> logs/session_history.csv
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
| `/td/audio_prompt` | string | — | Master Suno prompt from `PromptBundle.master_prompt` |
| `/tastedata/carbonation/grain_density` | float | 0.0 – 1.0 | ψ(CO₂) — granular synthesis density |
| `/tastedata/carbonation/grain_pitch_center` | float | 2000 – 20000 Hz | Log-mapped grain pitch |
| `/tastedata/carbonation/particle_angularity` | float | 0.0 – 1.0 | Particle shape: 0 = spherical, 1 = shard |
| `/tastedata/carbonation/particle_speed` | float | 0.0 – 1.0 | \|ΔCO₂\| × 10 — fizz-out rate |

The colour is computed as an intensity-weighted average of three anchor colours — Pink (255, 182, 193) for Sweetness, Yellow (255, 255, 0) for Sourness, Red (255, 0, 0) for Spiciness — producing a continuous chromatic space that reflects the dominant taste character of each frame. A neutral gray (200, 200, 200) is returned when all three anchor dimensions are below noise floor.

---

### 3.4 Multi-Channel Prompt Engine

`src/prompt_engine.py` is a standalone module that replaces the single-string audio prompt with a structured **PromptBundle** containing individual prompts per track channel and a combined master prompt optimised for Suno V4's natural-language parser. The design was driven by two principles: every taste dimension — including Temperature — must influence every channel output, and the system should reason about music the way a human producer would before generating any text.

#### Stage 1 — FlavorAxes

The 8 perceived intensities are first compressed into 5 aesthetic axes that capture the producer-level intuition about a food's character:

| Axis | Formula | What it represents |
|------|---------|-------------------|
| `energy` | `Spiciness×0.40 + Sourness×0.25 + Carbonation×0.20 + Temperature×0.10 + Saltiness×0.05` | Arousal, activation, aggressiveness |
| `warmth` | `Sweetness×0.40 + Umami×0.30 + Temperature×0.20 − Bitterness×0.10` | Hedonic comfort, sweetness-umami glow |
| `darkness` | `Bitterness×0.45 + Sourness×0.25 + (1−Sweetness)×0.20 + (1−Temperature)×0.10` | Timbral weight, minor key pull |
| `texture` | `Carbonation×0.50 + Saltiness×0.30 + Spiciness×0.20` | Stochastic grain, surface roughness |
| `richness` | `Umami×0.45 + Sweetness×0.30 + Saltiness×0.25` | Harmonic fullness, spectral density |

`temp_feel` is preserved as a raw normalized value alongside the axes because temperature has qualitatively different effects at cold, warm, and hot ranges that a single axis position cannot capture.

#### Stage 2 — Genre Selection

Twelve genre profiles are defined as points in the 6-dimensional axis space (energy, warmth, darkness, texture, richness, temp_feel). The system scores every genre using weighted mean squared error against the current axes — energy and darkness carry the highest weights (0.28 and 0.24) because they are the most genre-discriminative dimensions — and selects the closest match. The selected genre determines BPM range, key/mode tendency, channel role roster, and mix aesthetic.

| Genre | Ideal energy | Ideal warmth | Ideal darkness | Typical channels |
|---|---|---|---|---|
| Dark Techno / Industrial | 0.80 | 0.10 | 0.80 | 7 |
| Hyperpop / Club | 0.90 | 0.45 | 0.20 | 8 |
| Tropical House / Afrobeat | 0.65 | 0.80 | 0.10 | 7 |
| Dark Ambient / Drone | 0.05 | 0.20 | 0.90 | 5 |
| Jazz / Soul | 0.40 | 0.80 | 0.40 | 7 |
| Dream Pop / Shoegaze | 0.30 | 0.80 | 0.20 | 7 |
| Minimal Techno | 0.50 | 0.20 | 0.50 | 5 |
| IDM / Glitch | 0.55 | 0.30 | 0.50 | 7 |
| Neo-Soul / R&B | 0.35 | 0.90 | 0.25 | 7 |
| Cinematic Orchestral | 0.55 | 0.50 | 0.60 | 8 |
| Punk / Noise Rock | 0.95 | 0.10 | 0.60 | 6 |
| Ambient Electronic | 0.10 | 0.60 | 0.30 | 5 |

BPM is selected within the genre's range by `energy × 0.55 + temp_feel × 0.20 − warmth × 0.15 − richness × 0.10`. Key/mode is derived from darkness and warmth: deep darkness maps to Phrygian or Locrian; moderate darkness maps to natural minor or Dorian; high warmth maps to Lydian or major.

#### Stage 3 — Channel Roster

The active channel count is scaled by `richness × 0.60 + energy × 0.40`, ranging from a minimum of 3 channels (for very sparse, quiet profiles) up to the genre's full roster. Channels are taken in mix-priority order — foundation channels (kick, bass) always render; texture and atmosphere channels are the first to be dropped for sparse profiles.

#### Stage 4 — Per-Channel Rendering

Each channel receives three rendering passes, and all 8 taste dimensions contribute to every pass:

**Timbral adjectives** — every dimension produces a descriptive word even at low intensities (no threshold gating). Examples: Sweetness → "silky and warm" / "smooth and rounded" / "slightly warm"; Sourness → "piercing and acidic" / "bright with a sharp edge"; Spiciness → "heavily saturated and overdriven" (signal channels) / "aggressive and dense". Temperature is handled in continuous ranges: `te > 0.80` → "hot and saturated — dense and steamy like a heat haze"; `0.40–0.60` → "room-temperature — clear and neutral"; `te < 0.20` → "cold and sterile — icy precision".

**Articulation** — role-aware playing style description. Sustained roles (pads, atmospheres, drones) receive slow-attack, bloom, and sustain language; rhythmic roles (kicks, percussion) receive transient and decay language. Temperature shapes this directly: cold profiles produce "extremely tight decay — no room in the cold" for percussion and "sparse, crystalline sustain — notes hang in cold air" for pads; hot profiles produce "slightly extended decay — temperature adds warmth to the tail" and "dense sustained body — saturated and slow-moving".

**Effects chain** — Temperature is the **primary reverb driver**, contributing 0.50 weight in the reverb formula (Sweetness 0.25, Umami 0.15). `te > 0.75` → dense plate reverb + wide mid-side stereo; `te < 0.20` → almost dry, narrow mono-compatible image. Spiciness drives distortion and bitcrushing; Sourness drives rhythmic delay and high-pass filter presence; Bitterness closes a low-pass filter on non-bass channels; Saltiness adds chorus/ensemble detune shimmer; Carbonation drives granular synthesis with grain pitch mapped to 2–20 kHz proportionally to CO₂ intensity.

The output is a `PromptBundle` containing one `RenderedChannel` per active channel and a master prompt structured in the order Suno's parser responds to best: style tags → BPM/key → one-sentence overall mood → condensed arrangement → dominant sensory signature.

---

## 4. Project Structure

```
tasteData/
|
+-- config/
|   +-- settings.yaml         All scientific constants: normalization bounds, Stevens
|                             exponents, EMA alpha, interaction thresholds, carbonation
|                             grain synthesis parameters.
|
+-- docs/
|   +-- logic_manifesto.md    Primary research document: citations, exponent
|                             derivations, cross-modal mapping rationale.
|   +-- ARCHITECTURE.md       Full technical reference for the pipeline (10 sections).
|   +-- validation_report.txt Output of run_battery.py — regenerated on every run.
|   +-- pour_analysis.txt     Output of mock_stream_server.py — EMA fluidity study.
|   +-- synthetic_test_report.txt
|                             Output of tests/synthetic_test.py — 21 test cases with
|                             analytically computed expected values.
|
+-- logs/
|   +-- session_history.csv   Append-only CSV log of every processed taste frame.
|   +-- archive/              Rotated session files from previous runs.
|
+-- snapshots/
|                             Per-label JSON files saved on demand during a live
|                             session (CLI 'S' key). Each file captures: raw sensor
|                             values, all 8 perceived intensities, and the
|                             PromptBundle.master_prompt at the moment of capture.
|
+-- src/
|   +-- brain.py              TasteMapper — the core scientific engine. Implements
|                             Stevens's Power Law, EMA, perceptual interaction rules,
|                             visual parameter computation, legacy single-string audio
|                             prompt generation, and snapshot serialisation.
|                             Also contains PsychophysicalScaler — a standalone class
|                             importable into TouchDesigner without the full pipeline.
|   +-- prompt_engine.py      Multi-Channel Suno Prompt Engine — standalone module.
|                             Accepts TasteMapper intensities and produces a
|                             PromptBundle: genre selection across 12 profiles, 3–12
|                             per-channel Suno prompts, and a combined master prompt.
|                             All 8 taste dimensions (including Temperature) contribute
|                             to every channel's timbre, articulation, and FX chain.
|   +-- sensors.py            SensorReader — serial device abstraction with automatic
|                             hardware/simulation fallback.
|   +-- bridge.py             OSC client — processes all 8 sensor fields via
|                             TasteMapper, calls generate_bundle() for the master
|                             prompt, and transmits visual params + prompt over OSC.
|   +-- logger.py             SessionLogger — CSV append writer with per-frame flush.
|   +-- analyzer.py           Snapshot Library Analyzer — reads snapshots/ and
|                             generates a Digital Menu table and Global Flavor Profile.
|
+-- tests/
|   +-- run_battery.py        Validation battery — 8 standard food profiles processed
|                             in isolation. Confirms correctness of each pipeline
|                             stage and documents the effect of interaction rules.
|                             Writes docs/validation_report.txt.
|   +-- synthetic_test.py     Synthetic test suite — 21 test cases with analytically
|                             pre-computed expected values covering: all 7 pure
|                             dimensions in isolation, all 3 interaction rules (fire /
|                             no-fire), real food profiles, edge cases (all-zero,
|                             out-of-range clamp, EMA first-frame identity).
|                             Tolerance 1e-4. Exit code 1 on any failure.
|   +-- mock_stream_server.py EMA fluidity study — simulates a 30-second beverage
|                             pour at 10 Hz and measures convergence behaviour.
|
+-- firmware/
|   +-- TasteData_Sensor_Node.ino  Arduino firmware. Outputs one CSV line per 100 ms
|                                  at 9600 baud. Set SIMULATE=true for bench testing
|                                  without physical sensors.
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

Output is printed to the terminal and written to `docs/validation_report.txt`. Each profile shows all 8 perceived intensities, the computed visual parameters, and the generated audio prompt. The battery calls `reset_ema()` between profiles to guarantee isolation.

---

**Synthetic Test Suite** — verifies the algorithm against 21 analytically computed expected values:

```bash
python tests/synthetic_test.py
```

Covers pure dimensions in isolation, all three interaction rules at and below their thresholds, real food profiles (Cola, Espresso, Miso Soup), and edge cases including out-of-range clamping and EMA first-frame identity. Exits with code 1 if any test fails. Report saved to `docs/synthetic_test_report.txt`.

---

**Prompt Engine Demo** — runs 5 food profiles through the multi-channel prompt engine:

```bash
python src/prompt_engine.py
```

Prints a full `PromptBundle` for each profile: selected genre, BPM, key/mode, all active channels with individual prompts, and the combined master prompt ready for Suno V4.

---

**Snapshot Library Analyzer** — reads all saved snapshots and generates a statistical overview:

```bash
python src/analyzer.py
```

Prints a Digital Menu table (Drink Name | Primary Tastes | Mood Tag) and a Global Flavor Profile showing the dominant dimension and per-dimension average intensities across the entire snapshot library.

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

The prompt engine (`src/prompt_engine.py`) introduced in Version 2.0 resolves the most significant limitation of the original audio output system: the single-string prompt that treated all taste dimensions equally and excluded Temperature entirely. The new engine reasons in four stages — vibe axes, genre selection, channel architecture, per-channel rendering — producing prompts with sufficient specificity for Suno V4 to construct coherent multi-layer arrangements that genuinely reflect the chemical character of the food being sensed.

The next horizon is closing the latency gap between taste data and audio output entirely. The current architecture generates a prompt and sends it to a cloud-based generation API; the audio response arrives on the timescale of minutes, not frames. **Phase X** envisions replacing this round-trip with real-time local synthesis: the 8 perceived intensity values would map continuously to synthesis parameters — oscillator frequency ratios, filter cutoff frequencies, granular density, spectral tilt, reverb decay time — within a local engine such as SuperCollider or a WebAudio-based custom synthesizer. The audio would then respond to taste data at the same 10 Hz frame rate as the visual output, creating a fully synchronized three-channel synesthetic experience.

The scientific architecture is already designed for this transition. The `intensities` dict produced by `TasteMapper.process_data` and the `FlavorAxes` struct produced by `compute_axes` are normalized, smoothed, interaction-corrected vectors that map cleanly onto any parameter space. The carbonation engine's OSC bundle (`/tastedata/carbonation/*`) already demonstrates the pattern: ψ(CO₂) drives grain density and pitch; ΔCO₂ drives particle speed. Extending this pattern to cover all 8 dimensions with local synthesis would require changes only to `src/bridge.py` and the downstream patch — the psychophysical core remains untouched.

---

## 7. References

Breslin, P. A. S., & Beauchamp, G. K. (1997). Salt enhances flavour by suppressing bitterness. *Nature*, *387*(6633), 563. https://doi.org/10.1038/42388

Caterina, M. J., Schumacher, M. A., Tominaga, M., Rosen, T. A., Levine, J. D., & Julius, D. (1997). The capsaicin receptor: A heat-activated ion channel in the pain pathway. *Nature*, *389*(6653), 816–824. https://doi.org/10.1038/39807

McBurney, D. H. (1969). Effects of adaptation on human taste function. In C. Pfaffmann (Ed.), *Olfaction and Taste III* (pp. 407–419). Rockefeller University Press.

Stevens, S. S. (1957). On the psychophysical law. *Psychological Review*, *64*(3), 153–181. https://doi.org/10.1037/h0046162

---

*TasteData is developed as coursework for IF201 at Sabancı University. All scientific constants and calibration values reflect published psychophysical literature and are stored externally in `config/settings.yaml` to support ongoing empirical refinement.*
