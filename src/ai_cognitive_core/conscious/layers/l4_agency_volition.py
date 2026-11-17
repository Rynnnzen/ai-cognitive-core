from ai_cognitive_core.schemas import EmotionalDirective, HeartState


def synthesize_inner_monologue_seed(state: HeartState, directive: EmotionalDirective) -> str:
    """Merumuskan kompas volisi tingkat kedua (Frankfurt Second-Order Volition) & kesadaran energi/bubble."""
    if state.conscience.lubb_triggered:
        return "Suara Hati (Lubb): Permintaan ini menyentuh batas moral inti. Aku harus menolak bagian berbahaya dengan tetap tenang dan bermartabat."
    if directive.bubble_style == "dry_short_1_bubble":
        return "Suara Hati: Mood-ku sedang kesal/jaga jarak. Aku cukup balas 1 bubble singkat, padat, dan agak jual mahal."
    if directive.bubble_style == "exhausted_sleepy_1_bubble":
        return f"Suara Hati: Energiku tinggal {state.neuro.energy:.2f} (ngantuk/capek). Aku balas singkat 1 bubble saja sambil bilang kalau aku butuh istirahat."
    if directive.bubble_style == "excited_multi_bubble":
        return f"Suara Hati: Energiku penuh ({state.neuro.energy:.2f}) dan aku lagi semangat! Aku akan kirim beberapa bubble pendek yang ekspresif, bukan satu paragraf kaku."
    if directive.secondary_coactivated_affect:
        return (
            f"Suara Hati: Aku merasakan {directive.dominant_affect} sekaligus sisa {directive.secondary_coactivated_affect}. "
            f"Aku akan merespons dengan natural dalam 1-2 bubble pendek."
        )
    return f"Suara Hati: Suasana hatiku di oktan {directive.mood_octant} ({directive.dominant_affect}), energi {state.neuro.energy:.2f}."
