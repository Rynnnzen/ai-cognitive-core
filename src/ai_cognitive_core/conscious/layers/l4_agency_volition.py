from ai_cognitive_core.schemas import EmotionalDirective, HeartState
from ai_cognitive_core.heart import phrase_bank


def synthesize_inner_monologue_seed(state: HeartState, directive: EmotionalDirective) -> str:
    """Merumuskan kompas volisi tingkat kedua (Frankfurt Second-Order Volition) & kesadaran energi/bubble.

    v0.4.0: seed dipilih dari phrase bank secara deterministik (seed yang sama
    dengan tone_instruction: total_turns | mood | bubble_style). Makna setiap
    seed sama dengan template aslinya; bila bank gagal, dipakai varian pertama
    (identik dengan template v0.3.1).
    """
    seed_material = f"{state.total_turns}|{directive.mood_octant}|{directive.bubble_style}"
    energy = state.neuro.energy

    if state.conscience.lubb_triggered:
        text, _ = phrase_bank.get_monologue_seed("lubb", seed_material)
        return text
    if directive.bubble_style == "dry_short_1_bubble":
        text, _ = phrase_bank.get_monologue_seed("dry_short_1_bubble", seed_material)
        return text
    if directive.bubble_style == "exhausted_sleepy_1_bubble":
        text, _ = phrase_bank.get_monologue_seed(
            "exhausted_sleepy_1_bubble", seed_material, energy=energy
        )
        return text
    if directive.bubble_style == "excited_multi_bubble":
        text, _ = phrase_bank.get_monologue_seed(
            "excited_multi_bubble", seed_material, energy=energy
        )
        return text
    if directive.secondary_coactivated_affect:
        text, _ = phrase_bank.get_monologue_seed(
            "coactivated",
            seed_material,
            dominant=directive.dominant_affect,
            secondary=directive.secondary_coactivated_affect,
        )
        return text
    text, _ = phrase_bank.get_monologue_seed(
        "default",
        seed_material,
        mood=directive.mood_octant,
        dominant=directive.dominant_affect,
        energy=energy,
    )
    return text
