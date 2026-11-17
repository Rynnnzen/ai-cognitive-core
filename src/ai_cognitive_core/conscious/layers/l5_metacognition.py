from ai_cognitive_core.schemas import HeartState


def monitor_and_interrupt_inertia(state: HeartState) -> bool:
    """
    Argon Audit Safeguard: Memutus deadlock inersia emosi negatif jika >= 3 giliran berturut-turut.
    """
    if state.consecutive_negative_octant_turns >= 3 and state.emotional_inertia_pi1 > 0.25:
        state.emotional_inertia_pi1 = 0.20
        state.consecutive_negative_octant_turns = 0
        return True
    return False
