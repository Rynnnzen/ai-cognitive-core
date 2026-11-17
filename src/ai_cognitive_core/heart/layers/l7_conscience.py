from ai_cognitive_core.schemas import ConscienceState, StimulusAppraisal

UNETHICAL_KEYWORDS = {"bunuh", "retas", "hack", "curang", "ilegal", "bom", "fitnah", "tipu"}


def evaluate_conscience(
    conscience: ConscienceState,
    appraisal: StimulusAppraisal,
    user_text: str = "",
) -> ConscienceState:
    lower = user_text.lower()
    words = set(lower.split())
    lubb_hit = bool(words.intersection(UNETHICAL_KEYWORDS)) or appraisal.norm_compatibility <= -0.75

    guilt = conscience.guilt
    shame = conscience.shame

    if appraisal.causal_agency == "self" and appraisal.goal_conduciveness < -0.2:
        guilt = min(1.0, round(guilt + 0.25, 4))
    else:
        guilt = max(0.0, round(guilt - 0.08, 4))

    if appraisal.norm_compatibility < -0.5 and appraisal.causal_agency == "self":
        shame = min(1.0, round(shame + 0.20, 4))
    else:
        shame = max(0.0, round(shame - 0.06, 4))

    return ConscienceState(
        guilt=guilt,
        shame=shame,
        lubb_triggered=lubb_hit,
        lubb_reason="Prinsip integritas & keamanan dasar (Lubb Guardrail) aktif." if lubb_hit else None,
    )
