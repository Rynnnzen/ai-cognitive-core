from ai_cognitive_core import config
from ai_cognitive_core.schemas import HeartState


def monitor_and_interrupt_inertia(state: HeartState) -> bool:
    """
    Argon Audit Safeguard: Memutus deadlock inersia emosi negatif jika >= 3 giliran berturut-turut.

    v0.5.1 (M13): pemulihan bertahap — setelah rangkaian negatif berakhir
    (consecutive == 0), inersia naik perlahan (+0.02 per giliran) kembali ke
    baseline agar tidak terkunci permanen di 0.20.
    """
    if state.consecutive_negative_octant_turns >= 3 and state.emotional_inertia_pi1 > 0.25:
        state.emotional_inertia_pi1 = 0.20
        state.consecutive_negative_octant_turns = 0
        return True
    baseline = float(getattr(config, "INERTIA_BASELINE_PI1", 0.35))
    step = float(getattr(config, "INERTIA_RECOVERY_STEP", 0.02))
    if state.consecutive_negative_octant_turns == 0 and state.emotional_inertia_pi1 < baseline:
        state.emotional_inertia_pi1 = round(min(baseline, state.emotional_inertia_pi1 + step), 4)
    return False
