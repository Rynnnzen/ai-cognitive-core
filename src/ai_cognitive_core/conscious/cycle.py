from typing import Optional
from ai_cognitive_core import config
from ai_cognitive_core.schemas import ConsciousBroadcast, EmotionalDirective
from ai_cognitive_core.heart.engine import HeartEngine
from ai_cognitive_core.heart.layers.l1_neurochemical import current_local_hour, get_circadian_phase
from ai_cognitive_core.heart import phrase_bank
from ai_cognitive_core.heart.layers.l4_appraisal import fast_heuristic_appraisal
from ai_cognitive_core.memory.manager import MemoryManager
from ai_cognitive_core.conscious.layers.l1_preconscious import bind_coalition_candidates
from ai_cognitive_core.conscious.layers.l2_salience_gwt import ignite_global_workspace
from ai_cognitive_core.conscious.layers.l3_appraisal_psi import compute_psi_parameters
from ai_cognitive_core.conscious.layers.l4_agency_volition import synthesize_inner_monologue_seed
from ai_cognitive_core.conscious.layers.l5_metacognition import monitor_and_interrupt_inertia

# Mimpi hanya ditawarkan saat suasana santai/positif (bukan saat tugas/tegang).
_DREAM_FRIENDLY_OCTANTS = {"Exuberant", "Relaxed", "Dependent", "Docile", "Bored/Depressed"}


def _safe_optional(fn, default):
    """v0.5.1 (M10): satu fitur opsional yang gagal tidak boleh mematikan
    seluruh giliran — kembalikan nilai default dan lanjut."""
    try:
        return fn()
    except Exception:
        return default


class CognitiveCycleRunner:
    """Orkestrator Siklus Kognitif Tertutup (Heart + Conscious + Memory)."""

    def __init__(self, heart: HeartEngine, memory: MemoryManager):
        self.heart = heart
        self.memory = memory

    def perceive_and_think(
        self,
        user_input: str,
        elapsed_seconds: float = 0.0,
        turn_id: Optional[str] = None,
    ) -> dict:
        # 0. v0.4.0 — identitas giliran: retry perceive dengan turn_id yang sama
        # TIDAK BOLEH menguras energi dua kali.
        perceive_retry = False
        drain_energy = True
        if turn_id:
            marker = self.memory.get_turn_marker(turn_id)
            if marker and marker["drained"]:
                drain_energy = False
                perceive_retry = True

        # 1. Memory L1 & L2
        self.memory.ingest_sensory_input(user_input, role="user")

        # v0.4.0: hitung giliran (dipakai seed phrase bank & telemetri).
        # Dinaikkan SEBELUM step agar build_directive memakai nomor turn ini.
        if not perceive_retry:
            self.heart.state.total_turns += 1
        energy_before = self.heart.state.neuro.energy

        # 2. Heart 7-Layer Fast Step (dengan deteksi micro-cues & jeda waktu balas)
        directive: EmotionalDirective = self.heart.step(
            user_input,
            elapsed_seconds=elapsed_seconds,
            drain_energy=drain_energy,
        )

        # v0.4.0: telemetri energi (tanpa konten percakapan).
        energy_after = self.heart.state.neuro.energy
        drain_actual = round(energy_before - energy_after, 4) if drain_energy else 0.0
        self.memory.record_energy_telemetry(
            turn_id=turn_id,
            drain=drain_actual if drain_energy else None,
            energy_after=energy_after,
            noradrenaline=self.heart.state.neuro.noradrenaline,
            cortisol=self.heart.state.neuro.cortisol,
        )
        if turn_id:
            self.memory.mark_turn_perceived(turn_id, drained=drain_energy)

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
        broadcast: ConsciousBroadcast = ignite_global_workspace(
            candidates, max_chunks=config.GWT_MAX_CHUNKS
        )

        # 5. Conscious L3, L4, L5 (PSI, Inner Monologue, Metacognitive Inertia Check)
        psi_params = compute_psi_parameters(self.heart.state)
        inertia_before = self.heart.state.emotional_inertia_pi1
        interrupted = monitor_and_interrupt_inertia(self.heart.state)
        # v0.5.1 (M13): simpan juga bila inersia berubah karena pemulihan
        # bertahap (bukan hanya saat safeguard memutus) — proses MCP
        # one-shot akan kehilangan perubahan yang tidak disimpan.
        if interrupted or self.heart.state.emotional_inertia_pi1 != inertia_before:
            self.heart.save()

        broadcast.inner_monologue = synthesize_inner_monologue_seed(self.heart.state, directive)
        broadcast.inertia_interrupted = interrupted

        result = {
            "emotional_directive": directive.model_dump(),
            "conscious_broadcast": broadcast.model_dump(),
            "psi_modulation": psi_params,
            "ca1_novelty_mismatch": ca1_mismatch,
            "recalled_episodes": [ep.model_dump() for ep in episodes],
            "semantic_facts": [f.model_dump() for f in facts],
        }

        # 5b. v0.4.1/v0.5.0 — L5 Procedural Habits, Worker Blackboard, Inside Joke, Sirkadian & Relasi
        # v0.5.1 (M10): pemanggilan fitur opsional dibungkus agar satu
        # kegagalan tidak mematikan seluruh giliran chat.
        habits = _safe_optional(
            lambda: self.memory.match_procedural_habits(
                user_input, top_k=getattr(config, "HABIT_TOP_K", 3)
            ),
            [],
        )
        if habits:
            result["learned_habits"] = habits

        active_workers = _safe_optional(
            lambda: self.memory.list_worker_tasks(limit=5, only_active=True),
            [],
        )
        if active_workers:
            result["worker_blackboard"] = active_workers

        joke = _safe_optional(lambda: self.memory.match_inside_joke(user_input), None)
        if joke:
            result["inside_joke_cue"] = joke

        local_hour = current_local_hour()
        result["circadian"] = {
            "local_hour": local_hour,
            "phase": get_circadian_phase(local_hour),
        }
        result["relationship"] = {
            "trust_score": self.heart.state.trust_score,
            "stage": self.heart.state.relationship_stage,
        }

        # 6. v0.4.0 — konten proaktif (masing-masing MAKSIMAL 1 per perceive).
        texting_style = fast_heuristic_appraisal(user_input).texting_style_detected
        curiosity = _safe_optional(
            lambda: self.memory.select_curiosity_prompt(
                user_text=user_input,
                mood_octant=directive.mood_octant,
                bubble_style=directive.bubble_style,
                texting_style=texting_style,
                total_turns=self.heart.state.total_turns,
            ),
            None,
        )
        if curiosity:
            result["curiosity_prompt"] = curiosity

        reminder = _safe_optional(
            lambda: self.memory.select_due_reminder(user_text=user_input),
            None,
        )
        if reminder:
            result["proactive_intent"] = reminder

        if directive.mood_octant in _DREAM_FRIENDLY_OCTANTS and not any(
            kw in user_input.lower() for kw in config.CURIOSITY_TASK_KEYWORDS
        ):
            dream = _safe_optional(lambda: self.memory.select_dream_to_surface(), None)
            if dream:
                result["dream_idea"] = dream

        photo = _safe_optional(
            lambda: self.memory.select_photo_reference(user_text=user_input),
            None,
        )
        if photo:
            result["photo_reference"] = photo

        result["diagnostics"] = {
            "phrase_bank_version": phrase_bank.PHRASE_BANK_VERSION,
            "phrase_seed": self.heart.last_phrase_seed,
            "turn_id": turn_id,
            "perceive_retry": perceive_retry,
            "energy_drained_this_turn": drain_actual,
        }
        return result
