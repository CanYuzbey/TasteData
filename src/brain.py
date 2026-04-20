from datetime import datetime
import json
from pathlib import Path

import yaml

_DEFAULT_SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
_SNAPSHOTS_DIR    = Path(__file__).resolve().parent.parent / "snapshots"


class TasteMapper:
    # Angularity targets (0.0=round, 1.0=star/pointy) — artistic, not in YAML
    _ANGULARITY = {"Sweetness": 0.0, "Sourness": 0.8, "Spiciness": 1.0}

    # Base colors per taste (R, G, B 0-255): Pink, Yellow, Red
    _COLORS = {
        "Sweetness": (255, 182, 193),
        "Sourness":  (255, 255,   0),
        "Spiciness": (255,   0,   0),
    }

    # Research-backed descriptor bundles per taste, structured for Suno V3.5/V4.
    # tag: Suno style tag (empty string = no tag for that dimension).
    _DESCRIPTORS: dict[str, dict[str, str]] = {
        "Sweetness":   {"tag": "[Legato]",                 "texture": "fragile, delicate textures",   "instr": "soft, tinkling piano"},
        "Sourness":    {"tag": "[Sharp Transients]",        "texture": "jagged, shattered transients", "instr": "staccato brass"},
        "Spiciness":   {"tag": "[Fast Tempo]",              "texture": "aggressive, dense energy",     "instr": "industrial bit-crushed synth"},
        "Saltiness":   {"tag": "[Bright Articulation]",    "texture": "crystalline textures",         "instr": "staccato rhythms"},
        "Umami":       {"tag": "[Low Frequency Dominant]", "texture": "meaty, dark resonances",       "instr": "deep bass sustain"},
        "Carbonation": {"tag": "",                          "texture": "bright, tingling grain",       "instr": "crackling harmonics"},
        "Bitterness":  {"tag": "",                          "texture": "robust, dense bass",           "instr": "distorted trombone"},
    }

    # ------------------------------------------------------------------ #

    def __init__(self, settings_path: Path | str | None = None) -> None:
        path = Path(settings_path) if settings_path else _DEFAULT_SETTINGS
        if not path.exists():
            raise FileNotFoundError(
                f"Settings file not found: {path}\n"
                "Run from the project root or pass an explicit settings_path."
            )
        with path.open("r") as fh:
            cfg = yaml.safe_load(fh)

        n = cfg["normalization"]
        self.PH_MIN,        self.PH_MAX        = n["ph"]["min"],        n["ph"]["max"]
        self.TEMP_MIN,      self.TEMP_MAX      = n["temp"]["min"],      n["temp"]["max"]
        self.BRIX_MIN,      self.BRIX_MAX      = n["brix"]["min"],      n["brix"]["max"]
        self.SHU_MIN,       self.SHU_MAX       = n["shu"]["min"],       n["shu"]["max"]
        self.CO2_MIN,       self.CO2_MAX       = n["co2"]["min"],       n["co2"]["max"]
        self.IBU_MIN,       self.IBU_MAX       = n["ibu"]["min"],       n["ibu"]["max"]
        self.SALT_MIN,      self.SALT_MAX      = n["salt"]["min"],      n["salt"]["max"]
        self.GLUTAMATE_MIN, self.GLUTAMATE_MAX = n["glutamate"]["min"], n["glutamate"]["max"]

        e = cfg["exponents"]
        self.EXPONENT_SWEETNESS  = e["sweetness"]
        self.EXPONENT_SPICINESS  = e["spiciness"]
        self.EXPONENT_SOURNESS   = e["sourness"]
        self.EXPONENT_BITTERNESS = e["bitterness"]
        self.EXPONENT_SALTINESS  = e["saltiness"]
        self.EXPONENT_UMAMI      = e["umami"]

        self._AUDIO_THRESHOLD = cfg["audio"]["threshold"]
        self.EMA_ALPHA        = cfg["smoothing"]["alpha"]

        ia = cfg.get("interactions", {})
        self.SALT_BITTER_THRESHOLD = ia.get("salt_bitter_threshold", 0.30)
        self.SALT_BITTER_REDUCTION = ia.get("salt_bitter_reduction", 0.20)
        self.SWEET_SOUR_THRESHOLD  = ia.get("sweet_sour_threshold",  0.50)
        self.SWEET_SOUR_REDUCTION  = ia.get("sweet_sour_reduction",  0.15)
        self.HEAT_SPICY_THRESHOLD  = ia.get("heat_spicy_threshold",  0.70)
        self.HEAT_SPICY_BOOST      = ia.get("heat_spicy_boost",      0.10)

        self._prev_intensities: dict[str, float] = {}

    # ------------------------------------------------------------------ #

    def _apply_power_law(self, value: float, exponent: float) -> float:
        clamped = max(0.0, min(1.0, value))
        if clamped == 0.0:
            return 0.0      # no stimulus → no perception; avoids 0^0 ambiguity
        if exponent <= 0.0:
            return 1.0      # degenerate config guard
        return clamped ** exponent

    def reset_ema(self) -> None:
        """Clear EMA state so the next process_data call starts from a clean baseline."""
        self._prev_intensities = {}

    def _apply_ema(self, raw: dict[str, float]) -> dict[str, float]:
        """Blend each dimension with its previous value via Exponential Moving Average."""
        a = self.EMA_ALPHA
        smoothed = {
            key: a * val + (1.0 - a) * self._prev_intensities.get(key, val)
            for key, val in raw.items()
        }
        self._prev_intensities = smoothed
        return smoothed

    def process_data(
        self,
        raw_ph:     float,
        raw_temp:   float,
        raw_brix:   float,
        raw_spicy:  float,
        raw_co2:    float = 0.0,
        raw_ibu:    float = 0.0,
        raw_salt:   float = 0.0,
        raw_umami:  float = 0.0,
    ) -> dict[str, float]:
        norm_ph       = (raw_ph       - self.PH_MIN)        / (self.PH_MAX        - self.PH_MIN)
        norm_temp     = (raw_temp     - self.TEMP_MIN)      / (self.TEMP_MAX      - self.TEMP_MIN)
        norm_brix     = (raw_brix     - self.BRIX_MIN)      / (self.BRIX_MAX      - self.BRIX_MIN)
        norm_spicy    = (raw_spicy    - self.SHU_MIN)       / (self.SHU_MAX       - self.SHU_MIN)
        norm_co2      = (raw_co2      - self.CO2_MIN)       / (self.CO2_MAX       - self.CO2_MIN)
        norm_ibu      = (raw_ibu      - self.IBU_MIN)       / (self.IBU_MAX       - self.IBU_MIN)
        norm_salt     = (raw_salt     - self.SALT_MIN)      / (self.SALT_MAX      - self.SALT_MIN)
        norm_glutamate= (raw_umami    - self.GLUTAMATE_MIN) / (self.GLUTAMATE_MAX - self.GLUTAMATE_MIN)

        sourness_input = 1.0 - norm_ph  # inverse: lower pH = more sour

        clamp = lambda v: max(0.0, min(1.0, v))
        raw_intensities = {
            "Sourness":    self._apply_power_law(sourness_input, self.EXPONENT_SOURNESS),
            "Sweetness":   self._apply_power_law(norm_brix,       self.EXPONENT_SWEETNESS),
            "Spiciness":   self._apply_power_law(norm_spicy,      self.EXPONENT_SPICINESS),
            "Saltiness":   self._apply_power_law(norm_salt,       self.EXPONENT_SALTINESS),
            "Umami":       self._apply_power_law(norm_glutamate,  self.EXPONENT_UMAMI),
            "Carbonation": clamp(norm_co2),
            "Bitterness":  self._apply_power_law(norm_ibu,        self.EXPONENT_BITTERNESS),
            "Temperature": clamp(norm_temp),
        }

        # -- Perceptual Interaction Rules (after Power Law, before EMA) --
        # Salt suppresses bitterness: NaCl competes with bitter receptors (McBurney 1969)
        if raw_intensities["Saltiness"] > self.SALT_BITTER_THRESHOLD:
            raw_intensities["Bitterness"] *= (1.0 - self.SALT_BITTER_REDUCTION)
        # Sweetness suppresses sourness: sugar masks acid perception (Breslin 1996)
        if raw_intensities["Sweetness"] > self.SWEET_SOUR_THRESHOLD:
            raw_intensities["Sourness"] *= (1.0 - self.SWEET_SOUR_REDUCTION)
        # Heat potentiates capsaicin response via TRPV1 channel sensitization
        if raw_intensities["Temperature"] > self.HEAT_SPICY_THRESHOLD:
            raw_intensities["Spiciness"] = min(1.0, raw_intensities["Spiciness"] * (1.0 + self.HEAT_SPICY_BOOST))

        return self._apply_ema(raw_intensities)

    def get_visual_params(self, intensities: dict[str, float]) -> dict:
        sweet       = intensities.get("Sweetness",   0.0)
        sour        = intensities.get("Sourness",    0.0)
        spicy       = intensities.get("Spiciness",   0.0)
        carbonation = intensities.get("Carbonation", 0.0)

        taste_weights = {"Sweetness": sweet, "Sourness": sour, "Spiciness": spicy}
        total_weight  = sum(taste_weights.values())

        if total_weight == 0.0:
            color_rgb        = (200, 200, 200)
            shape_angularity = 0.0
        else:
            r = sum(w * self._COLORS[t][0] for t, w in taste_weights.items()) / total_weight
            g = sum(w * self._COLORS[t][1] for t, w in taste_weights.items()) / total_weight
            b = sum(w * self._COLORS[t][2] for t, w in taste_weights.items()) / total_weight
            color_rgb = (round(r), round(g), round(b))

            shape_angularity = round(
                sum(w * self._ANGULARITY[t] for t, w in taste_weights.items()) / total_weight, 4
            )

        noise_level = round(max(0.0, min(1.0, spicy * 0.7 + carbonation * 0.3)), 4)

        return {
            "color_rgb":        color_rgb,
            "shape_angularity": shape_angularity,
            "noise_level":      noise_level,
        }

    def generate_audio_prompt(self, intensities: dict[str, float]) -> str:
        active_keys = sorted(
            [k for k in self._DESCRIPTORS if intensities.get(k, 0.0) >= self._AUDIO_THRESHOLD],
            key=lambda k: intensities.get(k, 0.0),
            reverse=True,
        )

        if not active_keys:
            return "[Ambient], neutral, soft, minimal"

        descs    = [self._DESCRIPTORS[k] for k in active_keys]
        tags     = " ".join(d["tag"] for d in descs if d["tag"])
        textures = [d["texture"] for d in descs]
        instrs   = [d["instr"]   for d in descs]

        def _join(parts: list[str]) -> str:
            return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" and {parts[-1]}"

        fusion = f"A composition with {_join(textures)}, featuring {_join(instrs)}."
        prefix = f"{tags}, " if tags else ""
        return f"{prefix}{', '.join(textures)}, {fusion}"

    def save_flavor_snapshot(self, label: str, data: dict) -> Path:
        """Process raw sensor data and persist the full taste frame as a JSON snapshot."""
        intensities  = self.process_data(**data)
        audio_prompt = self.generate_audio_prompt(intensities)

        _SNAPSHOTS_DIR.mkdir(exist_ok=True)
        safe_name = label.lower().replace(" ", "_").replace("/", "-")
        out_path  = _SNAPSHOTS_DIR / f"{safe_name}.json"

        payload = {
            "label":        label,
            "timestamp":    datetime.now().isoformat(timespec="seconds"),
            "raw_data":     data,
            "intensities":  {k: round(v, 6) for k, v in intensities.items()},
            "audio_prompt": audio_prompt,
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return out_path


# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    mapper = TasteMapper()

    raw = dict(raw_ph=2.8, raw_temp=5, raw_brix=8, raw_spicy=0,
               raw_co2=4.0, raw_ibu=40.0, raw_salt=0.0, raw_umami=0.0)
    intensities = mapper.process_data(**raw)

    print("=== Sparkling Bitter-Lemon ===")
    for sense, value in intensities.items():
        print(f"  {sense:<14} {value:.4f}  {'#' * int(value * 20)}")

    print(f"\n  Suno Prompt: {mapper.generate_audio_prompt(intensities)}")

    snap = mapper.save_flavor_snapshot("sparkling_bitter_lemon", raw)
    print(f"  Snapshot  : {snap}")
