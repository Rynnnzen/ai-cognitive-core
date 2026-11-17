from ai_cognitive_core.schemas import ConsciousBroadcast, EmotionalDirective
from ai_cognitive_core.heart.engine import HeartEngine
from ai_cognitive_core.memory.manager import MemoryManager
from ai_cognitive_core.conscious.layers.l1_preconscious import bind_coalition_candidates
from ai_cognitive_core.conscious.layers.l2_salience_gwt import ignite_global_workspace
from ai_cognitive_core.conscious.layers.l3_appraisal_psi import compute_psi_parameters
from ai_cognitive_core.conscious.layers.l4_agency_volition import synthesize_inner_monologue_seed
from ai_cognitive_core.conscious.layers.l5_metacognition import monitor_and_interrupt_inertia


class CognitiveCycleRunner:
    """Orkestrator Siklus Kognitif Tertutup (Heart + Conscious + Memory)."""

    def __init__(self, heart: HeartEngine, memory: MemoryManager):
        self.heart = heart
        self.memory = memory

    def perceive_and_think(self, user_input: str, elapsed_seconds: float = 0.0) -> dict:
        # 1. Memory L1 & L2
        self.memory.ingest_sensory_input(user_input, role="user")

        # 2. Heart 7-Layer Fast Step (dengan deteksi micro-cues & jeda waktu balas)
        directive: EmotionalDirective = self.heart.step(
            user_input,
            elapsed_seconds=elapsed_seconds,
            drain_energy=True,
        )

        # 3. Memory L3 (Bounded PPR) & L4 (Semantic Schema)
        episodes, facts, ca1_mismatch = self.memory.retrieve_context(
            user_input, self.heart.state.pad_current
        )

        # 4. Conscious L1 & L2 (GWT Ignition)
        candidates = bind_coalition_candidates(
            self.memory.working.active_pages,
            episodes,
            directive.dominant_affect,
        )
        broadcast: ConsciousBroadcast = ignite_global_workspace(candidates, max_chunks=4)

        # 5. Conscious L3, L4, L5 (PSI, Inner Monologue, Metacognitive Inertia Check)
        psi_params = compute_psi_parameters(self.heart.state)
        interrupted = monitor_and_interrupt_inertia(self.heart.state)
        if interrupted:
            self.heart.save()

        broadcast.inner_monologue = synthesize_inner_monologue_seed(self.heart.state, directive)
        broadcast.inertia_interrupted = interrupted

        return {
            "emotional_directive": directive.model_dump(),
            "conscious_broadcast": broadcast.model_dump(),
            "psi_modulation": psi_params,
            "ca1_novelty_mismatch": ca1_mismatch,
            "recalled_episodes": [ep.model_dump() for ep in episodes],
            "semantic_facts": [f.model_dump() for f in facts],
        }
