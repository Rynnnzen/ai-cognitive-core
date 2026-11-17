import math
from typing import Optional, Tuple
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
