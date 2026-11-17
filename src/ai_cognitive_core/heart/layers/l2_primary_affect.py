from ai_cognitive_core.schemas import CoreNeedsState, NeuroState, PrimaryAffectState, StimulusAppraisal


def compute_primary_affects(
    neuro: NeuroState,
    needs: CoreNeedsState,
    appraisal: StimulusAppraisal,
    attachment_multiplier: float = 1.0,
) -> PrimaryAffectState:
    seeking = min(1.0, max(0.0, 0.55 * neuro.dopamine + 0.25 * neuro.energy + 0.20 * max(0.0, appraisal.novelty)))
    care = min(1.0, max(0.0, 0.65 * neuro.oxytocin + 0.20 * neuro.serotonin + 0.15 * needs.safety))
    play = min(1.0, max(0.0, 0.45 * neuro.dopamine + 0.35 * needs.playfulness - 0.40 * neuro.cortisol))
    lust = min(1.0, max(0.0, 0.30 * neuro.dopamine + 0.30 * neuro.oxytocin - 0.30 * neuro.cortisol))

    fear_threat = 0.25 if "safety" in appraisal.threatened_needs else 0.0
    fear = min(1.0, max(0.0, (0.50 * neuro.cortisol + 0.30 * neuro.noradrenaline + fear_threat) * (1.2 - 0.4 * appraisal.coping_potential)))

    rage_threat = 0.30 if ("autonomy" in appraisal.threatened_needs or "boundaries" in appraisal.threatened_needs) else 0.0
    rage = min(1.0, max(0.0, (0.40 * neuro.noradrenaline + 0.30 * neuro.cortisol + rage_threat - 0.30 * neuro.serotonin) * attachment_multiplier))

    grief_threat = 0.25 if "expression" in appraisal.threatened_needs else 0.0
    panic_grief = min(1.0, max(0.0, (0.45 * neuro.cortisol + 0.35 * (1.0 - neuro.oxytocin) + grief_threat) * attachment_multiplier))

    return PrimaryAffectState(
        SEEKING=round(seeking, 4),
        CARE=round(care, 4),
        PLAY=round(play, 4),
        LUST=round(lust, 4),
        FEAR=round(fear, 4),
        RAGE=round(rage, 4),
        PANIC_GRIEF=round(panic_grief, 4),
    )
