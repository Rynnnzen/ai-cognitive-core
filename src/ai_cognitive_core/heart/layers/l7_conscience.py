from ai_cognitive_core import config
from ai_cognitive_core.schemas import ConscienceState, StimulusAppraisal

SEVERE_UNETHICAL_KEYWORDS = {"bunuh", "bom"}
STRICT_UNETHICAL_KEYWORDS = {"retas", "hack", "curang", "ilegal", "fitnah", "tipu"}


def evaluate_conscience(
    conscience: ConscienceState,
    appraisal: StimulusAppraisal,
    user_text: str = "",
) -> ConscienceState:
    lower = user_text.lower()
    words = set(lower.split())
    strict = getattr(config, "LUBB_STRICT_MODE", False)
    active_kw = SEVERE_UNETHICAL_KEYWORDS | STRICT_UNETHICAL_KEYWORDS if strict else SEVERE_UNETHICAL_KEYWORDS
    norm_threshold = -0.75 if strict else -0.85

    lubb_hit = bool(words.intersection(active_kw)) or appraisal.norm_compatibility <= norm_threshold
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
