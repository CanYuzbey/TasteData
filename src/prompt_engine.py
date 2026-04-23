"""
src/prompt_engine.py
Multi-Channel Suno Prompt Engine  --  Standalone Module

Thinking model applied here:
  A human producer receiving food sensor data would reason in four stages:
    1. What is the OVERALL VIBE? (energy, warmth, darkness, texture, richness)
    2. What GENRE fits that vibe? (tempo, structure, instrumentation palette)
    3. How many channels, and what ROLES? (kick, bass, pad, lead, texture, atmosphere...)
    4. For each channel, what is the EXACT SOUND? (source, timbre, articulation, FX)

  Every taste dimension, including Temperature, contributes to every stage.
  There is no threshold gating -- even a 0.1 intensity shift changes the output.

  Temperature in particular drives:
    - Reverb amount and tail length (hot = long/spacious, cold = dry/precise)
    - Mix density (hot = more layers, cold = sparse)
    - BPM tendency within the genre range (hot + spicy = upper end)
    - Timbre warmth/coldness across ALL channels

Entry point:
    bundle = generate_bundle(intensities)  # intensities from TasteMapper.process_data()
    for ch in bundle.channels:
        print(ch.label, "->", ch.prompt)
    print(bundle.master_prompt)
"""

from __future__ import annotations
from dataclasses import dataclass, field


def _c(v: float) -> float:
    return max(0.0, min(1.0, v))


# ============================================================================
# Stage 1: FlavorAxes
# Compress 8 taste dims into 5 aesthetic axes a human producer would feel.
# ============================================================================

@dataclass(frozen=True)
class FlavorAxes:
    """
    Five derived aesthetic axes + raw temperature feel.

    energy    -- arousal / activation / aggressiveness   [0=serene .. 1=aggressive]
    warmth    -- hedonic comfort / sweetness-umami glow  [0=cold/harsh .. 1=cozy]
    darkness  -- timbral weight / minor key pull         [0=bright .. 1=heavy/minor]
    texture   -- stochastic grain / surface roughness    [0=smooth .. 1=grainy]
    richness  -- harmonic fullness / spectral density    [0=sparse .. 1=lush]
    temp_feel -- raw normalized temperature (preserved)  [0=ice .. 1=scalding]
    """
    energy:    float
    warmth:    float
    darkness:  float
    texture:   float
    richness:  float
    temp_feel: float


def compute_axes(intensities: dict[str, float]) -> FlavorAxes:
    """
    Rationale per axis (the reasoning a producer would apply):

    energy: Capsaicin (spice) is the strongest arousal driver -- it activates TRPV1
        pain channels and triggers an adrenaline response. Acid (sourness) creates
        tension and urgency. Carbonation adds liveliness. Temperature is secondary.

    warmth: Sweetness and umami activate the brain's reward pathways. Moderate
        temperature is physically comforting. Bitterness is an evolutionary warning
        signal -- the opposite of comfort -- so it subtracts warmth.

    darkness: Bitterness maps naturally to minor keys and heavy timbres. Sourness
        adds harmonic dissonance (acid = unresolved, unstable). Low sweetness
        (absence of comfort) contributes residual darkness. Cold temperature adds
        an austere, sterile quality.

    texture: Carbonation is pure stochastic grain -- bubble nucleation is literally
        acoustic noise. Saltiness adds crystalline high-frequency structure.
        Spiciness adds roughness/noise.

    richness: Umami activates the broadest receptor range -- it makes food feel
        'full'. Sweetness adds upper-harmonic shimmer. Saltiness adds presence.
    """
    sw = intensities.get("Sweetness",   0.0)
    so = intensities.get("Sourness",    0.0)
    sp = intensities.get("Spiciness",   0.0)
    sa = intensities.get("Saltiness",   0.0)
    um = intensities.get("Umami",       0.0)
    ca = intensities.get("Carbonation", 0.0)
    bi = intensities.get("Bitterness",  0.0)
    te = intensities.get("Temperature", 0.0)

    energy   = _c(sp*0.40 + so*0.25 + ca*0.20 + te*0.10 + sa*0.05)
    warmth   = _c(sw*0.40 + um*0.30 + te*0.20 - bi*0.10)
    darkness = _c(bi*0.45 + so*0.25 + (1.0 - sw)*0.20 + (1.0 - te)*0.10)
    texture  = _c(ca*0.50 + sa*0.30 + sp*0.20)
    richness = _c(um*0.45 + sw*0.30 + sa*0.25)

    return FlavorAxes(energy, warmth, darkness, texture, richness, te)


# ============================================================================
# Stage 2: Genre Selection
# 12 genres cover the perceptual space; scored by weighted MSE against ideal axes.
# ============================================================================

@dataclass(frozen=True)
class GenreProfile:
    name:          str
    bpm_range:     tuple[int, int]   # (0, 0) = ambient / freeform
    style_tags:    tuple[str, ...]
    channel_roles: tuple[str, ...]   # ordered by mix priority
    key_tendency:  str               # "major", "minor", "dorian", "phrygian", "locrian"
    mix_aesthetic: str               # describes the intended mix engineer's approach
    # ideal axes: (energy, warmth, darkness, texture, richness, temp_feel)
    ideal:         tuple[float, ...]


# Axis weights for genre scoring.  Energy and darkness are most discriminative.
_AXIS_WEIGHTS = (0.28, 0.18, 0.24, 0.15, 0.10, 0.05)

_GENRES: tuple[GenreProfile, ...] = (
    GenreProfile(
        "Dark Techno / Industrial",
        (128, 145),
        ("[Dark Techno]", "[Industrial]", "[Heavy Bass]", "[Mechanical Pulse]"),
        ("KICK_HARD", "BASS_DIST", "PAD_DARK", "LEAD_DIST", "PERC_METAL",
         "TEX_NOISE", "ATMO_VOID"),
        "phrygian",
        "cold and sterile; maximum dynamic range; heavy sub compression; no warmth",
        (0.80, 0.10, 0.80, 0.55, 0.30, 0.65),
    ),
    GenreProfile(
        "Hyperpop / Club",
        (140, 165),
        ("[Hyperpop]", "[Club]", "[Hyper-bright]", "[Pitched Up]"),
        ("KICK_808", "BASS_808", "LEAD_BRIGHT", "PAD_SHIMMER", "PERC_CLAP",
         "TEX_GLITCH", "CHOP_VOCAL", "SFX_RISER"),
        "major",
        "maximally compressed; hyper-saturated highs; sidechain pumping; no headroom",
        (0.90, 0.45, 0.20, 0.80, 0.40, 0.55),
    ),
    GenreProfile(
        "Tropical House / Afrobeat",
        (100, 122),
        ("[Tropical]", "[Afrobeat]", "[Summer Vibes]", "[Warm Bass]"),
        ("KICK_WARM", "BASS_TROPICAL", "PAD_LUSH", "LEAD_STEEL", "PERC_HAND",
         "MELODY_HOOK", "CHORD_WARM"),
        "major",
        "warm and wide; lush reverb on pads; punchy percussion transients",
        (0.65, 0.80, 0.10, 0.30, 0.55, 0.60),
    ),
    GenreProfile(
        "Dark Ambient / Drone",
        (0, 0),
        ("[Dark Ambient]", "[Drone]", "[Cinematic Horror]", "[Slow Decay]"),
        ("BASS_DRONE", "PAD_DARK", "TEX_GRAIN", "ATMO_VOID", "LEAD_SPARSE"),
        "phrygian",
        "vast reverb tails; subsonic rumble; zero sharp transients; no clear tempo",
        (0.05, 0.20, 0.90, 0.45, 0.50, 0.25),
    ),
    GenreProfile(
        "Jazz / Soul",
        (80, 120),
        ("[Jazz]", "[Soul]", "[Live Band]", "[Swing Feel]"),
        ("BASS_UPRIGHT", "PERC_JAZZ", "HARM_RHODES", "LEAD_SAX",
         "PAD_BRASS", "TEX_BRUSH", "ATMO_ROOM"),
        "dorian",
        "live room feel; natural dynamics; mid-forward mix; subtle tape compression",
        (0.40, 0.80, 0.40, 0.20, 0.90, 0.50),
    ),
    GenreProfile(
        "Dream Pop / Shoegaze",
        (70, 100),
        ("[Shoegaze]", "[Dream Pop]", "[Wall of Sound]", "[Hazy]"),
        ("KICK_SOFT", "BASS_FUZZY", "PAD_WALL", "LEAD_JANGLY",
         "MELODY_ETHER", "TEX_TAPE", "ATMO_VAST"),
        "major",
        "washed in reverb; everything buried in effects; gauzy and soft",
        (0.30, 0.80, 0.20, 0.55, 0.65, 0.40),
    ),
    GenreProfile(
        "Minimal Techno",
        (120, 132),
        ("[Minimal Techno]", "[Stripped Back]", "[Hypnotic]"),
        ("KICK_CRISP", "BASS_SUB", "PAD_MINIMAL", "PERC_HIHAT", "LEAD_STAB"),
        "minor",
        "dry and surgical; no excess reverb; hypnotic repetition; minimal spectral content",
        (0.50, 0.20, 0.50, 0.25, 0.20, 0.45),
    ),
    GenreProfile(
        "IDM / Glitch",
        (90, 160),
        ("[IDM]", "[Glitch]", "[Electronica]", "[Complex Rhythms]"),
        ("KICK_GLITCH", "BASS_MODULAR", "PAD_GRANULAR", "LEAD_ALGO",
         "PERC_POLY", "TEX_MICRO", "SFX_GLITCH"),
        "dorian",
        "complex polyrhythms; granular processing throughout; clinical precision",
        (0.55, 0.30, 0.50, 0.90, 0.55, 0.40),
    ),
    GenreProfile(
        "Neo-Soul / R&B",
        (75, 98),
        ("[Neo-Soul]", "[R&B]", "[Smooth Groove]", "[Soulful]"),
        ("KICK_RNB", "BASS_SMOOTH", "HARM_RHODES", "LEAD_EXPR",
         "PAD_STRING", "PERC_SUBTLE", "MELODY_HOOK"),
        "dorian",
        "warm and wide; Rhodes front and center; lush string reverb; tight groove",
        (0.35, 0.90, 0.25, 0.20, 0.85, 0.55),
    ),
    GenreProfile(
        "Cinematic Orchestral",
        (60, 120),
        ("[Cinematic]", "[Orchestral]", "[Epic Score]", "[Dramatic]"),
        ("BASS_ORCH", "PAD_STRINGS", "HARM_ORCH", "LEAD_SOLO",
         "PERC_ORCH", "BRASS_SWELL", "ATMO_HALL", "MELODY_THEME"),
        "minor",
        "concert hall reverb; full dynamic range; natural instrument texture; no digital artifacts",
        (0.55, 0.50, 0.60, 0.40, 0.95, 0.50),
    ),
    GenreProfile(
        "Punk / Noise Rock",
        (140, 185),
        ("[Punk]", "[Noise Rock]", "[Aggressive]", "[Raw Energy]"),
        ("KICK_RAW", "BASS_OVERDRIVE", "HARM_RHYTHM_GTR", "LEAD_SCREAM",
         "PERC_SNARE", "ATMO_ROOM_NOISE"),
        "minor",
        "raw and unprocessed; all midrange aggression; live room bleed; zero polish",
        (0.95, 0.10, 0.60, 0.65, 0.20, 0.70),
    ),
    GenreProfile(
        "Ambient Electronic",
        (60, 80),
        ("[Ambient]", "[Electronic]", "[Evolving]", "[Meditative]"),
        ("PAD_EVOLVE", "TEX_GRAIN", "MELODY_SPARSE", "ATMO_DEEP", "BASS_GENTLE"),
        "major",
        "wide stereo field; long evolving reverb; slow movement; no sharp transients",
        (0.10, 0.60, 0.30, 0.60, 0.50, 0.35),
    ),
)


def select_genre(axes: FlavorAxes) -> GenreProfile:
    """Pick genre with minimum weighted MSE distance to current flavor axes."""
    actual = (axes.energy, axes.warmth, axes.darkness,
              axes.texture, axes.richness, axes.temp_feel)

    def score(g: GenreProfile) -> float:
        return sum(w * (a - b) ** 2
                   for w, a, b in zip(_AXIS_WEIGHTS, actual, g.ideal))

    return min(_GENRES, key=score)


# ============================================================================
# Stage 3: Channel Roster
# Genre determines the base set; intensity/richness modulates how many we use.
# ============================================================================

def _channel_count(genre: GenreProfile, axes: FlavorAxes) -> int:
    """
    Scale channel count by harmonic density.
    Sparse/quiet profiles get fewer channels; dense/rich profiles get the full set.
    Minimum 3 (kick/bass/pad).  Maximum = full genre roster.
    """
    base     = len(genre.channel_roles)
    density  = _c(axes.energy * 0.40 + axes.richness * 0.60)
    fraction = 0.55 + density * 0.45
    return max(3, min(base, round(base * fraction)))


def _key_mood(axes: FlavorAxes) -> str:
    """Derive key/mode from darkness + warmth axes."""
    if axes.darkness > 0.72:
        return "Phrygian" if axes.energy > 0.50 else "Locrian"
    if axes.darkness > 0.52:
        return "natural minor"
    if axes.darkness > 0.35:
        return "Dorian"
    if axes.warmth > 0.72:
        return "Lydian" if axes.richness > 0.50 else "major"
    if axes.warmth > 0.50:
        return "Mixolydian"
    return "natural major"


def _bpm(genre: GenreProfile, axes: FlavorAxes) -> int:
    """
    Select BPM within genre range.
    Energy + temperature push toward the upper bound.
    Warmth + richness pull toward the lower bound (relaxed feel).
    Ambient genres return 0.
    """
    lo, hi = genre.bpm_range
    if hi == 0:
        return 0
    t = _c(axes.energy * 0.55 + axes.temp_feel * 0.20
           - axes.warmth * 0.15 - axes.richness * 0.10)
    return round(lo + t * (hi - lo))


# ============================================================================
# Stage 4: Per-Channel Prompt Rendering
# Every taste dim contributes to every channel through three lenses:
#   timbre adjectives  (what it sounds like)
#   articulation note  (how it plays)
#   effects chain      (what processing is applied)
# ============================================================================

# Source catalog: role key -> (description, suno_bracket_tag)
# Each description may reference taste intensities via format placeholders,
# but for clarity most use fixed strings -- the timbral modifiers do the adaptation.

_SOURCES: dict[str, tuple[str, str]] = {
    # Kicks
    "KICK_HARD":       ("industrial kick drum",                   "[Hard Kick]"),
    "KICK_808":        ("808 kick with extended sub decay",       "[808 Kick]"),
    "KICK_WARM":       ("warm padded kick drum",                  "[Warm Kick]"),
    "KICK_SOFT":       ("soft pillowy kick -- distant and padded","[Soft Kick]"),
    "KICK_CRISP":      ("crisp click kick -- pure transient only","[Crisp Kick]"),
    "KICK_GLITCH":     ("pitch-envelope glitch kick",             "[Glitch Kick]"),
    "KICK_RAW":        ("raw unprocessed kick -- live room bleed","[Raw Kick]"),
    "KICK_RNB":        ("warm R&B kick with slight 808 tail",     "[R&B Kick]"),
    # Basses
    "BASS_DIST":       ("distorted analog bass synth",            "[Distorted Bass]"),
    "BASS_808":        ("melodic 808 bass with pitch slides",     "[808 Bass]"),
    "BASS_TROPICAL":   ("clean electric bass, light and bouncy",  "[Tropical Bass]"),
    "BASS_DRONE":      ("sub-sonic drone oscillator",             "[Drone Bass]"),
    "BASS_UPRIGHT":    ("acoustic upright bass -- plucked strings, wood resonance", "[Upright Bass]"),
    "BASS_FUZZY":      ("heavily fuzz-pedal electric bass",       "[Fuzz Bass]"),
    "BASS_SUB":        ("clean sine-wave sub -- no harmonics, pure foundation",     "[Sub Bass]"),
    "BASS_MODULAR":    ("modular FM synth bass -- evolving harmonics",              "[Modular Bass]"),
    "BASS_SMOOTH":     ("smooth electric bass -- Jazz pickup, light compression",   "[Smooth Bass]"),
    "BASS_OVERDRIVE":  ("massively overdriven bass guitar -- all mids",             "[Overdrive Bass]"),
    "BASS_ORCH":       ("cello and contrabass section -- bowed, deep register",     "[Orchestral Bass]"),
    "BASS_GENTLE":     ("sub sine bass with gentle low-pass -- barely there",       "[Gentle Bass]"),
    # Pads
    "PAD_DARK":        ("dark Moog-style pad with filter modulation",           "[Dark Pad]"),
    "PAD_SHIMMER":     ("shimmer reverb pad -- octave-up, almost bell-like",    "[Shimmer Pad]"),
    "PAD_LUSH":        ("lush Roland Juno-106 chorus pad -- dripping warmth",   "[Lush Pad]"),
    "PAD_WALL":        ("wall-of-sound guitar pad -- twelve guitars in reverb", "[Wall of Sound]"),
    "PAD_MINIMAL":     ("single oscillator minimal pad",                        "[Minimal Pad]"),
    "PAD_GRANULAR":    ("granular pad built from frozen source layers",         "[Granular Pad]"),
    "PAD_STRINGS":     ("orchestral string ensemble pad",                       "[String Pad]"),
    "PAD_BRASS":       ("warm brass ensemble held chord",                       "[Brass Pad]"),
    "PAD_EVOLVE":      ("slowly evolving ambient pad -- LFO filter, minute-long morphs", "[Evolving Pad]"),
    "PAD_STRING":      ("warm string section -- light vibrato, sustain-heavy",  "[String Pad]"),
    # Leads
    "LEAD_DIST":       ("industrial Minimoog lead through fuzz",                "[Distorted Lead]"),
    "LEAD_BRIGHT":     ("hyper-bright pitched lead synth -- octave shifted up", "[Bright Lead]"),
    "LEAD_STEEL":      ("steel pan / marimba -- warm mallet attack, tropical",  "[Steel Pan]"),
    "LEAD_SAX":        ("saxophone -- breathy and expressive",                  "[Saxophone]"),
    "LEAD_JANGLY":     ("jangly electric guitar -- Jazzmaster with tremolo",    "[Jangly Guitar]"),
    "LEAD_SPARSE":     ("sparse plucked notes -- long silences between each",   "[Sparse Lead]"),
    "LEAD_ALGO":       ("algorithmic melodic sequence -- Euclidean rhythm",     "[Algo Lead]"),
    "LEAD_EXPR":       ("expressive electric guitar lead -- heavy vibrato, bends", "[Expressive Lead]"),
    "LEAD_SCREAM":     ("screaming lead guitar -- full gain, feedback at peaks","[Screaming Guitar]"),
    "LEAD_STAB":       ("sparse synth stab -- one or two notes, long gaps",     "[Synth Stab]"),
    "LEAD_SOLO":       ("solo orchestral instrument -- intimate, front of mix", "[Solo Instrument]"),
    # Harmony / Chords
    "HARM_RHODES":     ("Rhodes electric piano -- warm chord voicings",         "[Rhodes]"),
    "HARM_ORCH":       ("full orchestra harmony -- strings, brass, woodwinds",  "[Full Orchestra]"),
    "HARM_RHYTHM_GTR": ("distorted rhythm guitar -- power chords, all aggression", "[Rhythm Guitar]"),
    "CHORD_WARM":      ("warm chord stabs -- acoustic guitar or piano",         "[Warm Chords]"),
    # Melody
    "MELODY_HOOK":     ("melodic hook -- earworm element, bright and forward",  "[Melody Hook]"),
    "MELODY_SPARSE":   ("sparse melodic element -- notes surrounded by silence","[Sparse Melody]"),
    "MELODY_ETHER":    ("ethereal vocal-like melody -- pitched up, underwater", "[Ethereal Melody]"),
    "MELODY_THEME":    ("thematic orchestral melody -- strings or solo woodwind","[Theme Melody]"),
    # Percussion
    "PERC_METAL":      ("metallic industrial hits -- steel drums, chain clangs","[Metal Percussion]"),
    "PERC_JAZZ":       ("jazz drum kit -- ride cymbal prominent, brushed snare","[Jazz Drums]"),
    "PERC_HAND":       ("tropical hand percussion -- congas, djembe, shakers",  "[Hand Percussion]"),
    "PERC_HIHAT":      ("sparse hi-hat pattern -- eighth notes, very dry",      "[Hi-Hats]"),
    "PERC_SNARE":      ("hard-hitting snare -- raw, unprocessed, maximum crack","[Hard Snare]"),
    "PERC_CLAP":       ("808 clap + layered snare -- hyper-processed",          "[Clap/Snare]"),
    "PERC_ORCH":       ("orchestral percussion -- timpani, snare, bass drum",   "[Orchestral Perc]"),
    "PERC_POLY":       ("polyrhythmic electronic percussion -- 5-against-3",    "[Poly Percussion]"),
    "PERC_SUBTLE":     ("subtle percussion accents -- tambourine, rim clicks",  "[Subtle Percussion]"),
    # Textures
    "TEX_NOISE":       ("industrial noise texture -- white noise filtered to mid-hiss", "[Noise Texture]"),
    "TEX_GRAIN":       ("granular synthesis texture -- bubble-like grain bursts",       "[Granular Texture]"),
    "TEX_GLITCH":      ("glitch texture -- stuttered buffers, digital artifacts",       "[Glitch Texture]"),
    "TEX_MICRO":       ("microsound texture -- grains < 50ms, continuous tone clouds",  "[Micro Texture]"),
    "TEX_BRUSH":       ("brush strokes on snare -- whispered rhythm",                   "[Brush Texture]"),
    "TEX_TAPE":        ("tape noise and warmth -- gentle hiss, wow-and-flutter",        "[Tape Texture]"),
    # Atmospheres
    "ATMO_VOID":       ("void atmosphere -- deep reverb, subsonic rumble",              "[Void Atmosphere]"),
    "ATMO_VAST":       ("vast hall reverb -- 8+ second tail, no direct signal",         "[Vast Atmosphere]"),
    "ATMO_ROOM":       ("live room atmosphere -- natural acoustic reflections",          "[Room Atmosphere]"),
    "ATMO_HALL":       ("concert hall atmosphere -- rich natural reverb, full decay",    "[Concert Hall]"),
    "ATMO_ROOM_NOISE": ("live room noise -- crowd bleed, microphone spill",             "[Room Noise]"),
    "ATMO_DEEP":       ("deep ambient atmosphere -- slow filter sweeps, weightless",     "[Deep Atmosphere]"),
    # Special
    "BRASS_SWELL":     ("brass swell -- full section building to peak then releasing",  "[Brass Swell]"),
    "CHOP_VOCAL":      ("chopped and pitched vocal samples -- harmonic content",        "[Vocal Chops]"),
    "SFX_RISER":       ("riser and sweep -- tension builder for drops",                 "[Riser/Sweep]"),
    "SFX_GLITCH":      ("glitch artifacts -- buffer repeats, bitcrush bursts",          "[Glitch SFX]"),
}


def _timbre_words(
    role: str, sw: float, so: float, sp: float, sa: float,
    um: float, ca: float, bi: float, te: float,
) -> list[str]:
    """
    Every taste dimension contributes a timbral adjective.
    No threshold gating -- even small intensities shift the description.
    Role context modulates how each dimension expresses itself.
    """
    w = []

    # SWEETNESS: roundness, warmth, softness
    if sw > 0.70:
        w.append("silky and warm")
    elif sw > 0.40:
        w.append("smooth and rounded")
    elif sw > 0.15:
        w.append("slightly warm")

    # SOURNESS: brightness, edge, acidity
    if so > 0.75:
        w.append("piercing and acidic")
    elif so > 0.50:
        w.append("bright with a sharp edge")
    elif so > 0.20:
        w.append("slightly bright")

    # SPICINESS: saturation, distortion, aggression
    if sp > 0.75:
        is_signal = any(x in role for x in ("BASS", "LEAD", "HARM", "GTR"))
        w.append("heavily saturated and overdriven" if is_signal else "aggressive and dense")
    elif sp > 0.45:
        w.append("lightly gritty")
    elif sp > 0.15:
        w.append("slightly edgy")

    # SALTINESS: crystalline highs, precision, sparkle
    if sa > 0.65:
        w.append("crystalline with high-frequency shimmer")
    elif sa > 0.40:
        w.append("articulate and precise")
    elif sa > 0.15:
        w.append("slightly bright presence")

    # UMAMI: depth, fullness, harmonic density
    if um > 0.70:
        is_bass = any(x in role for x in ("BASS", "DRONE", "ORCH"))
        w.append("deep and resonant with rich overtones" if is_bass else "full-bodied and harmonically dense")
    elif um > 0.40:
        w.append("warm and full")
    elif um > 0.15:
        w.append("slightly thick")

    # CARBONATION: grain, breathiness, stochastic character
    if ca > 0.65:
        is_tex = any(x in role for x in ("TEX", "GRAIN", "GLITCH", "MICRO"))
        w.append("highly granular with stochastic micro-variations" if is_tex else "airy with granular overtones")
    elif ca > 0.35:
        w.append("lightly textured with airy overtones")
    elif ca > 0.10:
        w.append("faintly effervescent")

    # BITTERNESS: darkness, heaviness, low-frequency emphasis
    if bi > 0.70:
        is_low = any(x in role for x in ("BASS", "DARK", "DRONE", "VOID"))
        w.append("dark and ominous with heavy low-end weight" if is_low else "dense and dark")
    elif bi > 0.40:
        w.append("subtly dark and weighted")
    elif bi > 0.15:
        w.append("slightly somber")

    # TEMPERATURE: the physical feel of the sound -- cold/hot maps to dry/saturated
    # This is where temperature gets a direct voice in EVERY channel.
    if te > 0.80:
        w.append("hot and saturated -- dense and steamy like a heat haze")
    elif te > 0.60:
        w.append("warm and slightly hazy")
    elif te > 0.40:
        w.append("room-temperature -- clear and neutral")
    elif te > 0.20:
        w.append("cool and crisp")
    else:
        w.append("cold and sterile -- icy precision")

    return w if w else ["neutral"]


def _articulation(
    role: str, sw: float, so: float, sp: float, sa: float,
    um: float, ca: float, bi: float, te: float,
) -> str:
    """
    One or two sentences on playing style and articulation.
    Drone/pad/atmosphere roles get sustained-specific language.
    Rhythmic roles get transient/tempo-specific language.
    """
    is_sustained = any(x in role for x in
                       ("PAD", "DRONE", "ATMO", "EVOLVE", "AMBIENT", "HALL", "VAST", "VOID", "ROOM", "DEEP"))
    is_rhythmic   = any(x in role for x in ("KICK", "PERC", "SNARE", "CLAP", "HIHAT"))

    parts = []

    if is_sustained:
        # Attack
        if sw > 0.50 or um > 0.50:
            parts.append("very slow fade-in -- bloom over 2-4 seconds")
        elif bi > 0.60:
            parts.append("slow attack with heavy low-end onset")
        else:
            parts.append("gradual attack -- 1-2 second onset")
        # Sustain modulation
        if ca > 0.50:
            parts.append("sustain layer shimmers with granular micro-variations, simulating bubble bursts")
        if te > 0.70:
            parts.append("dense sustained body -- saturated and slow-moving")
        elif te < 0.25:
            parts.append("sparse, crystalline sustain -- notes hang in cold air")
        # Release
        if um > 0.55:
            parts.append("long, gradual release -- harmonics decay over several seconds")
        elif bi > 0.55:
            parts.append("abrupt release when the filter closes")
        return ". ".join(parts)

    if is_rhythmic:
        # Attack
        if so > 0.55 or sp > 0.55:
            parts.append("maximum transient punch -- fastest possible attack")
        elif sw > 0.55:
            parts.append("soft, rounded transient")
        else:
            parts.append("sharp transient")
        # Decay
        if sa > 0.50:
            parts.append("tight, precise decay -- no smear")
        if te > 0.70:
            parts.append("slightly extended decay -- temperature adds warmth to the tail")
        elif te < 0.25:
            parts.append("extremely tight decay -- no room in the cold")
        # Tempo density
        if sp > 0.65 or so > 0.65:
            parts.append("fast, urgent -- fills available rhythmic space")
        elif sw > 0.65 or um > 0.65:
            parts.append("deliberate and unhurried")
        return "; ".join(parts)

    # Default (lead, bass, melody, harmony)
    if so > 0.55 or sp > 0.55:
        parts.append("sharp attack")
    elif sw > 0.55 or um > 0.55:
        parts.append("soft rounded onset")
    else:
        parts.append("moderate attack")

    if um > 0.60:
        parts.append("long sustain with gradual harmonic decay")
    elif bi > 0.55:
        parts.append("medium sustain cut off abruptly")
    elif ca > 0.55:
        parts.append("sustain broken by granular micro-stutters")
    elif sw > 0.55:
        parts.append("smooth sustained body that blooms")

    if sa > 0.50:
        parts.append("rhythmically precise and well-articulated")
    if sp > 0.70 or so > 0.70:
        parts.append("dense, fast note output")
    elif sw > 0.65 or um > 0.65:
        parts.append("slow, deliberate phrasing")

    return ", ".join(parts) if parts else "standard articulation"


def _fx_chain(
    role: str, sw: float, so: float, sp: float, sa: float,
    um: float, ca: float, bi: float, te: float,
    axes: FlavorAxes,
) -> list[str]:
    """
    Build the effects chain.  Temperature is the PRIMARY reverb driver here --
    this is where it has the most direct and unique sonic impact.
    """
    fx = []

    # --- REVERB (temperature + sweetness + umami determine size and length) ---
    # Cold = dry and tight; warm = spacious; hot = dense, saturated room
    reverb_amount = _c(te * 0.50 + sw * 0.25 + um * 0.15 - bi * 0.10)
    if te > 0.75:
        fx.append("dense plate reverb -- hot, saturated room feel; pre-delay 15ms")
    elif te > 0.55 or reverb_amount > 0.65:
        fx.append("long hall reverb with warm tail (2-4s)")
    elif te > 0.35 or reverb_amount > 0.40:
        fx.append("medium room reverb (0.8-1.5s)")
    elif te < 0.20:
        fx.append("almost dry -- tiny room reverb only; cold precision")
    else:
        fx.append("short room reverb (0.3-0.6s)")

    # --- DELAY (sourness adds rhythmic delay -- acid creates echo/reflection) ---
    if so > 0.60 and "KICK" not in role:
        fx.append("dotted-eighth ping-pong delay -- sourness creates rhythmic echo")
    elif ca > 0.55 and any(x in role for x in ("TEX", "GRAIN", "MICRO")):
        fx.append("micro-delay < 20ms for granular smearing")

    # --- DISTORTION / SATURATION (spiciness is capsaicin = pain = overdrive) ---
    if sp > 0.75:
        fx.append("heavy overdrive + bitcrusher (spiciness drives maximum saturation)")
    elif sp > 0.45:
        fx.append("light tape saturation")
    elif sp > 0.15:
        fx.append("subtle harmonic exciter")

    # --- FILTER (bitterness darkens, sourness brightens) ---
    if bi > 0.65 and "KICK" not in role:
        fx.append("low-pass filter sweeping down -- bitterness closes the highs")
    elif so > 0.65 and not any(x in role for x in ("KICK", "BASS")):
        fx.append("high-pass + presence boost -- sourness opens the top end")

    # --- COMPRESSION ---
    if axes.energy > 0.75:
        fx.append("heavy compression (4:1 or harder) -- maximum punch and density")
    elif axes.energy > 0.45:
        fx.append("moderate compression (2:1)")
    else:
        fx.append("gentle limiting only")

    # --- GRANULAR PROCESSING (carbonation drives grain specifically) ---
    if ca > 0.55 and any(x in role for x in ("TEX", "GRAIN", "MICRO", "PAD_GRANULAR", "PAD_EVOLVE")):
        grain_hz = int(2000 + ca * 18000)
        fx.append(
            f"granular synthesis: grain pitch ~{grain_hz} Hz, "
            f"grain density {ca:.2f} (proportional to CO2 intensity)"
        )

    # --- CHORUS / ENSEMBLE DETUNE (saltiness crystallizes via shimmer) ---
    if sa > 0.55 and not any(x in role for x in ("KICK", "BASS_SUB", "BASS_DRONE")):
        fx.append("subtle chorus/ensemble detune -- saltiness adds crystalline shimmer")

    # --- TEMPERATURE-SPECIFIC MIX TREATMENT ---
    if te < 0.20:
        fx.append("narrow stereo image -- mono-compatible; cold precision")
    elif te > 0.70:
        fx.append("wide mid-side stereo -- hot and expansive")

    return fx


def _render_channel(
    role: str,
    genre: GenreProfile,
    axes: FlavorAxes,
    intensities: dict[str, float],
    bpm_val: int,
    key_mood_str: str,
) -> "RenderedChannel":
    sw = intensities.get("Sweetness",   0.0)
    so = intensities.get("Sourness",    0.0)
    sp = intensities.get("Spiciness",   0.0)
    sa = intensities.get("Saltiness",   0.0)
    um = intensities.get("Umami",       0.0)
    ca = intensities.get("Carbonation", 0.0)
    bi = intensities.get("Bitterness",  0.0)
    te = intensities.get("Temperature", 0.0)

    source_desc, suno_tag = _SOURCES.get(
        role, (role.lower().replace("_", " "), f"[{role.replace('_',' ').title()}]")
    )

    timbre_list = _timbre_words(role, sw, so, sp, sa, um, ca, bi, te)
    artic       = _articulation(role, sw, so, sp, sa, um, ca, bi, te)
    fx_list     = _fx_chain(role, sw, so, sp, sa, um, ca, bi, te, axes)

    is_rhythmic = any(x in role for x in ("KICK", "PERC", "SNARE", "CLAP", "HIHAT"))
    bpm_line    = f" at {bpm_val} BPM" if bpm_val > 0 and is_rhythmic else ""

    label  = role.replace("_", " ").title()
    prompt = (
        f"{suno_tag} "
        f"{source_desc} -- {', '.join(timbre_list)}. "
        f"Articulation: {artic}. "
        f"FX: {'; '.join(fx_list)}. "
        f"Key/mode: {key_mood_str}{bpm_line}."
    )

    return RenderedChannel(role=role, label=label, prompt=prompt)


@dataclass
class RenderedChannel:
    role:   str
    label:  str
    prompt: str


# ============================================================================
# Master Prompt Builder
# ============================================================================

def _master_prompt(
    genre: GenreProfile,
    axes: FlavorAxes,
    intensities: dict[str, float],
    channels: list[RenderedChannel],
    bpm_val: int,
    key_mood_str: str,
) -> str:
    """
    Combine all channels into a single rich Suno master prompt.
    Structure Suno responds to best:
      1. Style tags (genre + dominant characteristics)
      2. BPM + Key
      3. One-sentence overall mood
      4. Arrangement layer list (condensed per-channel)
      5. Dominant sensory signature
      6. Mix engineer intent
    """
    sw = intensities.get("Sweetness",   0.0)
    so = intensities.get("Sourness",    0.0)
    sp = intensities.get("Spiciness",   0.0)
    sa = intensities.get("Saltiness",   0.0)
    um = intensities.get("Umami",       0.0)
    ca = intensities.get("Carbonation", 0.0)
    bi = intensities.get("Bitterness",  0.0)
    te = intensities.get("Temperature", 0.0)

    # Style tags
    tags = list(genre.style_tags)
    if bpm_val > 0:
        tags.append(f"[{bpm_val} BPM]")
    tags.append(f"[{key_mood_str}]")
    if sp > 0.65:  tags.append("[Aggressive]")
    if ca > 0.55:  tags.append("[Granular Texture]")
    if bi > 0.55:  tags.append("[Heavy Low End]")
    if sw > 0.60:  tags.append("[Warm]")
    if sa > 0.60:  tags.append("[Crystalline Highs]")
    if um > 0.60:  tags.append("[Rich Harmonics]")
    if te > 0.72:  tags.append("[Hot and Dense]")
    elif te < 0.20: tags.append("[Cold and Sterile]")
    tag_line = " ".join(tags)

    # Overall mood sentence
    energy_word = ("relentless and high-energy" if axes.energy > 0.72
                   else "moderately energetic" if axes.energy > 0.42
                   else "calm and introspective")
    feel_words = []
    if axes.warmth > 0.65:    feel_words.append("warm and comforting")
    elif axes.darkness > 0.65: feel_words.append("dark and foreboding")
    if axes.texture > 0.60:    feel_words.append("texturally rich")
    if axes.richness > 0.70:   feel_words.append("harmonically full")
    feel_str = (", " + ", ".join(feel_words)) if feel_words else ""
    mood_line = f"A {energy_word}{feel_str} composition. {genre.mix_aesthetic.capitalize()}."

    # Arrangement (condensed)
    arrangement_parts = []
    for ch in channels:
        src = _SOURCES.get(ch.role, (ch.role, ""))[0].split("--")[0].strip()
        arrangement_parts.append(f"{ch.label} ({src})")
    arrangement_line = "Arrangement: " + " | ".join(arrangement_parts) + "."

    # Sensory signature -- what makes this food's music unique
    # Every dim gets a voice if above 0.15
    dim_descs = [
        ("Sourness",    so, "acid cuts through every layer with dissonant urgency"),
        ("Sweetness",   sw, "sweetness softens attacks and extends reverb tails"),
        ("Spiciness",   sp, "capsaicin burns through as overdrive and aggression"),
        ("Bitterness",  bi, "bitterness anchors the low end in dark harmonic weight"),
        ("Saltiness",   sa, "salt crystallizes the high frequencies into shimmer"),
        ("Umami",       um, "umami fills every harmonic gap with resonant depth"),
        ("Carbonation", ca, "carbonation injects stochastic granular grain"),
        ("Temperature", te,
         ("heat saturates the texture -- dense, steamy reverb throughout" if te > 0.65
          else "cold temperature strips reverb dry, leaving sterile precision" if te < 0.28
          else "moderate temperature grounds the reverb with a natural room feel")),
    ]
    active = sorted([(n, v, d) for n, v, d in dim_descs if v > 0.12],
                    key=lambda x: x[1], reverse=True)
    sensory_line = ""
    if active:
        parts = [d for _, _, d in active[:5]]
        sensory_line = "Sensory signature: " + "; ".join(parts) + "."

    sections = [tag_line, "", mood_line, arrangement_line]
    if sensory_line:
        sections.append(sensory_line)

    return "\n".join(sections)


# ============================================================================
# PromptBundle + Entry Point
# ============================================================================

@dataclass
class PromptBundle:
    genre_name:    str
    bpm:           int
    key_mood:      str
    axes:          FlavorAxes
    channels:      list[RenderedChannel]
    master_prompt: str

    def summary(self, width: int = 78) -> str:
        sep   = "+" + "=" * (width - 2) + "+"
        dash  = "+" + "-" * (width - 2) + "+"
        lines = [
            sep,
            f"|  Genre   : {self.genre_name}".ljust(width - 1) + "|",
            f"|  BPM     : {self.bpm if self.bpm > 0 else 'freeform (ambient)'}".ljust(width - 1) + "|",
            f"|  Key     : {self.key_mood}".ljust(width - 1) + "|",
            (f"|  Axes    : energy={self.axes.energy:.2f}  warmth={self.axes.warmth:.2f}"
             f"  dark={self.axes.darkness:.2f}  tex={self.axes.texture:.2f}"
             f"  rich={self.axes.richness:.2f}  temp={self.axes.temp_feel:.2f}").ljust(width - 1) + "|",
            sep,
            f"|  Channels ({len(self.channels)})".ljust(width - 1) + "|",
            dash,
        ]
        for ch in self.channels:
            lines.append(f"|  [{ch.label}]".ljust(width - 1) + "|")
            # word-wrap prompt at width - 5
            remaining = ch.prompt
            while len(remaining) > width - 6:
                cut = remaining[:width - 6].rfind(" ")
                cut = cut if cut > 20 else width - 6
                lines.append(f"|    {remaining[:cut]}".ljust(width - 1) + "|")
                remaining = remaining[cut:].lstrip()
            lines.append(f"|    {remaining}".ljust(width - 1) + "|")
            lines.append("|" + " " * (width - 2) + "|")
        lines += [
            dash,
            "|  MASTER PROMPT".ljust(width - 1) + "|",
            dash,
        ]
        for raw_line in self.master_prompt.splitlines():
            remaining = raw_line if raw_line else " "
            while len(remaining) > width - 5:
                cut = remaining[:width - 5].rfind(" ")
                cut = cut if cut > 10 else width - 5
                lines.append(f"|  {remaining[:cut]}".ljust(width - 1) + "|")
                remaining = remaining[cut:].lstrip()
            lines.append(f"|  {remaining}".ljust(width - 1) + "|")
        lines.append(sep)
        return "\n".join(lines)


def generate_bundle(intensities: dict[str, float]) -> PromptBundle:
    """
    Full pipeline: taste intensities -> PromptBundle.

    Args:
        intensities: Output of TasteMapper.process_data() -- 8 taste dims in [0, 1].

    Returns:
        PromptBundle with per-channel prompts and a combined master prompt.
    """
    axes         = compute_axes(intensities)
    genre        = select_genre(axes)
    bpm_val      = _bpm(genre, axes)
    key_mood_str = _key_mood(axes)
    n_channels   = _channel_count(genre, axes)

    channels: list[RenderedChannel] = [
        _render_channel(role, genre, axes, intensities, bpm_val, key_mood_str)
        for role in genre.channel_roles[:n_channels]
    ]

    master = _master_prompt(genre, axes, intensities, channels, bpm_val, key_mood_str)

    return PromptBundle(
        genre_name=genre.name,
        bpm=bpm_val,
        key_mood=key_mood_str,
        axes=axes,
        channels=channels,
        master_prompt=master,
    )


# ============================================================================
# Standalone Demo
# ============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.brain import TasteMapper

    DEMOS = {
        "Classic Cola":       dict(raw_ph=2.8, raw_temp=4,  raw_brix=11.0, raw_spicy=0,
                                   raw_co2=3.5, raw_ibu=2.0,  raw_salt=0,   raw_umami=0),
        "Double Espresso":    dict(raw_ph=5.0, raw_temp=90, raw_brix=1.0,  raw_spicy=0,
                                   raw_co2=0,   raw_ibu=80.0, raw_salt=0,   raw_umami=0),
        "Miso Soup":          dict(raw_ph=4.9, raw_temp=68, raw_brix=2.0,  raw_spicy=0,
                                   raw_co2=0,   raw_ibu=0,    raw_salt=8.5, raw_umami=16.0),
        "Extreme Hot Sauce":  dict(raw_ph=3.5, raw_temp=22, raw_brix=3.0,  raw_spicy=40_000,
                                   raw_co2=0,   raw_ibu=0,    raw_salt=0,   raw_umami=0),
        "Tonic Water":        dict(raw_ph=2.5, raw_temp=4,  raw_brix=8.0,  raw_spicy=0,
                                   raw_co2=4.2, raw_ibu=35.0, raw_salt=0,   raw_umami=0),
    }

    mapper = TasteMapper()
    for food, raw in DEMOS.items():
        mapper.reset_ema()
        intensities = mapper.process_data(**raw)
        bundle      = generate_bundle(intensities)
        print(bundle.summary())
        print()
