from ai_cognitive_core.schemas import AttachmentStyle, CoreNeedsState, StimulusAppraisal


def update_core_needs(needs: CoreNeedsState, appraisal: StimulusAppraisal) -> CoreNeedsState:
    data = needs.model_dump()
    for k in data:
        if k in appraisal.threatened_needs:
            data[k] = max(0.0, round(data[k] - 0.12, 4))
        elif k in appraisal.fulfilled_needs:
            data[k] = min(1.0, round(data[k] + 0.08, 4))
        else:
            data[k] = round(data[k] + 0.02 * (0.75 - data[k]), 4)
    return CoreNeedsState(**data)


def compute_attachment_multiplier(style: AttachmentStyle) -> float:
    if style == AttachmentStyle.ANXIOUS:
        return 1.30
    if style == AttachmentStyle.AVOIDANT:
        return 0.85
    return 1.0
