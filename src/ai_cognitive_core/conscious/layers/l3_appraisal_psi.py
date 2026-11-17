from ai_cognitive_core.schemas import HeartState


def compute_psi_parameters(state: HeartState) -> dict:
    """Modulator PSI Dörner: Menyetel kedalaman resolusi berpikir & ambang seleksi."""
    cort = state.neuro.cortisol
    eng = state.neuro.energy
    resolution = round(max(0.2, min(1.0, eng * (1.1 - 0.6 * cort))), 3)
    selection_threshold = round(max(0.2, min(0.9, 0.4 + 0.4 * cort)), 3)
    return {
        "psi_resolution": resolution,
        "psi_selection_threshold": selection_threshold,
    }
