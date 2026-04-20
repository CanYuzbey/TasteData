/*
 * ============================================================================
 * TasteData Sensor Node — Firmware v1.0
 * Sabancı University IF201
 * ============================================================================
 *
 * Reads eight chemical / physical taste dimensions from analog sensor inputs
 * and transmits one CSV line per 100 ms (10 Hz) over USB-Serial:
 *
 *   ph,temp,brix,shu,co2,ibu,salt,glutamate
 *
 * This schema is consumed directly by src/sensors.py → src/brain.py.
 * All values are floating-point numbers in their native physical units.
 *
 * HARDWARE WIRING SUMMARY
 * ───────────────────────
 *   A0  pH electrode          (e.g. DFRobot SEN0161 analog pH circuit)
 *   A1  Temperature sensor    (e.g. LM35: 10 mV / °C)
 *   A2  Brix refractometer    (analog output circuit: 0–5 V = 0–20 °Bx)
 *   A3  Capsaicin / SHU       (custom biosensor or log-scale converter)
 *   A4  Dissolved CO₂         (e.g. MG-811 CO₂ module)
 *   A5  Bitterness / IBU      (e.g. OPT101 absorbance at 275 nm)
 *   A6  Saltiness / NaCl      (TDS conductivity probe, NaCl-calibrated)
 *   A7  Umami / L-glutamate   (enzymatic biosensor)
 *
 * STARTUP HANDSHAKE
 * ─────────────────
 * On power-on the node prints a machine-readable banner before streaming data.
 * The Python SensorReader detects the "TASTEDATA_NODE" prefix and logs a
 * hardware-confirmed connection. The CSV parser silently skips any non-numeric
 * line, so the banner is safe on all firmware versions.
 *
 * SIMULATE MODE
 * ─────────────
 * Set SIMULATE = true to generate Synthetic Flavor Waves entirely in firmware.
 * This lets you run and validate the full Python pipeline without any sensors
 * connected. Each dimension follows an independent sine oscillator so the
 * output exercises all pipeline stages: Stevens's Law, EMA smoothing, perceptual
 * interaction rules, visual mapping, and audio prompt generation.
 *
 * ============================================================================
 */

#include <math.h>

// ── Mode flag ────────────────────────────────────────────────────────────────
// false → read from physical sensors (A0–A7)
// true  → generate Synthetic Flavor Waves internally
const bool SIMULATE = true;

// ── Serial / timing ──────────────────────────────────────────────────────────
#define BAUD_RATE           9600
#define SAMPLE_INTERVAL_MS  100     // 10 Hz — matches run_app.py POLL_INTERVAL_SEC

// ── Pin assignments ───────────────────────────────────────────────────────────
#define PIN_PH       A0
#define PIN_TEMP     A1
#define PIN_BRIX     A2
#define PIN_SHU      A3
#define PIN_CO2      A4
#define PIN_IBU      A5
#define PIN_SALT     A6
#define PIN_UMAMI    A7
#define PIN_LED      13             // Built-in LED used by startup blink sequence


// ============================================================================
// CALIBRATION CONSTANTS
// ============================================================================
//
// Each sensor maps a raw ADC value [0–1023] to a real physical unit.
//
//   RAW_MIN / RAW_MAX  — ADC readings observed at the physical unit extremes.
//                        Measure these with a calibrated reference solution.
//   UNIT_MIN / UNIT_MAX — Corresponding real-world values in physical units.
//                        Must match the normalization bounds in settings.yaml.
//
// CALIBRATION PROCEDURE (repeat for every sensor channel):
//   1. Prepare a reference solution at UNIT_MIN (e.g. pH 2.5 buffer).
//   2. Open the Arduino Serial Monitor.
//   3. Temporarily add: Serial.println(analogRead(PIN_XX));  to loop().
//   4. Record the printed value → set as RAW_MIN.
//   5. Switch to the UNIT_MAX reference → record → set as RAW_MAX.
//   6. Remove the debug print and upload the final sketch.
//
// ─────────────────────────────────────────────────────────────────────────────

// pH  (DFRobot SEN0161 or equivalent analog pH circuit)
// Most pH op-amp circuits are inverting: lower pH → higher output voltage.
// Calibrate with pH 4.01 and pH 6.86 standard buffer solutions,
// then extrapolate to the project range [2.5, 5.0].
const int   PH_RAW_MIN  = 737;     // ADC at pH 2.5 (most acidic in project range)
const int   PH_RAW_MAX  = 614;     // ADC at pH 5.0 (least acidic in project range)
const float PH_UNIT_MIN = 2.5;     // pH units  — matches settings.yaml ph.min
const float PH_UNIT_MAX = 5.0;     // pH units  — matches settings.yaml ph.max
// Note: RAW_MIN > RAW_MAX because the circuit inverts (high acid → high voltage).

// Temperature  (LM35: Vout = 10 mV × T_celsius, referenced to GND)
// 0 °C  →  0.000 V  →  ADC ≈ 0
// 80 °C →  0.800 V  →  ADC = (0.800 / 5.0) × 1023 ≈ 164
const int   TEMP_RAW_MIN  = 0;
const int   TEMP_RAW_MAX  = 164;
const float TEMP_UNIT_MIN = 0.0;   // °C  — settings.yaml temp.min
const float TEMP_UNIT_MAX = 80.0;  // °C  — settings.yaml temp.max

// Brix  (analog refractometer output circuit: 0–5 V = 0–20 °Brix)
const int   BRIX_RAW_MIN  = 0;
const int   BRIX_RAW_MAX  = 1023;
const float BRIX_UNIT_MIN = 0.0;   // °Brix  — settings.yaml brix.min
const float BRIX_UNIT_MAX = 20.0;  // °Brix  — settings.yaml brix.max

// Spiciness / Capsaicin  (custom biosensor; ideally log-corrected post-calibration)
// Replace with a characterised logarithmic mapping once sensor response is known.
const int   SHU_RAW_MIN  = 0;
const int   SHU_RAW_MAX  = 1023;
const float SHU_UNIT_MIN = 0.0;        // SHU  — settings.yaml shu.min
const float SHU_UNIT_MAX = 50000.0;    // SHU  — settings.yaml shu.max

// Dissolved CO₂  (MG-811 or equivalent; check module datasheet for voltage offset)
const int   CO2_RAW_MIN  = 0;
const int   CO2_RAW_MAX  = 1023;
const float CO2_UNIT_MIN = 0.0;    // volumes CO₂  — settings.yaml co2.min
const float CO2_UNIT_MAX = 5.0;    // volumes CO₂  — settings.yaml co2.max

// Bitterness / IBU  (OPT101 or TSL2591 measuring UV absorbance at ~275 nm)
// Calibrate upper end with a commercial beer of known IBU as reference.
const int   IBU_RAW_MIN  = 0;
const int   IBU_RAW_MAX  = 1023;
const float IBU_UNIT_MIN = 0.0;    // IBU  — settings.yaml ibu.min
const float IBU_UNIT_MAX = 100.0;  // IBU  — settings.yaml ibu.max

// Saltiness / NaCl  (TDS conductivity probe, calibrated with NaCl solutions)
// Prepare 0 g/L (distilled water) and 10 g/L NaCl reference solutions.
const int   SALT_RAW_MIN  = 0;
const int   SALT_RAW_MAX  = 1023;
const float SALT_UNIT_MIN = 0.0;   // g/L NaCl  — settings.yaml salt.min
const float SALT_UNIT_MAX = 10.0;  // g/L NaCl  — settings.yaml salt.max

// Umami / L-glutamate  (enzymatic biosensor; arbitrary 0–20 unit scale)
const int   UMAMI_RAW_MIN  = 0;
const int   UMAMI_RAW_MAX  = 1023;
const float UMAMI_UNIT_MIN = 0.0;  // glutamate units  — settings.yaml glutamate.min
const float UMAMI_UNIT_MAX = 20.0; // glutamate units  — settings.yaml glutamate.max


// ============================================================================
// SIMULATION PARAMETERS — Synthetic Flavor Waves
// ============================================================================
//
// Each dimension oscillates as a sine wave centered on a realistic baseline
// value, with an amplitude that keeps the output well within the sensor range.
//
// Oscillation periods are chosen to be mutually irrational (no two share a
// common divisor), so the 8-dimensional signal never exactly repeats.
// This ensures the Python EMA, interaction rules, and audio prompt generator
// are all exercised across a rich variety of flavor states.
//
// SHU uses a signed-squared sine (x·|x|) to generate sharp, brief spiciness
// spikes rather than smooth sinusoidal swells — modeling the experience of
// capsaicin appearing suddenly rather than fading in gradually.
//
// ─────────────────────────────────────────────────────────────────────────────

//                          Center          Amplitude       Resulting range
const float SIM_PH_BASE    = 3.80;  const float SIM_PH_AMP    = 1.15;  // pH  2.65 – 4.95
const float SIM_TEMP_BASE  = 35.0;  const float SIM_TEMP_AMP  = 29.0;  // °C  6.0  – 64.0
const float SIM_BRIX_BASE  = 7.0;   const float SIM_BRIX_AMP  = 6.5;   // Bx  0.5  – 13.5
const float SIM_SHU_BASE   = 4500;  const float SIM_SHU_AMP   = 4400;  // SHU 100  – 8900
const float SIM_CO2_BASE   = 2.0;   const float SIM_CO2_AMP   = 1.8;   // vol 0.2  – 3.8
const float SIM_IBU_BASE   = 25.0;  const float SIM_IBU_AMP   = 23.5;  // IBU 1.5  – 48.5
const float SIM_SALT_BASE  = 2.5;   const float SIM_SALT_AMP  = 2.3;   // g/L 0.2  – 4.8
const float SIM_UMAMI_BASE = 5.0;   const float SIM_UMAMI_AMP = 4.7;   // gu  0.3  – 9.7

// Oscillation periods in seconds (all mutually irrational)
const float SIM_PH_PERIOD    = 17.3;
const float SIM_TEMP_PERIOD  = 41.0;
const float SIM_BRIX_PERIOD  = 23.7;
const float SIM_SHU_PERIOD   = 11.9;
const float SIM_CO2_PERIOD   = 29.1;
const float SIM_IBU_PERIOD   = 37.3;
const float SIM_SALT_PERIOD  = 13.1;
const float SIM_UMAMI_PERIOD = 53.7;

// Phase offsets (radians) so sensors start at varied points in their cycles,
// avoiding an artificial 'all sensors at baseline' initial state.
const float SIM_PH_PHASE    = 0.00;
const float SIM_TEMP_PHASE  = 1.10;
const float SIM_BRIX_PHASE  = 2.30;
const float SIM_SHU_PHASE   = 0.70;
const float SIM_CO2_PHASE   = 3.50;
const float SIM_IBU_PHASE   = 5.10;
const float SIM_SALT_PHASE  = 1.90;
const float SIM_UMAMI_PHASE = 4.40;


// ── State ────────────────────────────────────────────────────────────────────
unsigned long lastSampleMs = 0;


// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

// Linear interpolation of x from [inMin, inMax] to [outMin, outMax].
// Arduino's built-in map() is integer-only; this version handles floats.
float mapFloat(float x, float inMin, float inMax, float outMin, float outMax) {
    if (inMax == inMin) return outMin;
    return (x - inMin) / (inMax - inMin) * (outMax - outMin) + outMin;
}

float clampFloat(float x, float lo, float hi) {
    if (x < lo) return lo;
    if (x > hi) return hi;
    return x;
}

// Standard sine oscillator returning a value in [base - amp, base + amp].
float sineWave(float tSec, float period, float base, float amp, float phaseRad) {
    return base + amp * sin(TWO_PI * tSec / period + phaseRad);
}

// Signed-squared sine: produces sharp spikes rather than smooth oscillations.
// Output range is the same as sineWave but energy is concentrated at the peaks.
float spikeSine(float tSec, float period, float base, float amp, float phaseRad) {
    float s = sin(TWO_PI * tSec / period + phaseRad);
    return base + amp * s * fabs(s);
}


// ============================================================================
// SERIAL OUTPUT
// ============================================================================
//
// Transmits exactly one CSV line per call.
// Field order: ph,temp,brix,shu,co2,ibu,salt,glutamate
// This is the schema expected by src/sensors.py.
//
void transmitFrame(float ph,   float temp, float brix, float shu,
                   float co2,  float ibu,  float salt,  float umami) {
    // Decimal precision is chosen per-channel to balance resolution against
    // line length. At 9600 baud, a 60-character line transmits in ~6 ms,
    // well within the 100 ms sampling window.
    Serial.print(ph,    3);  Serial.print(',');
    Serial.print(temp,  2);  Serial.print(',');
    Serial.print(brix,  3);  Serial.print(',');
    Serial.print(shu,   1);  Serial.print(',');
    Serial.print(co2,   3);  Serial.print(',');
    Serial.print(ibu,   2);  Serial.print(',');
    Serial.print(salt,  3);  Serial.print(',');
    Serial.print(umami, 3);  Serial.println();
}


// ============================================================================
// HARDWARE READ PATH
// ============================================================================
//
// Each function performs one analogRead, applies the linear calibration map,
// and clamps the result to the valid physical range.
//

float readPH() {
    return clampFloat(
        mapFloat(analogRead(PIN_PH), PH_RAW_MIN, PH_RAW_MAX, PH_UNIT_MIN, PH_UNIT_MAX),
        PH_UNIT_MIN, PH_UNIT_MAX);
}

float readTemp() {
    return clampFloat(
        mapFloat(analogRead(PIN_TEMP), TEMP_RAW_MIN, TEMP_RAW_MAX, TEMP_UNIT_MIN, TEMP_UNIT_MAX),
        TEMP_UNIT_MIN, TEMP_UNIT_MAX);
}

float readBrix() {
    return clampFloat(
        mapFloat(analogRead(PIN_BRIX), BRIX_RAW_MIN, BRIX_RAW_MAX, BRIX_UNIT_MIN, BRIX_UNIT_MAX),
        BRIX_UNIT_MIN, BRIX_UNIT_MAX);
}

float readSHU() {
    return clampFloat(
        mapFloat(analogRead(PIN_SHU), SHU_RAW_MIN, SHU_RAW_MAX, SHU_UNIT_MIN, SHU_UNIT_MAX),
        SHU_UNIT_MIN, SHU_UNIT_MAX);
}

float readCO2() {
    return clampFloat(
        mapFloat(analogRead(PIN_CO2), CO2_RAW_MIN, CO2_RAW_MAX, CO2_UNIT_MIN, CO2_UNIT_MAX),
        CO2_UNIT_MIN, CO2_UNIT_MAX);
}

float readIBU() {
    return clampFloat(
        mapFloat(analogRead(PIN_IBU), IBU_RAW_MIN, IBU_RAW_MAX, IBU_UNIT_MIN, IBU_UNIT_MAX),
        IBU_UNIT_MIN, IBU_UNIT_MAX);
}

float readSalt() {
    return clampFloat(
        mapFloat(analogRead(PIN_SALT), SALT_RAW_MIN, SALT_RAW_MAX, SALT_UNIT_MIN, SALT_UNIT_MAX),
        SALT_UNIT_MIN, SALT_UNIT_MAX);
}

float readUmami() {
    return clampFloat(
        mapFloat(analogRead(PIN_UMAMI), UMAMI_RAW_MIN, UMAMI_RAW_MAX, UMAMI_UNIT_MIN, UMAMI_UNIT_MAX),
        UMAMI_UNIT_MIN, UMAMI_UNIT_MAX);
}

void transmitHardware() {
    transmitFrame(
        readPH(), readTemp(), readBrix(), readSHU(),
        readCO2(), readIBU(), readSalt(), readUmami()
    );
}


// ============================================================================
// SIMULATION PATH — Synthetic Flavor Waves
// ============================================================================
//
// Generates physically plausible sensor values using overlapping sine waves.
// Designed to exercise all Python pipeline stages without physical hardware.
//
// Flavor events guaranteed to occur during a typical 60-second run:
//   - High Sourness:    pH dips below 3.0 (normalized > 0.80)
//   - High Sweetness:  Brix rises above 10 (normalized > 0.50)
//   - Salt suppression: Salt > ~3 g/L while IBU is elevated — fires the
//                       Bitterness suppression rule in brain.py
//   - Spicy spike:     SHU pulse via spikeSine exercises the EMA step response
//   - Heat boost:      Temp > 60 °C while SHU is nonzero — fires the TRPV1 rule
//
void transmitSimulated(float tSec) {
    float ph    = clampFloat(sineWave  (tSec, SIM_PH_PERIOD,    SIM_PH_BASE,    SIM_PH_AMP,    SIM_PH_PHASE),
                             PH_UNIT_MIN,    PH_UNIT_MAX);
    float temp  = clampFloat(sineWave  (tSec, SIM_TEMP_PERIOD,  SIM_TEMP_BASE,  SIM_TEMP_AMP,  SIM_TEMP_PHASE),
                             TEMP_UNIT_MIN,  TEMP_UNIT_MAX);
    float brix  = clampFloat(sineWave  (tSec, SIM_BRIX_PERIOD,  SIM_BRIX_BASE,  SIM_BRIX_AMP,  SIM_BRIX_PHASE),
                             BRIX_UNIT_MIN,  BRIX_UNIT_MAX);
    float shu   = clampFloat(spikeSine (tSec, SIM_SHU_PERIOD,   SIM_SHU_BASE,   SIM_SHU_AMP,   SIM_SHU_PHASE),
                             SHU_UNIT_MIN,   SHU_UNIT_MAX);
    float co2   = clampFloat(sineWave  (tSec, SIM_CO2_PERIOD,   SIM_CO2_BASE,   SIM_CO2_AMP,   SIM_CO2_PHASE),
                             CO2_UNIT_MIN,   CO2_UNIT_MAX);
    float ibu   = clampFloat(sineWave  (tSec, SIM_IBU_PERIOD,   SIM_IBU_BASE,   SIM_IBU_AMP,   SIM_IBU_PHASE),
                             IBU_UNIT_MIN,   IBU_UNIT_MAX);
    float salt  = clampFloat(sineWave  (tSec, SIM_SALT_PERIOD,  SIM_SALT_BASE,  SIM_SALT_AMP,  SIM_SALT_PHASE),
                             SALT_UNIT_MIN,  SALT_UNIT_MAX);
    float umami = clampFloat(sineWave  (tSec, SIM_UMAMI_PERIOD, SIM_UMAMI_BASE, SIM_UMAMI_AMP, SIM_UMAMI_PHASE),
                             UMAMI_UNIT_MIN, UMAMI_UNIT_MAX);

    transmitFrame(ph, temp, brix, shu, co2, ibu, salt, umami);
}


// ============================================================================
// STARTUP SEQUENCE
// ============================================================================
//
// Executed once on power-on. Confirms firmware identity over Serial and blinks
// the built-in LED so the user can verify the board is alive before connecting
// the Python host.
//
// The Python SensorReader detects the "TASTEDATA_NODE" prefix in the banner
// and records a hardware-confirmed handshake in the session log. Any line that
// cannot be parsed as 8 comma-separated floats is silently discarded, so the
// banner does not corrupt the data stream on older host builds.
//
void startupSequence() {
    // Three LED blinks — visual confirmation that setup() has been reached.
    for (int i = 0; i < 3; i++) {
        digitalWrite(PIN_LED, HIGH);  delay(150);
        digitalWrite(PIN_LED, LOW);   delay(150);
    }

    // Machine-readable handshake header.
    // The Python host scans for the "TASTEDATA_NODE" prefix.
    Serial.println(F("=== TASTEDATA_NODE_v1.0 READY ==="));
    Serial.print  (F("Mode   : "));
    Serial.println(SIMULATE ? F("SIMULATE") : F("HARDWARE"));
    Serial.print  (F("Rate   : "));
    Serial.print  (1000 / SAMPLE_INTERVAL_MS);
    Serial.println(F(" Hz"));
    Serial.println(F("Schema : ph,temp,brix,shu,co2,ibu,salt,glutamate"));
    Serial.println(F("--- BEGIN DATA STREAM ---"));

    // Brief pause so the Python host has time to detect the banner before
    // the first data line arrives. Without this, fast USB enumeration can
    // cause the banner to be missed on initial connect.
    delay(500);
}


// ============================================================================
// ARDUINO ENTRY POINTS
// ============================================================================

void setup() {
    pinMode(PIN_LED, OUTPUT);

    Serial.begin(BAUD_RATE);

    // Wait for USB-CDC serial port enumeration.
    // Required on boards with native USB (Leonardo, Micro, Zero, MKR series).
    // On Uno / Mega (UART-over-USB via separate chip), this resolves instantly.
    while (!Serial) { ; }

    startupSequence();
    lastSampleMs = millis();
}

void loop() {
    unsigned long now = millis();

    // Non-blocking interval guard — keeps loop() free for future expansions
    // (e.g. reading a push-button to trigger a snapshot command).
    if (now - lastSampleMs < SAMPLE_INTERVAL_MS) return;
    lastSampleMs = now;

    if (SIMULATE) {
        transmitSimulated(now / 1000.0f);
    } else {
        transmitHardware();
    }
}
