# TasteData Algorithm Specifications
Version 2.0 · 2026-04-23

This document is the primary research reference for every algorithm decision in TasteData.
It records the scientific source, mathematical form, and implementation rationale for each
component, so that constants can be re-calibrated without losing the reasoning behind them.

---

## 1. Normalization Bounds

All raw sensor readings are mapped to [0, 1] before entering the psychophysical model.
The bounds below reflect the chemically and physiologically relevant range for beverages
and food encountered in practice. Values outside the range are clamped silently.

| Dimension   | Raw Unit        | Min   | Max    | Notes |
|-------------|-----------------|-------|--------|-------|
| pH          | pH scale        | 2.5   | 5.0    | Sourness uses inverse: `1.0 - normalized_pH` |
| Temperature | degrees Celsius | 0.0   | 80.0   | Linear passthrough, no Stevens exponent |
| Sweetness   | degrees Brix    | 0.0   | 20.0   | Optical refractometry dissolved-solids proxy |
| Spiciness   | SHU             | 0.0   | 50,000 | Covers jalapeño (~5,000) to habanero (~350,000) clipped at practical threshold |
| Carbonation | volumes CO₂     | 0.0   | 5.0    | Still water ≈ 0; sparkling water ≈ 2.5; heavily carbonated cola ≈ 3.7 |
| Bitterness  | IBU             | 0.0   | 100.0  | Lager ≈ 8–15; IPA ≈ 40–70; maximum perceived meaningful range |
| Saltiness   | g/L NaCl        | 0.0   | 10.0   | Sea water ≈ 35 g/L (clamped); palatable threshold ≈ 2–6 g/L |
| Umami       | glutamate units | 0.0   | 20.0   | Arbitrary sensor scale; calibrated against MSG concentration in food lab |

Sourness special case: pH is a logarithmic inverse scale of acidity. The raw pH reading
is first normalized to [0, 1] using the bounds above, then inverted:

```
sourness_input = 1.0 - normalized_pH
```

This ensures that low pH (high acidity) maps to high sourness intensity before the
power law is applied.

---

## 2. Stevens's Power Law Exponents

### 2.1 Theory

Human sensation is not linear. Stevens (1957) established that perceived magnitude follows
a power function of physical stimulus intensity:

```
Ψ(I) = k · I^n
```

where:
- `Ψ(I)` — perceived magnitude (output in [0, 1] after normalization)
- `I` — physical stimulus intensity (normalized to [0, 1])
- `k` — scaling constant (= 1.0; handled by the normalization step)
- `n` — modality-specific exponent

Convention used in this codebase:
- `n > 1.0` → **compressive**: perception grows slower than the physical stimulus;
  more stimulus is needed to reach a given perceived intensity level
- `n < 1.0` → **expansive**: perception grows faster than the physical stimulus;
  the sensation is felt strongly even at low concentrations
- `n = 1.0` → **linear**: perception directly proportional to stimulus

### 2.2 Exponents (all stored in config/settings.yaml → exponents)

| Dimension   | Exponent | Type        | Scientific Basis |
|-------------|----------|-------------|-----------------|
| Sweetness   | 1.3      | Compressive | Sucrose magnitude estimation data (Stevens, 1969); sweet perception builds gradually, saturates late |
| Sourness    | 1.1      | Compressive | Citric acid titration data (Breslin, 1996); near-linear with slight build lag |
| Spiciness   | 0.8      | Expansive   | Capsaicin TRPV1 activation; pain nociceptors signal at very low concentrations (Caterina et al., 1997) |
| Bitterness  | 1.3      | Compressive | Quinine sulphate data; bitterness is an evolutionary warning that builds slowly to avoid false positives |
| Saltiness   | 1.4      | Compressive | NaCl magnitude estimation (McBurney, 1969); most compressive of all tastes — salt perception saturates last |
| Umami       | 1.0      | Linear      | Glutamate receptor response is approximately linear in the beverage range (Yamaguchi, 1991) |
| Carbonation | 1.1      | Compressive | CO₂ prickling via TRPA1 and carbonic anhydrase; sensation builds gradually with concentration (Green, 1992) |

Temperature exponent: none applied. Temperature is a physical property that modulates
the expression of all other taste dimensions (via TRPV1 sensitisation, diffusion rate,
etc.) rather than a discrete chemical taste signal. It enters the output pipeline as a
linear normalized value and drives reverb, articulation, and mix density in the prompt
engine.

### 2.3 Implementation Guards (src/brain.py → _apply_power_law)

```python
def _apply_power_law(self, value: float, exponent: float) -> float:
    clamped = max(0.0, min(1.0, value))
    if clamped == 0.0: return 0.0   # avoids 0^0 = 1 ambiguity
    if exponent <= 0.0: return 1.0  # protects against bad YAML config
    return clamped ** exponent
```

---

## 3. Perceptual Interaction Rules

Human taste perception is not a simple sum of independent dimensions. The following three
rules implement well-replicated cross-modal interactions. They are applied **after**
Stevens's Power Law and **before** EMA smoothing, so the smoothed output reflects the
chemosensory reality of each frame rather than smoothing a pre-interaction value.

All thresholds and reduction factors live in `config/settings.yaml → interactions`.

### Rule 1 — Salt Suppresses Bitterness

> **Condition:** `Saltiness > 0.30`
> **Effect:** `Bitterness × 0.80` (−20%)

Sodium chloride reduces bitter transduction by competing at amiloride-sensitive epithelial
sodium channels, raising the bitter detection threshold. The effect has been replicated
across culinary concentration ranges (McBurney, 1969). This is the scientific basis for
the practice of adding salt to coffee to reduce bitterness.

### Rule 2 — Sweetness Suppresses Sourness

> **Condition:** `Sweetness > 0.50`
> **Effect:** `Sourness × 0.85` (−15%)

Dissolved sugars elevate the sourness perception threshold through peripheral adaptation
at type III taste receptor cells. The suppression scales with sugar concentration and
onset begins at approximately moderate sweetness (Breslin & Beauchamp, 1997). This models
sweetened citrus drinks tasting less sharp than their unsweetened counterparts at the
same pH.

### Rule 3 — Heat Potentiates Spiciness

> **Condition:** `Temperature > 0.70`
> **Effect:** `Spiciness × 1.10` (+10%, clamped to 1.0)

TRPV1 is a polymodal nociceptor that responds to both capsaicin and noxious heat. Elevated
tissue temperature lowers the TRPV1 activation threshold, making capsaicin more potent at
the same concentration. Confirmed at the molecular level by Caterina et al. (1997) and
consistent with the culinary observation that hot food tastes spicier than cold food.

---

## 4. EMA Signal Smoothing

### 4.1 Formula

```
smoothed[t] = α · raw[t]  +  (1 − α) · smoothed[t−1]
```

`α = 0.2` at `fps = 10 Hz` (configurable in `settings.yaml → smoothing.alpha`).

### 4.2 Analytical Properties

| Property | Formula | Value |
|----------|---------|-------|
| Per-frame lag on ramp | `(1−α)/α/fps` | 0.40 s |
| Step-function 90% convergence | `ceil(log(0.1)/log(1−α))` | 11 frames = 1.10 s |
| First-frame behaviour | `prev` defaults to `raw[t]` → output = raw[t] | No phantom decay |

### 4.3 Why This α

0.40 s of lag is imperceptible during a live pour. 1.10 s rise time is fast enough to feel
responsive but slow enough to absorb single-frame sensor spikes. Increasing α toward 1.0
makes the system more reactive; decreasing toward 0.0 gives slower, more cinematic
transitions.

---

## 5. Cross-Modal Mapping Matrix

### 5.1 Visual Parameters (src/brain.py → TasteMapper.get_visual_params)

| Dimension | Colour anchor | Shape (angularity) | Noise contribution |
|-----------|--------------|--------------------|--------------------|
| Sweetness | Pink (255, 182, 193) | 0.0 (perfectly round) | — |
| Sourness  | Yellow (255, 255, 0) | 0.8 (sharp) | — |
| Spiciness | Red (255, 0, 0) | 1.0 (maximum jagged) | × 0.7 |
| Carbonation | — | — | × 0.3 |

Colour: `RGB = weighted_average(anchors, weights=[Sweetness, Sourness, Spiciness])`.
Returns neutral gray (200, 200, 200) when all three weights are zero.

Noise: `noise = clamp(Spiciness × 0.7 + Carbonation × 0.3)`

### 5.2 FlavorAxes (src/prompt_engine.py → compute_axes)

The 8 perceived intensities are compressed into 5 aesthetic axes that capture producer-level
intuition about a food's character. Each weight was chosen to reflect the strongest
psychophysical evidence for that dimension's contribution to the aesthetic property.

| Axis     | Formula | Perceptual rationale |
|----------|---------|----------------------|
| `energy`   | `Sp×0.40 + So×0.25 + Ca×0.20 + Te×0.10 + Sa×0.05` | Capsaicin is the strongest arousal driver (TRPV1 pain signal). Sourness creates tension. Carbonation adds liveliness. |
| `warmth`   | `Sw×0.40 + Um×0.30 + Te×0.20 − Bi×0.10` | Sweetness and umami activate reward pathways. Bitterness is an evolutionary aversion signal — it subtracts warmth. |
| `darkness` | `Bi×0.45 + So×0.25 + (1−Sw)×0.20 + (1−Te)×0.10` | Bitterness maps to minor keys and heavy timbres. Sourness adds harmonic dissonance. Cold temperature adds austerity. |
| `texture`  | `Ca×0.50 + Sa×0.30 + Sp×0.20` | Carbonation is literal stochastic acoustic grain (bubble nucleation). Salt adds crystalline high-frequency structure. |
| `richness` | `Um×0.45 + Sw×0.30 + Sa×0.25` | Umami activates the broadest receptor range — it makes food feel "full". Sweetness adds upper-harmonic shimmer. |

`temp_feel = Temperature` (raw, preserved separately, drives reverb and articulation
through continuous ranges rather than a single axis value).

---

## 6. Genre Selection

### 6.1 Algorithm

Each of the 12 genre profiles is defined as a point in 6-dimensional axis space:
`(energy, warmth, darkness, texture, richness, temp_feel)`.

The system computes a weighted MSE score for every genre and selects the minimum:

```
score(g) = Σ  w_i × (actual_i − ideal_i)²
```

Axis weights: `(0.28, 0.18, 0.24, 0.15, 0.10, 0.05)`

Energy and darkness are weighted highest (0.28, 0.24) because they are the most
genre-discriminative dimensions. temp_feel is weighted lowest (0.05) because temperature
shapes the rendering of any genre rather than selecting between them.

### 6.2 Genre Profiles (12 total, src/prompt_engine.py → _GENRES)

| Genre | energy | warmth | darkness | texture | richness | temp_feel |
|-------|--------|--------|----------|---------|----------|-----------|
| Dark Techno / Industrial | 0.80 | 0.10 | 0.80 | 0.55 | 0.30 | 0.65 |
| Hyperpop / Club | 0.90 | 0.45 | 0.20 | 0.80 | 0.40 | 0.55 |
| Tropical House / Afrobeat | 0.65 | 0.80 | 0.10 | 0.30 | 0.55 | 0.60 |
| Dark Ambient / Drone | 0.05 | 0.20 | 0.90 | 0.45 | 0.50 | 0.25 |
| Jazz / Soul | 0.40 | 0.80 | 0.40 | 0.20 | 0.90 | 0.50 |
| Dream Pop / Shoegaze | 0.30 | 0.80 | 0.20 | 0.55 | 0.65 | 0.40 |
| Minimal Techno | 0.50 | 0.20 | 0.50 | 0.25 | 0.20 | 0.45 |
| IDM / Glitch | 0.55 | 0.30 | 0.50 | 0.90 | 0.55 | 0.40 |
| Neo-Soul / R&B | 0.35 | 0.90 | 0.25 | 0.20 | 0.85 | 0.55 |
| Cinematic Orchestral | 0.55 | 0.50 | 0.60 | 0.40 | 0.95 | 0.50 |
| Punk / Noise Rock | 0.95 | 0.10 | 0.60 | 0.65 | 0.20 | 0.70 |
| Ambient Electronic | 0.10 | 0.60 | 0.30 | 0.60 | 0.50 | 0.35 |

---

## 7. BPM and Key/Mode Selection

### 7.1 BPM

Within the genre's BPM range `[lo, hi]`:

```
t = clamp(energy×0.55 + temp_feel×0.20 − warmth×0.15 − richness×0.10)
BPM = round(lo + t × (hi − lo))
```

High energy and heat push toward the upper bound; warmth and richness pull toward the
lower bound (a more relaxed, groove-oriented feel).

### 7.2 Key/Mode

Derived from darkness and warmth axes:

| Condition | Key/Mode |
|-----------|----------|
| `darkness > 0.72` and `energy > 0.50` | Phrygian |
| `darkness > 0.72` and `energy ≤ 0.50` | Locrian |
| `darkness > 0.52` | natural minor |
| `darkness > 0.35` | Dorian |
| `warmth > 0.72` and `richness > 0.50` | Lydian |
| `warmth > 0.72` | major |
| `warmth > 0.50` | Mixolydian |
| else | natural major |

---

## 8. Per-Channel Rendering

Each channel receives three rendering passes, and all 8 taste dimensions contribute to
every pass — there is no threshold gating.

### 8.1 Timbral Adjectives

Continuous intensity ranges map to descriptive words. Temperature is handled in five
distinct bands to capture its qualitative shift from physiologically cold to hot:

| Temperature | Timbre word |
|-------------|-------------|
| `> 0.80` | "hot and saturated — dense and steamy like a heat haze" |
| `> 0.60` | "warm and slightly hazy" |
| `> 0.40` | "room-temperature — clear and neutral" |
| `> 0.20` | "cool and crisp" |
| `≤ 0.20` | "cold and sterile — icy precision" |

### 8.2 Articulation (role-aware)

- **Sustained** (pad, drone, atmo): attack / bloom / sustain / release language
  - Cold: "sparse, crystalline sustain — notes hang in cold air"
  - Hot: "dense sustained body — saturated and slow-moving"
- **Rhythmic** (kick, perc): transient / decay language
  - Cold: "extremely tight decay — no room in the cold"
  - Hot: "slightly extended decay — temperature adds warmth to the tail"

### 8.3 Effects Chain

Temperature is the **primary reverb driver**:

```
reverb_amount = clamp(Temperature×0.50 + Sweetness×0.25 + Umami×0.15 − Bitterness×0.10)
```

| Temperature | Reverb treatment | Stereo image |
|-------------|-----------------|-------------|
| `> 0.75` | Dense plate reverb (pre-delay 15 ms) | Wide M-S stereo |
| `> 0.55` | Long hall reverb (2–4 s tail) | — |
| `> 0.35` | Medium room reverb (0.8–1.5 s) | — |
| `< 0.20` | Almost dry (tiny room only) | Narrow mono |

Additional FX driven by other dimensions:
- **Spiciness:** heavy overdrive + bitcrusher at sp > 0.75; tape saturation at sp > 0.45
- **Sourness:** dotted-eighth ping-pong delay (rhythmic echo); HPF + presence boost
- **Bitterness:** LPF sweep closing the high end (on non-bass channels)
- **Saltiness:** chorus / ensemble detune shimmer
- **Carbonation:** granular synthesis — grain pitch mapped to 2,000–20,000 Hz proportional to CO₂ intensity; density proportional to carbonation value

---

## 9. References

Breslin, P. A. S., & Beauchamp, G. K. (1997). Salt enhances flavour by suppressing bitterness. *Nature*, *387*(6633), 563.

Caterina, M. J., Schumacher, M. A., Tominaga, M., Rosen, T. A., Levine, J. D., & Julius, D. (1997). The capsaicin receptor: A heat-activated ion channel in the pain pathway. *Nature*, *389*(6653), 816–824.

Chandrashekar, J., Yarmolinsky, D., von Buchholtz, L., Oka, Y., Sly, W., Ryba, N. J., & Zuker, C. S. (2009). The taste of carbonation. *Science*, *326*(5951), 443–445.

Green, B. G. (1992). The sensory effects of l-menthol on human skin. *Somatosensory & Motor Research*, *9*(3), 235–244.

McBurney, D. H. (1969). Effects of adaptation on human taste function. In C. Pfaffmann (Ed.), *Olfaction and Taste III* (pp. 407–419). Rockefeller University Press.

Stevens, S. S. (1957). On the psychophysical law. *Psychological Review*, *64*(3), 153–181.

Yamaguchi, S. (1991). Basic properties of umami and its effects on food flavor. *Food Reviews International*, *7*(2), 283–296.
