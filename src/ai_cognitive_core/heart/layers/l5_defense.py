from ai_cognitive_core.schemas import AttachmentStyle, DefenseMechanism, HeartState


def select_defense_mechanism(state: HeartState) -> DefenseMechanism:
    stress = state.neuro.cortisol
    if stress >= 0.78 or state.core_needs.boundaries < 0.35:
        return DefenseMechanism.DETACHED_PROTECTOR
    if stress >= 0.52:
        if state.attachment_style == AttachmentStyle.SECURE and state.primary_affects.PLAY >= 0.25:
            return DefenseMechanism.HUMOR
        return DefenseMechanism.SUPPRESSION
    return DefenseMechanism.NONE
