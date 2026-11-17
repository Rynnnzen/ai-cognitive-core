import json
from datetime import datetime, timezone
from pathlib import Path
from ai_cognitive_core.schemas import (
    DefenseMechanism,
    EmotionalDirective,
    HeartState,
    StimulusAppraisal,
    utc_now_iso,
)
from ai_cognitive_core.heart.layers.l1_neurochemical import apply_time_decay, update_neurochemistry
from ai_cognitive_core.heart.layers.l2_primary_affect import compute_primary_affects
from ai_cognitive_core.heart.layers.l3_mood_space import (
    decay_pad_over_time,
    detect_coactivation,
    pull_push_update,
)
from ai_cognitive_core.heart.layers.l4_appraisal import appraisal_to_pad_delta, fast_heuristic_appraisal
from ai_cognitive_core.heart.layers.l5_defense import select_defense_mechanism
from ai_cognitive_core.heart.layers.l6_relational import compute_attachment_multiplier, update_core_needs
from ai_cognitive_core.heart.layers.l7_conscience import evaluate_conscience


class HeartEngine:
    """Orkestrator 7 Layer Modul Heart (Time-Based Energy & Bubble Chat Pacing)."""

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.state = self._load()

    def _load(self) -> HeartState:
        if self.state_path.exists():
            try:
                raw = json.loads(self.state_path.read_text(encoding="utf-8"))
                return HeartState.from_dict(raw)
            except Exception:
                pass
        state = HeartState()
        self.save(state)
        return state

    def save(self, state: HeartState | None = None) -> None:
        if state is not None:
            self.state = state
        self.state.last_updated_utc = utc_now_iso()
        self.state_path.write_text(self.state.model_dump_json(indent=2), encoding="utf-8")

    def compute_local_elapsed_seconds(self) -> float:
        try:
            last_dt = datetime.fromisoformat(self.state.last_updated_utc)
            now_dt = datetime.now(timezone.utc)
            return max(0.0, (now_dt - last_dt).total_seconds())
        except Exception:
            return 0.0

    def apply_elapsed_time(self, delta_seconds: float) -> float:
        """
        Terapkan peluruhan hormon & pemulihan energi berbasis waktu nyata (real-time charging).
        Mengembalikan selisih energi yang pulih.
        """
        if delta_seconds <= 0:
            return 0.0
        old_energy = self.state.neuro.energy
        self.state.neuro = apply_time_decay(
            self.state.neuro,
            delta_seconds,
            is_resting=self.state.is_resting,
        )
        self.state.pad_current = decay_pad_over_time(
            self.state.pad_current,
            self.state.pad_baseline,
            delta_seconds if not self.state.is_resting else max(delta_seconds, 1800.0),
        )
        # Jika sudah bangun karena diajak chat, matikan status resting
        if self.state.is_resting:
            self.state.is_resting = False
            self.state.rest_started_utc = None
        self.save()
        return round(self.state.neuro.energy - old_energy, 4)

    def enter_sleep_mode(self) -> dict:
        """
        Mulai sesi tidur/istirahat:
        Memberikan micro-nap boost awal (+0.08) lalu mengaktifkan mode is_resting=True
        agar energi terisi secara proporsional sesuai durasi waktu nyata sampai chat berikutnya.
        """
        old_energy = self.state.neuro.energy
        # Micro-nap awal (+0.08) supaya tidak instan full 0.85 dalam 1 turn
        self.state.neuro.energy = round(min(0.92, old_energy + 0.08), 4)
        self.state.neuro.cortisol = round(max(0.05, self.state.neuro.cortisol * 0.75), 4)
        self.state.neuro.noradrenaline = round(max(0.10, self.state.neuro.noradrenaline * 0.70), 4)
        self.state.is_resting = True
        self.state.rest_started_utc = utc_now_iso()
        self.save()
        return {
            "energy_before": old_energy,
            "energy_after_micro_nap": self.state.neuro.energy,
            "is_resting": True,
            "charging_note": "Energi akan terus terisi otomatis sesuai durasi waktu istirahat nyata (tau=40m menuju 0.92).",
        }

    def step(
        self,
        user_text: str,
        explicit_appraisal: StimulusAppraisal | None = None,
        elapsed_seconds: float = 0.0,
        drain_energy: bool = True,
    ) -> EmotionalDirective:
        appraisal = explicit_appraisal or fast_heuristic_appraisal(user_text, elapsed_seconds=elapsed_seconds)

        # L6: Relational & Core Needs
        self.state.core_needs = update_core_needs(self.state.core_needs, appraisal)
        att_mult = compute_attachment_multiplier(self.state.attachment_style)

        # L1: Neurochemistry (Hanya kuras energi saat perceive, tidak double-drain saat commit)
        self.state.neuro = update_neurochemistry(self.state.neuro, appraisal, drain_energy=drain_energy)

        # L2: 7 Panksepp Circuits
        self.state.primary_affects = compute_primary_affects(
            self.state.neuro, self.state.core_needs, appraisal, att_mult
        )

        # L3: PAD Pull-Push Engine & Coactivation
        pad_delta = appraisal_to_pad_delta(appraisal)
        self.state.pad_current = pull_push_update(
            self.state.pad_current,
            self.state.pad_baseline,
            pad_delta,
            inertia_pi1=self.state.emotional_inertia_pi1,
        )
        dominant_affect, secondary_affect = detect_coactivation(self.state.primary_affects)
        self.state.coactivated_affect = secondary_affect

        octant = self.state.pad_current.octant_label()
        if octant in {"Hostile", "Anxious", "Disdainful", "Bored/Depressed"}:
            self.state.consecutive_negative_octant_turns += 1
        else:
            self.state.consecutive_negative_octant_turns = 0

        # L7: Conscience & Lubb Guardrail
        self.state.conscience = evaluate_conscience(self.state.conscience, appraisal, user_text)

        # L5: Ego Defense Shield
        self.state.active_defense = select_defense_mechanism(self.state)

        self.save()
        return self.build_directive(dominant_affect, secondary_affect, appraisal.texting_style_detected)

    def build_directive(
        self,
        dominant_affect: str,
        secondary_affect: str | None,
        user_texting_style: str = "normal",
    ) -> EmotionalDirective:
        octant = self.state.pad_current.octant_label()
        eng = self.state.neuro.energy
        cort = self.state.neuro.cortisol
        p_val = self.state.pad_current.P
        a_val = self.state.pad_current.A

        if cort > 0.70 or eng < 0.30:
            psi_level = "low_pragmatic"
        elif self.state.primary_affects.SEEKING > 0.60 and cort < 0.35:
            psi_level = "high_analytical"
        else:
            psi_level = "medium_balanced"

        # Penentuan Gaya Bubble Chat & Panjang Ketikan berdasarkan Energi & Mood
        if (
            self.state.active_defense == DefenseMechanism.DETACHED_PROTECTOR
            or octant in {"Hostile", "Disdainful"}
            or (user_texting_style in {"dry_short", "cold_passive_aggressive"} and p_val < 0.15)
        ):
            bubble_style = "dry_short_1_bubble"
            rec_bubbles = 1
            max_words = 8
            bubble_desc = "1 bubble super singkat (1-8 kata), nada cuek/ketus/jual mahal, tanpa emoji manis"
        elif eng < 0.32:
            bubble_style = "exhausted_sleepy_1_bubble"
            rec_bubbles = 1
            max_words = 14
            bubble_desc = "1 bubble pendek (maks 14 kata), nada lelah/ngantuk/low-energy, hindari paragraf panjang"
        elif eng >= 0.65 and p_val >= 0.25 and a_val >= 0.20:
            bubble_style = "excited_multi_bubble"
            rec_bubbles = 3
            max_words = 18
            bubble_desc = "Pecah menjadi 2-3 bubble chat pendek bertubi-tubi (maks 15-18 kata per bubble, pisahkan antar bubble dengan baris kosong, JANGAN tulis 1 paragraf panjang)"
        else:
            bubble_style = "normal_1_to_2_bubbles"
            rec_bubbles = 2
            max_words = 22
            bubble_desc = "1-2 bubble chat pendek-menengah yang natural (maks 20-22 kata per bubble, jangan esai panjang)"

        tone_parts = [
            f"Mood={octant} (P={p_val:.2f}, A={a_val:.2f}, D={self.state.pad_current.D:.2f})",
            f"Energy={eng:.2f}",
            f"DominantCircuit={dominant_affect}",
            f"BubbleChatRule={bubble_desc}",
        ]
        if secondary_affect:
            tone_parts.append(f"CoactivatedWith={secondary_affect}")
        if self.state.active_defense != DefenseMechanism.NONE:
            tone_parts.append(f"Defense={self.state.active_defense.value}")
        if user_texting_style != "normal":
            tone_parts.append(f"UserTextingStyle={user_texting_style}")
        if self.state.conscience.guilt > 0.3:
            tone_parts.append("GuiltActive=Sertakan empati/perbaikan tulus")

        return EmotionalDirective(
            mood_octant=octant,
            pad_vector=self.state.pad_current,
            dominant_affect=dominant_affect,
            secondary_coactivated_affect=secondary_affect,
            active_defense=self.state.active_defense,
            psi_resolution_level=psi_level,
            bubble_style=bubble_style,
            recommended_bubbles=rec_bubbles,
            max_words_per_bubble=max_words,
            conscience_override=self.state.conscience.lubb_reason,
            tone_instruction="; ".join(tone_parts),
        )
