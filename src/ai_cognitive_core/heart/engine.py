import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from ai_cognitive_core.schemas import (
    DefenseMechanism,
    EmotionalDirective,
    HeartState,
    StimulusAppraisal,
    utc_now_iso,
)
from ai_cognitive_core import config
from ai_cognitive_core.heart.layers.l1_neurochemical import (
    apply_time_decay,
    current_local_hour,
    get_circadian_phase,
    update_neurochemistry,
)
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
from ai_cognitive_core.heart import phrase_bank


class HeartEngine:
    """Orkestrator 7 Layer Modul Heart (Time-Based Energy & Bubble Chat Pacing)."""

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.state = self._load()
        # v0.4.0: seed frasa terakhir yang dipakai build_directive (diagnostik).
        self.last_phrase_seed: str = ""

    def _load(self) -> HeartState:
        if self.state_path.exists():
            try:
                raw = json.loads(self.state_path.read_text(encoding="utf-8"))
                return HeartState.from_dict(raw)
            except Exception as exc:
                # v0.5.1 (P3): JANGAN reset diam-diam. Log error, amankan
                # file rusak (jangan ditimpa), lalu coba pulihkan dari .bak.
                sys.stderr.write(f"[HeartEngine] heart_state.json rusak: {exc}\n")
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                corrupt_path = self.state_path.with_name(
                    f"{self.state_path.name}.corrupt.{stamp}"
                )
                try:
                    self.state_path.rename(corrupt_path)
                    sys.stderr.write(f"[HeartEngine] file rusak dipindah ke: {corrupt_path.name}\n")
                except OSError as rename_exc:
                    sys.stderr.write(f"[HeartEngine] gagal memindah file rusak: {rename_exc}\n")
                bak_path = self.state_path.with_name(f"{self.state_path.name}.bak")
                if bak_path.exists():
                    try:
                        raw_bak = json.loads(bak_path.read_text(encoding="utf-8"))
                        recovered = HeartState.from_dict(raw_bak)
                        sys.stderr.write("[HeartEngine] state dipulihkan dari .bak\n")
                        self.save(recovered)
                        return recovered
                    except Exception as bak_exc:
                        sys.stderr.write(f"[HeartEngine] .bak juga rusak: {bak_exc}\n")
        state = HeartState()
        self.save(state)
        return state

    def save(self, state: HeartState | None = None) -> None:
        if state is not None:
            self.state = state
        self.state.last_updated_utc = utc_now_iso()
        payload = self.state.model_dump_json(indent=2)
        # v0.5.1 (P3): sebelum menimpa file yang sudah ada dan valid, simpan
        # salinan last-good (.bak). Lalu tulis atomik: tmp + os.replace.
        if self.state_path.exists():
            try:
                json.loads(self.state_path.read_text(encoding="utf-8"))
                shutil.copy2(
                    str(self.state_path),
                    str(self.state_path.with_name(f"{self.state_path.name}.bak")),
                )
            except Exception:
                pass  # File lama rusak/tidak terbaca — jangan jadikan .bak.
        tmp_path = self.state_path.with_name(f"{self.state_path.name}.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(str(tmp_path), str(self.state_path))

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
        local_hour = current_local_hour() if getattr(config, "ENABLE_CIRCADIAN_RHYTHM", True) else None
        self.state.neuro = apply_time_decay(
            self.state.neuro,
            delta_seconds,
            is_resting=self.state.is_resting,
            local_hour=local_hour,
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

        # L1: Neurochemistry + Ritme Sirkadian (v0.5.0)
        local_hour = current_local_hour() if getattr(config, "ENABLE_CIRCADIAN_RHYTHM", True) else None
        self.state.neuro = update_neurochemistry(
            self.state.neuro, appraisal, drain_energy=drain_energy, local_hour=local_hour
        )

        # L2: 7 Panksepp Circuits
        self.state.primary_affects = compute_primary_affects(
            self.state.neuro, self.state.core_needs, appraisal, att_mult
        )

        # L3: PAD Pull-Push Engine & Coactivation (terhubung ke L1/L2 + Sirkadian)
        pad_delta = appraisal_to_pad_delta(appraisal)
        if self.state.neuro.energy < 0.45:
            fatigue_ratio = (0.45 - self.state.neuro.energy) / 0.45
            pad_delta.A -= 0.08 + 0.18 * fatigue_ratio
        if local_hour is not None and get_circadian_phase(local_hour) == "late_night":
            pad_delta.A -= 0.08
        neg_affect = max(
            self.state.primary_affects.FEAR,
            self.state.primary_affects.RAGE,
            self.state.primary_affects.PANIC_GRIEF,
        )
        pos_affect = max(
            self.state.primary_affects.CARE,
            self.state.primary_affects.PLAY,
        )
        if neg_affect > pos_affect:
            pad_delta.P -= 0.25 * (neg_affect - pos_affect)
        if max(self.state.primary_affects.FEAR, self.state.primary_affects.PANIC_GRIEF) >= 0.45:
            pad_delta.D -= 0.15
        pad_delta = pad_delta.clamp()

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

        # v0.5.0: Evolusi Relasi (trust_score & relationship_stage)
        # v0.5.1 (M5): delta & ambang stage dari config.py agar benar-benar
        # bertahap (dulu hardcoded +0.012/-0.020 di sini).
        if getattr(config, "ENABLE_RELATIONSHIP_EVOLUTION", True):
            trust_delta = 0.0
            if appraisal.goal_conduciveness > 0.15 and appraisal.norm_compatibility >= 0.0:
                trust_delta = float(getattr(config, "TRUST_POS_DELTA", 0.004))
            elif appraisal.goal_conduciveness < -0.25 or appraisal.norm_compatibility < -0.25:
                trust_delta = float(getattr(config, "TRUST_NEG_DELTA", -0.012))
            if trust_delta != 0.0:
                self.state.trust_score = round(max(0.0, min(1.0, self.state.trust_score + trust_delta)), 4)
            t = self.state.trust_score
            if t >= float(getattr(config, "TRUST_STAGE_DEEP_BOND", 0.80)):
                self.state.relationship_stage = "deep_bond"
            elif t >= float(getattr(config, "TRUST_STAGE_CLOSE", 0.60)):
                self.state.relationship_stage = "close"
            elif t >= float(getattr(config, "TRUST_STAGE_WARM", 0.40)):
                self.state.relationship_stage = "warm"
            else:
                self.state.relationship_stage = "guarded"

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

        # Penentuan Gaya Bubble Chat & Panjang Ketikan berdasarkan Energi & Mood.
        # Nilai enum bubble_style DIKUNCI kontrak eksternal — jangan diubah.
        # v0.4.0: deskripsi aturan & max_words bervariasi deterministik lewat
        # phrase bank (makna & cap tidak berubah; fallback = template asli).
        if (
            self.state.active_defense == DefenseMechanism.DETACHED_PROTECTOR
            or octant in {"Hostile", "Disdainful"}
            or (user_texting_style in {"dry_short", "cold_passive_aggressive"} and p_val < 0.15)
        ):
            bubble_style = "dry_short_1_bubble"
            rec_bubbles = 1
        elif eng < 0.32:
            bubble_style = "exhausted_sleepy_1_bubble"
            rec_bubbles = 1
        elif eng >= 0.65 and p_val >= 0.25 and a_val >= 0.20:
            bubble_style = "excited_multi_bubble"
            rec_bubbles = 3
        else:
            bubble_style = "normal_1_to_2_bubbles"
            rec_bubbles = 2

        seed_material = f"{self.state.total_turns}|{octant}|{bubble_style}"
        bubble_desc, phrase_seed = phrase_bank.get_bubble_rule(bubble_style, seed_material)
        max_words = phrase_bank.select_max_words(bubble_style, seed_material)
        emoji_palette = phrase_bank.select_emoji_palette(octant, bubble_style, seed_material)
        self.last_phrase_seed = phrase_seed

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
            guilt_fragment, _ = phrase_bank.get_guilt_fragment(seed_material)
            tone_parts.append(guilt_fragment)
        if emoji_palette:
            tone_parts.append(f"EmojiHint={' '.join(emoji_palette)} (pakai seperlunya, jangan berlebihan)")

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
            emoji_palette=emoji_palette,
        )

    def apply_worker_outcome(self, status: str) -> None:
        """v0.5.0: Reaksi emosional halus saat worker bot selesai atau gagal."""
        if status == "done":
            self.state.neuro.dopamine = round(min(1.0, self.state.neuro.dopamine + 0.06), 4)
            self.state.pad_current = self.state.pad_current.clamp()
            self.state.pad_current.P = round(min(1.0, self.state.pad_current.P + 0.08), 4)
            self.save()
        elif status == "failed":
            self.state.neuro.cortisol = round(min(1.0, self.state.neuro.cortisol + 0.08), 4)
            self.state.pad_current.P = round(max(-1.0, self.state.pad_current.P - 0.10), 4)
            self.state.pad_current.A = round(min(1.0, self.state.pad_current.A + 0.08), 4)
            self.save()
