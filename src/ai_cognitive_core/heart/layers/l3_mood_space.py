import math
from typing import Any, Dict, Optional, Tuple

from ai_cognitive_core import config
from ai_cognitive_core.schemas import PADVector, PrimaryAffectState

PAD_TIME_DECAY_LAMBDA = 1.0 / 7200.0  # Paruh waktu mood ~2 jam saat idle


def decay_pad_over_time(pad_t: PADVector, pad_0: PADVector, delta_seconds: float) -> PADVector:
    """Koreksi Argon Audit: Mencegah Time-Step Drift antara Layer 1 dan Layer 3 saat pindah sesi."""
    if delta_seconds < 120:
        return pad_t
    gamma = math.exp(-PAD_TIME_DECAY_LAMBDA * delta_seconds)
    return PADVector(
        P=pad_0.P + (pad_t.P - pad_0.P) * gamma,
        A=pad_0.A + (pad_t.A - pad_0.A) * gamma,
        D=pad_0.D + (pad_t.D - pad_0.D) * gamma,
    ).clamp()


def pull_push_update(
    pad_t: PADVector,
    pad_0: PADVector,
    delta_ctx: PADVector,
    inertia_pi1: float = 0.35,
    beta_0: float = 0.28,
) -> PADVector:
    """
    Persamaan Pull-Push Engine (PPE):
    PAD_{t+1} = CLAMP(PAD_t + alpha * Delta_ctx + (1 - alpha) * beta_0 * (PAD_0 - PAD_t))
    dengan alpha = 1 - inertia_pi1.
    """
    alpha = max(0.05, min(0.95, 1.0 - inertia_pi1))
    p_next = pad_t.P + alpha * delta_ctx.P + (1.0 - alpha) * beta_0 * (pad_0.P - pad_t.P)
    a_next = pad_t.A + alpha * delta_ctx.A + (1.0 - alpha) * beta_0 * (pad_0.A - pad_t.A)
    d_next = pad_t.D + alpha * delta_ctx.D + (1.0 - alpha) * beta_0 * (pad_0.D - pad_t.D)
    return PADVector(P=p_next, A=a_next, D=d_next).clamp()


def detect_coactivation(affects: PrimaryAffectState) -> Tuple[str, Optional[str]]:
    scores = affects.model_dump()
    sorted_affects = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    dominant = sorted_affects[0][0]
    pos_set = {"SEEKING", "CARE", "PLAY", "LUST"}
    neg_set = {"FEAR", "RAGE", "PANIC_GRIEF"}

    secondary = None
    for name, val in sorted_affects[1:]:
        if val >= 0.35:
            if (dominant in pos_set and name in neg_set) or (dominant in neg_set and name in pos_set):
                secondary = name
                break
    return dominant, secondary


# ---------------------------------------------------------------------------
# Ekspansi PAD v0.6.0 — fungsi deterministik (tanpa randomness)
# Dipakai engine untuk mengisi field baru di EmotionalDirective / HeartState.
# Aturan klasifikasi didokumentasikan di tiap docstring; kalau user mengubah
# sebuah ambang atau label, ubah di sini (satu tempat).
# ---------------------------------------------------------------------------

# Default delta PAD saat belum ada PAD sebelumnya (turn pertama).
_STEADY_DELTA: Dict[str, Any] = {"dp": 0.0, "da": 0.0, "dd": 0.0, "direction": "steady"}


def compute_pad_intensity(pad: PADVector) -> Tuple[float, str]:
    """v0.6.0: magnitudo Euclidean PAD + label intensitas.

    mag = sqrt(P^2 + A^2 + D^2) (maks ~1.732 karena tiap sumbu di-clamp ±1).
    Label: mag <= PAD_INTENSITY_MILD_MAX (0.35) -> "mild";
    mag <= PAD_INTENSITY_MODERATE_MAX (0.75) -> "moderate"; sisanya "intense".
    """
    mag = round(math.sqrt(pad.P ** 2 + pad.A ** 2 + pad.D ** 2), 4)
    mild_max = float(getattr(config, "PAD_INTENSITY_MILD_MAX", 0.35))
    moderate_max = float(getattr(config, "PAD_INTENSITY_MODERATE_MAX", 0.75))
    if mag <= mild_max:
        return mag, "mild"
    if mag <= moderate_max:
        return mag, "moderate"
    return mag, "intense"


def compute_pad_trajectory(prev_pad: Optional[PADVector], curr_pad: PADVector) -> Dict[str, Any]:
    """v0.6.0: delta PAD + arah perubahan mood.

    dp/da/dd = selisih tiap sumbu (dibulatkan 4 desimal). Arah memakai
    PAD_TRAJECTORY_DEADBAND (0.06); urutan prioritas:
      steady       — semua |d| < deadband (atau belum ada prev_pad)
      softening    — prev P < 0 dan dp >= deadband (rasa negatif melunak)
      warming_up   — dp >= deadband dari P >= 0 (senang makin menghangat)
      escalating   — dp <= -deadband dan da >= deadband (P turun, A naik)
      calming_down — dp <= -deadband dan da <= -deadband (P dan A sama turun)
      cooling_down — da <= -deadband (arousal mendingin)
    Selain itu (mis. hanya D yang bergerak, atau P turun sendiri) -> steady.
    """
    if prev_pad is None:
        return dict(_STEADY_DELTA)
    dp = round(curr_pad.P - prev_pad.P, 4)
    da = round(curr_pad.A - prev_pad.A, 4)
    dd = round(curr_pad.D - prev_pad.D, 4)
    db = float(getattr(config, "PAD_TRAJECTORY_DEADBAND", 0.06))
    if abs(dp) < db and abs(da) < db and abs(dd) < db:
        direction = "steady"
    elif prev_pad.P < 0 and dp >= db:
        direction = "softening"
    elif dp >= db:
        direction = "warming_up"
    elif dp <= -db and da >= db:
        direction = "escalating"
    elif dp <= -db and da <= -db:
        direction = "calming_down"
    elif da <= -db:
        direction = "cooling_down"
    else:
        direction = "steady"
    return {"dp": dp, "da": da, "dd": dd, "direction": direction}


def apply_hedonic_elasticity(pad: PADVector, pad_baseline: PADVector, high_pleasure_streak: int) -> Tuple[PADVector, int]:
    """v0.6.0: elastisitas hedonik — kesenangan tinggi yang bertahan ditarik ke baseline.

    Jika pad.P > PAD_HEDONIC_PLEASURE_THRESHOLD (0.75): streak +1; saat streak
    mencapai PAD_HEDONIC_STREAK_TRIGGER (3), P ditarik ke arah baseline
    sebesar PAD_HEDONIC_ELASTIC_PULL (0.08) — hanya memotong kelebihan di
    atas baseline (tidak pernah turun di bawah baseline). Jika P <= ambang,
    streak direset ke 0. Mengembalikan (pad_baru, streak_baru); A dan D utuh.
    """
    threshold = float(getattr(config, "PAD_HEDONIC_PLEASURE_THRESHOLD", 0.75))
    trigger = int(getattr(config, "PAD_HEDONIC_STREAK_TRIGGER", 3))
    pull = float(getattr(config, "PAD_HEDONIC_ELASTIC_PULL", 0.08))
    if pad.P <= threshold:
        return pad, 0
    streak = int(high_pleasure_streak) + 1
    if streak < trigger:
        return pad, streak
    new_p = pad.P
    if pad.P > pad_baseline.P:
        new_p = max(pad_baseline.P, pad.P - pull)
    return PADVector(P=new_p, A=pad.A, D=pad.D).clamp(), streak


def classify_emotional_nuance(pad: PADVector, intensity: str, dominant_affect: str, energy: float, circadian_phase: str) -> str:
    """v0.6.0: sub-emosi halus dari oktan + intensitas + afek dominan.

    Drowsy didahulukan: energi < 0.32, atau late_night dengan A < -0.15.
    Lalu per oktan (intensitas mild/moderate/intense; afek dominan PLAY/CARE
    menggeser sebagian label):
      Exuberant  — mild: Playful (CARE: Affectionate); moderate: Cheerful
                   (PLAY: Teasing); intense: Euphoric
      Dependent  — mild: Affectionate; moderate/intense: Clingy
      Relaxed    — CARE: Affectionate (mild) / Protective (moderate+);
                   PLAY: Playful (mild/moderate) / Teasing (intense);
                   lainnya: Cozy (mild) / Content (moderate/intense)
      Docile     — CARE: Cozy (mild) / Affectionate (moderate+);
                   PLAY: Playful; lainnya: Calm (mild) / Cozy (moderate)
                   / Content (intense)
      Hostile    — mild: Defensive; moderate: Irritated; intense: Fierce
      Anxious    — mild: Flustered; moderate: Vulnerable; intense: Restless
      Disdainful — mild: Guarded; moderate: Pouty; intense: Sulky
      Bored/Depressed — mild: Lonely; moderate/intense: Melancholic
    """
    if energy < 0.32 or (circadian_phase == "late_night" and pad.A < -0.15):
        return "Drowsy"
    octant = pad.octant_label()
    if octant == "Exuberant":
        if intensity == "intense":
            return "Euphoric"
        if dominant_affect == "PLAY":
            return "Teasing" if intensity == "moderate" else "Playful"
        if dominant_affect == "CARE":
            return "Affectionate"
        return "Cheerful" if intensity == "moderate" else "Playful"
    if octant == "Dependent":
        return "Affectionate" if intensity == "mild" else "Clingy"
    if octant == "Relaxed":
        if dominant_affect == "CARE":
            return "Affectionate" if intensity == "mild" else "Protective"
        if dominant_affect == "PLAY":
            return "Teasing" if intensity == "intense" else "Playful"
        return "Cozy" if intensity == "mild" else "Content"
    if octant == "Docile":
        if dominant_affect == "CARE":
            return "Cozy" if intensity == "mild" else "Affectionate"
        if dominant_affect == "PLAY":
            return "Playful"
        if intensity == "intense":
            return "Content"
        return "Calm" if intensity == "mild" else "Cozy"
    if octant == "Hostile":
        if intensity == "intense":
            return "Fierce"
        return "Defensive" if intensity == "mild" else "Irritated"
    if octant == "Anxious":
        if intensity == "intense":
            return "Restless"
        return "Flustered" if intensity == "mild" else "Vulnerable"
    if octant == "Disdainful":
        if intensity == "intense":
            return "Sulky"
        return "Guarded" if intensity == "mild" else "Pouty"
    if octant == "Bored/Depressed":
        return "Lonely" if intensity == "mild" else "Melancholic"
    return "Calm"
