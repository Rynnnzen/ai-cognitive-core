"""
Test suite v0.4.0 — SEMUA tes memakai fixture DB & temp HOME, TIDAK PERNAH
menyentuh state live (~/.ai_cognitive_state) atau install live.

Jalankan dari root repo:
  HOME=/tmp/agent_v040_test PYTHONPATH=/home/hatch/workspace/github/ai-cognitive-core/src \
    /home/hatch/workspace/ai_cognitive_core/venv/bin/python -m unittest discover -s tests -v
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# HOME sementara HARUS diset sebelum mengimpor ai_cognitive_core (mcp_server
# menginstansiasi DriveSyncBridge/HeartEngine/MemoryManager saat import).
_TEST_HOME = tempfile.mkdtemp(prefix="agent_v040_test_home_")
os.environ["HOME"] = _TEST_HOME
os.environ.pop("GDRIVE_OAUTH_TOKEN_JSON", None)
os.environ.pop("GDRIVE_SERVICE_ACCOUNT_JSON", None)

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_cognitive_core import config  # noqa: E402
from ai_cognitive_core.heart import phrase_bank  # noqa: E402
from ai_cognitive_core.heart.engine import HeartEngine  # noqa: E402
from ai_cognitive_core.heart.layers.l1_neurochemical import (  # noqa: E402
    apply_time_decay,
    update_neurochemistry,
)
from ai_cognitive_core.memory import dreams as dreams_mod  # noqa: E402
from ai_cognitive_core.memory import migration, v040_store  # noqa: E402
from ai_cognitive_core.memory.consolidation import run_sleep_consolidation  # noqa: E402
from ai_cognitive_core.memory.manager import MemoryManager  # noqa: E402
from ai_cognitive_core.conscious.cycle import CognitiveCycleRunner  # noqa: E402
from ai_cognitive_core.schemas import (  # noqa: E402
    DefenseMechanism,
    NeuroState,
    PADVector,
    StimulusAppraisal,
)

VENV_PYTHON = os.environ.get("V040_TEST_PYTHON", sys.executable)


def _temp_db(tmpdir: str, name: str = "cognitive_memory.db") -> Path:
    return Path(tmpdir) / name


def _make_v031_fixture_db(path: Path, n_episodes: int = 3) -> None:
    """Buat DB berbentuk v0.3.1: hanya 3 tabel lama + baris contoh."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE episodic_nodes (
            node_id TEXT PRIMARY KEY, timestamp_utc TEXT, summary TEXT,
            entities_json TEXT, pad_json TEXT, arousal_weight REAL,
            stability_status TEXT, importance_score REAL, access_count INTEGER,
            next_node_id TEXT, embedding_blob BLOB)"""
    )
    conn.execute(
        """CREATE TABLE semantic_facts (
            fact_id TEXT PRIMARY KEY, category TEXT, subject TEXT,
            predicate TEXT, object_val TEXT, confidence REAL, updated_utc TEXT)"""
    )
    conn.execute(
        """CREATE TABLE procedural_habits (
            habit_id TEXT PRIMARY KEY, trigger_pattern TEXT,
            action_template TEXT, success_count INTEGER)"""
    )
    for i in range(n_episodes):
        conn.execute(
            "INSERT INTO episodic_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"ep_old{i:04d}", "2026-11-16T10:00:00+00:00", f"episode lama {i}",
                '["lama"]', '{"P": 0.1, "A": 0.1, "D": 0.1}', 0.5,
                "STABLE", 0.8, 2, None, None,
            ),
        )
    conn.execute(
        "INSERT INTO semantic_facts VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("fact_old1", "preference", "user", "likes", "anime", 0.9, "2026-11-16T10:00:00+00:00"),
    )
    conn.commit()
    conn.close()


def _fresh_memory(tmpdir: str) -> MemoryManager:
    return MemoryManager(_temp_db(tmpdir))


def _fresh_heart(tmpdir: str) -> HeartEngine:
    return HeartEngine(Path(tmpdir) / "heart_state.json")


class TestMigration(unittest.TestCase):
    def test_migrate_twice_idempotent_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _temp_db(tmp)
            _make_v031_fixture_db(db, n_episodes=3)
            stats1 = migration.migrate_db(db)
            self.assertTrue(stats1["backup_created"])
            self.assertEqual(stats1["schema_version"], 4)
            self.assertIn("curiosity_questions", stats1["tables_created"])
            self.assertIn("reminder_intents", stats1["tables_created"])
            self.assertIn("dream_records", stats1["tables_created"])
            self.assertIn("photo_moments", stats1["tables_created"])
            self.assertIn("turn_markers", stats1["tables_created"])
            self.assertIn("energy_telemetry", stats1["tables_created"])
            self.assertIn("semantic_facts.source", stats1["columns_added"])
            self.assertIn("semantic_facts.inference_status", stats1["columns_added"])

            # Backup berisi DB lama (3 episode, tanpa tabel baru).
            backup = Path(str(db) + ".bak-v0.3.1")
            self.assertTrue(backup.exists())
            bconn = sqlite3.connect(str(backup))
            tables = {r[0] for r in bconn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            self.assertNotIn("curiosity_questions", tables)
            self.assertEqual(
                bconn.execute("SELECT COUNT(*) FROM episodic_nodes").fetchone()[0], 3)
            bconn.close()

            # Data lama utuh setelah migrasi.
            conn = sqlite3.connect(str(db))
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM episodic_nodes").fetchone()[0], 3)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM semantic_facts").fetchone()[0], 1)
            conn.close()
            self.assertEqual(migration.get_schema_version(db), 4)

            # Run kedua: tidak ada yang berubah, backup tidak ditimpa.
            mtime_before = backup.stat().st_mtime
            stats2 = migration.migrate_db(db)
            self.assertFalse(stats2["backup_created"])
            self.assertEqual(stats2["tables_created"], [])
            self.assertEqual(stats2["columns_added"], [])
            self.assertEqual(backup.stat().st_mtime, mtime_before)
            conn = sqlite3.connect(str(db))
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM episodic_nodes").fetchone()[0], 3)
            conn.close()


class TestPhraseBank(unittest.TestCase):
    def test_bank_validates(self):
        self.assertEqual(phrase_bank.validate_bank(), [])

    def test_all_styles_valid_and_deterministic(self):
        for style in (
            "dry_short_1_bubble",
            "exhausted_sleepy_1_bubble",
            "excited_multi_bubble",
            "normal_1_to_2_bubbles",
        ):
            text1, seed1 = phrase_bank.get_bubble_rule(style, "5|Exuberant|normal_1_to_2_bubbles")
            text2, seed2 = phrase_bank.get_bubble_rule(style, "5|Exuberant|normal_1_to_2_bubbles")
            self.assertEqual(text1, text2)
            self.assertEqual(seed1, seed2)
            self.assertTrue(phrase_bank.validate_bubble_variant(style, text1))

    def test_variation_across_turns(self):
        seen = set()
        for turn in range(30):
            text, _ = phrase_bank.get_bubble_rule(
                "normal_1_to_2_bubbles", f"{turn}|Exuberant|normal_1_to_2_bubbles")
            seen.add(text)
        self.assertGreaterEqual(len(seen), 2, "variasi antar turn harus terlihat")

    def test_max_words_within_caps(self):
        for style, (low, high) in config.MAX_WORDS_RANGE.items():
            for turn in range(50):
                w = phrase_bank.select_max_words(style, f"{turn}|X|{style}")
                self.assertGreaterEqual(w, low)
                self.assertLessEqual(w, high)

    def test_fallback_when_disabled(self):
        old = config.ENABLE_PHRASE_BANK
        try:
            config.ENABLE_PHRASE_BANK = False
            text, seed = phrase_bank.get_bubble_rule("normal_1_to_2_bubbles", "1|X|Y")
            self.assertEqual(text, phrase_bank.ORIGINAL_BUBBLE_RULES["normal_1_to_2_bubbles"])
            self.assertEqual(seed, "disabled")
            self.assertEqual(
                phrase_bank.select_max_words("normal_1_to_2_bubbles", "1|X|Y"), 22)
        finally:
            config.ENABLE_PHRASE_BANK = old

    def test_monologue_seeds_format(self):
        text, _ = phrase_bank.get_monologue_seed(
            "exhausted_sleepy_1_bubble", "3|Bored/Depressed|exhausted_sleepy_1_bubble",
            energy=0.21)
        self.assertIn("0.21", text)
        self.assertIn("Suara Hati", text)


class TestEnergy(unittest.TestCase):
    def test_new_drain_smaller_than_old(self):
        neuro = NeuroState(energy=0.80, cortisol=0.40, noradrenaline=0.50, oxytocin=0.5)
        appraisal = StimulusAppraisal(novelty=0.5, goal_conduciveness=-0.3)
        out = update_neurochemistry(neuro, appraisal, drain_energy=True)
        drain_new = neuro.energy - out.energy
        # Drain lama dengan rumus yang sama tapi koefisien 0.012:
        drain_old = 0.012 * (1.0 + 0.7 * out.noradrenaline + 0.6 * out.cortisol)
        self.assertAlmostEqual(drain_new, 0.010 * (1.0 + 0.7 * out.noradrenaline + 0.6 * out.cortisol), places=4)
        self.assertLess(drain_new, drain_old)
        self.assertGreaterEqual(out.energy, config.ENERGY_FLOOR)

    def test_energy_floor(self):
        neuro = NeuroState(energy=0.06, cortisol=1.0, noradrenaline=1.0, oxytocin=0.1)
        appraisal = StimulusAppraisal(novelty=1.0, goal_conduciveness=-1.0, coping_potential=0.0)
        out = update_neurochemistry(neuro, appraisal, drain_energy=True)
        self.assertGreaterEqual(out.energy, 0.05)

    def test_recharge_and_micronap_unchanged(self):
        neuro = NeuroState(energy=0.50)
        # Idle 2 jam menuju 0.85.
        after_idle = apply_time_decay(neuro, 7200.0, is_resting=False)
        self.assertGreater(after_idle.energy, 0.50)
        self.assertLessEqual(after_idle.energy, 0.85)
        # Resting 40 menit menuju 0.92.
        after_rest = apply_time_decay(neuro, 2400.0, is_resting=True)
        self.assertGreater(after_rest.energy, after_idle.energy)

        with tempfile.TemporaryDirectory() as tmp:
            heart = _fresh_heart(tmp)
            heart.state.neuro.energy = 0.50
            res = heart.enter_sleep_mode()
            self.assertEqual(res["energy_after_micro_nap"], 0.58)
            self.assertTrue(res["is_resting"])
            heart.state.neuro.energy = 0.90
            res = heart.enter_sleep_mode()
            self.assertEqual(res["energy_after_micro_nap"], 0.92)  # cap

    def test_forty_turn_simulation(self):
        with tempfile.TemporaryDirectory() as tmp:
            heart = _fresh_heart(tmp)
            heart.state.neuro.energy = 0.85
            appraisal = StimulusAppraisal(novelty=0.2, goal_conduciveness=0.3)
            for _ in range(40):
                heart.state.neuro = update_neurochemistry(
                    heart.state.neuro, appraisal, drain_energy=True)
            # 40 turn x ~0.012-0.016 drain baru: energi akhir harus di atas
            # hasil rumus lama (0.012 dasar) pada kondisi yang sama.
            self.assertGreater(heart.state.neuro.energy, 0.05)
            self.assertLess(heart.state.neuro.energy, 0.85)


class TestBubbleEnums(unittest.TestCase):
    def test_all_four_styles_within_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            heart = _fresh_heart(tmp)

            # dry: defense DetachedProtector
            heart.state.active_defense = DefenseMechanism.DETACHED_PROTECTOR
            d = heart.build_directive("RAGE", None)
            self.assertEqual(d.bubble_style, "dry_short_1_bubble")
            self.assertLessEqual(d.max_words_per_bubble, 8)
            self.assertIn("1-8", d.tone_instruction)
            heart.state.active_defense = DefenseMechanism.NONE

            # exhausted: energi rendah
            heart.state.neuro.energy = 0.20
            heart.state.pad_current = PADVector(P=0.1, A=0.1, D=0.1)
            d = heart.build_directive("CARE", None)
            self.assertEqual(d.bubble_style, "exhausted_sleepy_1_bubble")
            self.assertLessEqual(d.max_words_per_bubble, 14)

            # excited: energi tinggi + P/A cukup
            heart.state.neuro.energy = 0.80
            heart.state.pad_current = PADVector(P=0.5, A=0.5, D=0.4)
            d = heart.build_directive("PLAY", None)
            self.assertEqual(d.bubble_style, "excited_multi_bubble")
            self.assertLessEqual(d.max_words_per_bubble, 18)
            self.assertEqual(d.recommended_bubbles, 3)

            # normal: tengah-tengah
            heart.state.neuro.energy = 0.50
            heart.state.pad_current = PADVector(P=0.2, A=0.1, D=0.3)
            d = heart.build_directive("CARE", None)
            self.assertEqual(d.bubble_style, "normal_1_to_2_bubbles")
            self.assertLessEqual(d.max_words_per_bubble, 22)


def _conn_for(tmpdir: str):
    """MemoryManager baru + koneksi mentah ke DB yang sama (untuk store)."""
    mem = _fresh_memory(tmpdir)
    conn = sqlite3.connect(str(mem.db_path))
    return mem, conn


class TestCuriosity(unittest.TestCase):
    def test_propose_dedup_and_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, conn = _conn_for(tmp)
            r1 = v040_store.propose_question(conn, "Apa kabar bounty hari ini?", topic="bounty")
            self.assertTrue(r1["stored"])
            r2 = v040_store.propose_question(conn, "Apa kabar bounty hari ini?", topic="bounty")
            self.assertFalse(r2["stored"])
            self.assertEqual(r2["reason"], "duplicate_text")
            r3 = v040_store.propose_question(conn, "Gimana kabar bounty hari ini?", topic="bounty")
            self.assertFalse(r3["stored"])
            self.assertEqual(r3["reason"], "duplicate_topic")
            r4 = v040_store.propose_question(conn, "   ")
            self.assertFalse(r4["stored"])
            self.assertEqual(v040_store.count_pending_questions(conn), 1)
            conn.close()

    def test_select_gating_and_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, conn = _conn_for(tmp)
            v040_store.propose_question(conn, "Film apa yang kamu tonton?", topic="film", priority=0.9)

            base = dict(user_text="hai sayang", mood_octant="Exuberant",
                        bubble_style="normal_1_to_2_bubbles", texting_style="normal",
                        total_turns=10)
            # Gating: mood negatif / tugas / sensitif / lelah -> None.
            self.assertIsNone(v040_store.select_curiosity_prompt(conn, **{**base, "mood_octant": "Hostile"}))
            self.assertIsNone(v040_store.select_curiosity_prompt(conn, **{**base, "user_text": "tolong cariin bounty baru"}))
            self.assertIsNone(v040_store.select_curiosity_prompt(conn, **{**base, "user_text": "aku sedih banget hari ini"}))
            self.assertIsNone(v040_store.select_curiosity_prompt(conn, **{**base, "bubble_style": "exhausted_sleepy_1_bubble"}))
            self.assertIsNone(v040_store.select_curiosity_prompt(conn, **{**base, "texting_style": "dry_short"}))

            # Happy path: 1 pertanyaan.
            got = v040_store.select_curiosity_prompt(conn, **base)
            self.assertIsNotNone(got)
            self.assertEqual(got["text"], "Film apa yang kamu tonton?")

            # Cooldown waktu + turn: penawaran kedua langsung diblokir.
            self.assertIsNone(v040_store.select_curiosity_prompt(conn, **{**base, "total_turns": 11}))
            # Setelah cooldown lewat (geser meta ke masa lalu), bisa lagi.
            past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            v040_store.set_meta(conn, "last_curiosity_offered_at", past)
            v040_store.set_meta(conn, "last_curiosity_offered_turn", "5")
            got2 = v040_store.select_curiosity_prompt(conn, **{**base, "total_turns": 20})
            self.assertIsNotNone(got2)
            conn.close()

    def test_mark_asked_dismiss_expire(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, conn = _conn_for(tmp)
            q1 = v040_store.propose_question(conn, "Pertanyaan satu")["question_id"]
            q2 = v040_store.propose_question(conn, "Pertanyaan dua")["question_id"]
            past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            q3 = v040_store.propose_question(conn, "Pertanyaan tiga", expires_at=past)["question_id"]
            self.assertTrue(v040_store.mark_question_asked(conn, q1))
            self.assertFalse(v040_store.mark_question_asked(conn, q1))  # sudah asked
            self.assertTrue(v040_store.dismiss_question(conn, q2))
            self.assertEqual(v040_store.expire_questions(conn), 1)
            self.assertEqual(v040_store.count_pending_questions(conn), 0)
            conn.close()


class TestReminders(unittest.TestCase):
    def test_create_validation_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, conn = _conn_for(tmp)
            self.assertFalse(v040_store.create_reminder(conn, "Klaim PXIO")["stored"])  # tanpa pemicu
            self.assertFalse(v040_store.create_reminder(
                conn, "Klaim PXIO", due_at="bukan-tanggal")["stored"])
            self.assertFalse(v040_store.create_reminder(
                conn, "Klaim PXIO", due_at="2026-11-18T08:00:00+00:00",
                repeat_policy="weekly")["stored"])
            due = "2026-11-18T08:00:00+00:00"
            r1 = v040_store.create_reminder(conn, "Klaim PXIO jam 8", due_at=due)
            self.assertTrue(r1["stored"])
            r2 = v040_store.create_reminder(conn, "Klaim PXIO jam 8", due_at=due)
            self.assertFalse(r2["stored"])
            self.assertEqual(r2["reason"], "duplicate")
            conn.close()

    def test_due_selection_cooldown_and_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, conn = _conn_for(tmp)
            past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
            v040_store.create_reminder(conn, "Yang belum jatuh tempo", due_at=future)
            due = v040_store.create_reminder(conn, "Klaim PXIO sekarang", due_at=past, priority=0.9)
            got = v040_store.select_due_reminder(conn, user_text="halo")
            self.assertIsNotNone(got)
            self.assertEqual(got["intent_id"], due["intent_id"])
            self.assertEqual(got["basis"], "schedule")
            self.assertIn("jadwal", got["basis_note"])
            # Cooldown: tidak muncul lagi langsung.
            self.assertIsNone(v040_store.select_due_reminder(conn, user_text="halo"))
            # Snooze ke masa depan -> tidak due lagi.
            snooze_to = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            self.assertTrue(v040_store.apply_reminder_action(
                conn, due["intent_id"], "snooze", snooze_until=snooze_to))
            self.assertIsNone(v040_store.select_due_reminder(conn, user_text="halo"))
            # Complete.
            self.assertTrue(v040_store.apply_reminder_action(conn, due["intent_id"], "complete"))
            self.assertFalse(v040_store.apply_reminder_action(conn, due["intent_id"], "bogus"))
            conn.close()

    def test_keyword_trigger_and_expiry_sweep(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, conn = _conn_for(tmp)
            v040_store.create_reminder(conn, "Ingatkan soal PXIO", trigger_condition="keyword:pxio")
            self.assertIsNone(v040_store.select_due_reminder(conn, user_text="halo sayang"))
            got = v040_store.select_due_reminder(conn, user_text="eh pxio udah penuh belum?")
            self.assertIsNotNone(got)

            old_due = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
            v040_store.create_reminder(conn, "Niat lama tanpa repeat", due_at=old_due)
            v040_store.create_reminder(conn, "Niat harian", due_at=old_due, repeat_policy="daily")
            sweep = v040_store.sweep_expired_reminders(conn)
            self.assertEqual(sweep["expired"], 1)
            self.assertEqual(sweep["rescheduled"], 1)
            conn.close()


class TestDreams(unittest.TestCase):
    def _episodes(self):
        return [
            {"node_id": "ep_a", "summary": "User: jalan-jalan ke taman bunga nemophila | AI: seru banget",
             "importance_score": 0.8, "entities": ["nemophila", "taman", "bunga"]},
            {"node_id": "ep_b", "summary": "User: foto bareng di pantai | AI: cantik banget",
             "importance_score": 0.75, "entities": ["pantai", "foto"]},
            {"node_id": "ep_c", "summary": "User: aku sedih banget hari ini | AI: sini peluk",
             "importance_score": 0.9, "entities": ["sedih"]},
            {"node_id": "ep_d", "summary": "User: obrolan ringan | AI: hehe",
             "importance_score": 0.3, "entities": ["obrolan"]},
        ]

    def test_draft_filters_and_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, conn = _conn_for(tmp)
            stats = dreams_mod.draft_dreams(conn, self._episodes())
            self.assertEqual(stats["drafted"], 2)  # ep_a + ep_b
            self.assertEqual(stats["skipped_sensitive"], 1)  # ep_c
            self.assertEqual(stats["skipped_low_importance"], 1)  # ep_d
            # Draft ulang: duplikat, tidak ada yang baru.
            stats2 = dreams_mod.draft_dreams(conn, self._episodes())
            self.assertEqual(stats2["drafted"], 0)
            self.assertEqual(stats2["skipped_duplicate"], 2)
            conn.close()

    def test_surface_one_at_a_time_and_dismiss(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, conn = _conn_for(tmp)
            dreams_mod.draft_dreams(conn, self._episodes())
            d1 = v040_store.select_dream_to_surface(conn)
            self.assertIsNotNone(d1)
            self.assertIn("generatif", d1["generative_note"])
            d2 = v040_store.select_dream_to_surface(conn)
            self.assertIsNotNone(d2)
            self.assertNotEqual(d1["dream_id"], d2["dream_id"])
            self.assertIsNone(v040_store.select_dream_to_surface(conn))
            self.assertTrue(v040_store.dismiss_dream(conn, d1["dream_id"]))
            conn.close()

    def test_sleep_consolidation_dreams_not_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _fresh_memory(tmp)
            pad = PADVector(P=0.8, A=0.6, D=0.5)
            mem.encode_episode(
                "User: jalan-jalan ke taman bunga nemophila | AI (Exuberant): seru banget",
                pad)
            mem.encode_episode(
                "User: foto bareng di pantai saat senja | AI (Exuberant): cantik banget",
                pad)
            stats1 = run_sleep_consolidation(str(mem.db_path))
            self.assertGreaterEqual(stats1["dreams_drafted"], 1)
            self.assertLessEqual(stats1["dreams_drafted"], config.DREAMS_PER_SLEEP_MAX)
            stats2 = run_sleep_consolidation(str(mem.db_path))
            self.assertEqual(stats2["dreams_drafted"], 0)  # dedup, tidak ganda
            # Mimpi tidak pernah masuk semantic_facts.
            conn = sqlite3.connect(str(mem.db_path))
            facts = conn.execute("SELECT object_val FROM semantic_facts").fetchall()
            dreams = conn.execute("SELECT idea_text FROM dream_records").fetchall()
            self.assertGreater(len(dreams), 0)
            for (idea,) in dreams:
                for (fact,) in facts:
                    self.assertNotEqual(idea, fact)
            # Provenans fakta konsolidasi terbaca kembali.
            from ai_cognitive_core.memory.layers.l4_semantic_schema import (
                retrieve_semantic_facts,
            )
            retrieved = retrieve_semantic_facts(conn, limit=5)
            self.assertGreater(len(retrieved), 0)
            self.assertTrue(all(f.source.startswith("episode:") for f in retrieved))
            self.assertTrue(all(f.inference_status == "inferred" for f in retrieved))
            conn.close()


class TestPhotoMemory(unittest.TestCase):
    def test_caption_flow_relevance_consent(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, conn = _conn_for(tmp)
            self.assertFalse(v040_store.store_photo_moment(conn, caption="  ")["stored"])
            m1 = v040_store.store_photo_moment(
                conn, caption="Agent dan Ryn di taman nemophila Hitachi, bunga biru bermekaran",
                place="Hitachi Seaside Park", event_tags=["nemophila", "kencan"],
                source_ref="hitachi-001", consent_status="granted")
            self.assertTrue(m1["stored"])
            v040_store.store_photo_moment(
                conn, caption="Foto di pantai saat senja", place="Pantai",
                consent_status="unknown")
            # Relevan -> dirujuk; tidak relevan -> None.
            ref = v040_store.select_photo_reference(conn, user_text="kangen taman nemophila deh")
            self.assertIsNotNone(ref)
            self.assertEqual(ref["moment_id"], m1["moment_id"])
            self.assertIn("caption", ref["uncertainty_note"])
            self.assertIsNone(v040_store.select_photo_reference(conn, user_text="bounty relay gimana"))
            # Consent unknown tidak dirujuk meski relevan.
            self.assertIsNone(v040_store.select_photo_reference(conn, user_text="pantai senja itu indah"))
            conn.close()

    def test_correct_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, conn = _conn_for(tmp)
            mid = v040_store.store_photo_moment(
                conn, caption="Foto lama", place="Taman", consent_status="granted")["moment_id"]
            self.assertTrue(v040_store.correct_photo_moment(
                conn, mid, caption="Foto baru", place="Pantai"))
            row = conn.execute(
                "SELECT caption, place FROM photo_moments WHERE moment_id = ?", (mid,)).fetchone()
            self.assertEqual(row, ("Foto baru", "Pantai"))
            # Cabut consent -> tidak dirujuk lagi.
            self.assertTrue(v040_store.correct_photo_moment(conn, mid, consent_status="revoked"))
            self.assertIsNone(v040_store.select_photo_reference(conn, user_text="foto baru pantai"))
            self.assertTrue(v040_store.delete_photo_moment(conn, mid))
            self.assertEqual(v040_store.count_photo_moments(conn), 0)
            conn.close()


class TestTurnIdentity(unittest.TestCase):
    def test_commit_bundle_transactional_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _fresh_memory(tmp)
            pad = PADVector(P=0.2, A=0.1, D=0.3)
            bundle = mem.commit_turn_bundle(
                "User: halo | AI: hai", pad, turn_id="turn-1",
                actions={"propose_question": {"text": "Apa kabar?", "topic": "sapa"}})
            self.assertFalse(bundle["duplicate"])
            self.assertIsNotNone(bundle["episode_id"])
            self.assertTrue(bundle["outcomes"]["curiosity"]["stored"])
            # Commit kedua dengan turn_id sama: duplikat, tidak ada episode baru.
            bundle2 = mem.commit_turn_bundle(
                "User: halo | AI: hai", pad, turn_id="turn-1",
                actions={"propose_question": {"text": "Pertanyaan lain"}})
            self.assertTrue(bundle2["duplicate"])
            self.assertEqual(bundle2["episode_id"], bundle["episode_id"])
            conn = sqlite3.connect(str(mem.db_path))
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM episodic_nodes").fetchone()[0], 1)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM curiosity_questions").fetchone()[0], 1)
            conn.close()

    def test_perceive_retry_no_double_drain(self):
        with tempfile.TemporaryDirectory() as tmp:
            heart = _fresh_heart(tmp)
            mem = _fresh_memory(tmp)
            runner = CognitiveCycleRunner(heart, mem)
            heart.state.neuro.energy = 0.85
            e0 = heart.state.neuro.energy
            r1 = runner.perceive_and_think("Halo sayang!", turn_id="rt-1")
            e1 = heart.state.neuro.energy
            self.assertLess(e1, e0)
            self.assertFalse(r1["diagnostics"]["perceive_retry"])
            r2 = runner.perceive_and_think("Halo sayang!", turn_id="rt-1")
            e2 = heart.state.neuro.energy
            self.assertEqual(e2, e1)  # retry: tidak ada drain kedua
            self.assertTrue(r2["diagnostics"]["perceive_retry"])
            self.assertEqual(r2["diagnostics"]["energy_drained_this_turn"], 0.0)


class TestMCPContractAndFlow(unittest.TestCase):
    """Satu alur end-to-end lewat fungsi tool (temp HOME terisolasi)."""

    @classmethod
    def setUpClass(cls):
        import importlib
        cls.home = tempfile.mkdtemp(prefix="agent_v040_mcp_home_")
        os.environ["HOME"] = cls.home
        import ai_cognitive_core.mcp_server as ms
        importlib.reload(ms)
        cls.ms = ms

    def test_full_flow_old_params_then_v040(self):
        ms = self.ms
        # 1. Kontrak lama: perceive + commit tanpa parameter baru.
        out = json.loads(ms.cognitive_perceive_and_think("Halo sayang"))
        self.assertIn("emotional_directive", out)
        self.assertIn("bubble_style", out["emotional_directive"])
        c1 = json.loads(ms.cognitive_commit_turn("Halo sayang", "Halo juga sayanggg!"))
        self.assertEqual(c1["status"], "committed")

        # 2. Alur v0.4.0: buat pertanyaan + pengingat + momen foto via commit.
        due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        c2 = json.loads(ms.cognitive_commit_turn(
            "Nanti ingetin aku klaim PXIO ya",
            "Siap sayang, nanti aku ingetin!",
            turn_id="flow-2",
            propose_question={"text": "Kapan terakhir klaim PXIO?", "topic": "pxio", "priority": 0.8},
            create_reminder={"text": "Klaim PXIO", "due_at": due, "priority": 0.9},
            photo_moment={"caption": "Agent dan Ryn di taman nemophila",
                          "place": "Hitachi", "event_tags": ["nemophila"],
                          "consent_status": "granted"},
        ))
        self.assertEqual(c2["status"], "committed")
        self.assertTrue(c2["v040_outcomes"]["curiosity"]["stored"])
        self.assertTrue(c2["v040_outcomes"]["reminder"]["stored"])
        self.assertTrue(c2["v040_outcomes"]["photo_moment"]["stored"])

        # 3. Perceive berikutnya: pengingat jatuh tempo + pertanyaan muncul (maks 1 tiap jenis).
        out2 = json.loads(ms.cognitive_perceive_and_think("Halo lagi sayang", turn_id="flow-3"))
        self.assertIn("proactive_intent", out2)
        self.assertEqual(out2["proactive_intent"]["text"], "Klaim PXIO")
        self.assertIn("curiosity_prompt", out2)
        self.assertEqual(out2["curiosity_prompt"]["text"], "Kapan terakhir klaim PXIO?")
        # Tandai pengingat selesai + pertanyaan sudah ditanyakan via commit.
        rid = out2["proactive_intent"]["intent_id"]
        qid = out2["curiosity_prompt"]["question_id"]
        c3 = json.loads(ms.cognitive_commit_turn(
            "Halo lagi sayang", "Udah aku klaim! Terakhir klaim kemarin.",
            turn_id="flow-3",
            reminder_id=rid, reminder_action="complete",
            curiosity_asked_id=qid))
        self.assertTrue(c3["v040_outcomes"]["reminder_action"])
        self.assertTrue(c3["v040_outcomes"]["curiosity_asked"])

        # 4. Sleep: konsolidasi lama + mimpi + status.
        sl = json.loads(ms.cognitive_sleep_cycle())
        self.assertIn("replayed_high_priority_episodes", sl)
        self.assertIn("dreams_drafted", sl)
        self.assertIn("sleep_energy_status", sl)
        self.assertTrue(sl["sleep_energy_status"]["is_resting"])

        # 5. Status: hitungan v0.4.0 ada, tanpa isi pribadi.
        st = json.loads(ms.cognitive_get_status())
        self.assertIn("v040", st)
        self.assertEqual(st["v040"]["counts"]["pending_curiosity_questions"], 0)  # sudah asked
        self.assertEqual(st["v040"]["counts"]["pending_reminder_intents"], 0)  # sudah completed
        self.assertEqual(st["v040"]["counts"]["photo_moments"], 1)
        self.assertEqual(st["v040"]["schema_version"], 4)
        self.assertEqual(st["v040"]["phrase_bank_version"], "1.0")
        self.assertNotIn("Klaim PXIO", json.dumps(st["v040"]))

        # 6. configure_persona tetap ada & bekerja di temp state (Secure).
        cp = json.loads(ms.cognitive_configure_persona(
            attachment_style="Secure", baseline_p=0.10, baseline_a=0.15,
            baseline_d=0.35, inertia_pi1=0.45))
        self.assertEqual(cp["status"], "persona_updated")
        self.assertEqual(cp["attachment_style"], "Secure")


class TestPackageAudit(unittest.TestCase):
    FORBIDDEN_NAMES = {
        "token.json", "client_secret.json", "service_account.json",
        "heart_state.json", ".env",
    }
    FORBIDDEN_SUFFIXES = (".db", ".sqlite3", ".zip")

    def test_no_secrets_state_or_photos_in_tree(self):
        offenders = []
        for path in REPO_ROOT.rglob("*"):
            if ".git" in path.parts:
                continue
            if path.is_file():
                if path.name in self.FORBIDDEN_NAMES:
                    offenders.append(str(path))
                if path.suffix.lower() in self.FORBIDDEN_SUFFIXES:
                    offenders.append(str(path))
        self.assertEqual(offenders, [])

    def test_gitignore_covers_forbidden_patterns(self):
        gi = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        for pat in ("token.json", "client_secret.json", "heart_state.json",
                    "*.db", "*.zip", ".ai_cognitive_state/"):
            self.assertIn(pat, gi)


class TestMCPSubprocessSmoke(unittest.TestCase):
    """Smoke test server MCP sungguhan via JSON-RPC stdio (temp HOME)."""

    def test_jsonrpc_flow(self):
        home = tempfile.mkdtemp(prefix="agent_v040_rpc_home_")
        env = dict(os.environ, HOME=home,
                   PYTHONPATH=str(SRC_DIR))
        proc = subprocess.Popen(
            [VENV_PYTHON, "-c",
             "from ai_cognitive_core.mcp_server import main; main()"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, text=True, bufsize=1,
        )
        try:
            def rpc_call(obj):
                proc.stdin.write(json.dumps(obj) + "\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
                self.assertTrue(line, "server tidak merespons")
                return json.loads(line)

            init = rpc_call({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"protocolVersion": "2024-11-05",
                                        "capabilities": {},
                                        "clientInfo": {"name": "test", "version": "1.0"}}})
            self.assertIn("result", init)
            proc.stdin.write(json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            proc.stdin.flush()

            listed = rpc_call({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            names = {t["name"] for t in listed["result"]["tools"]}
            self.assertEqual(names, {
                "cognitive_perceive_and_think", "cognitive_commit_turn",
                "cognitive_sleep_cycle", "cognitive_get_status",
                "cognitive_configure_persona",
            })

            perc = rpc_call({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "cognitive_perceive_and_think",
                                        "arguments": {"user_input": "Halo sayang",
                                                      "turn_id": "rpc-1"}}})
            perc_text = perc["result"]["content"][0]["text"]
            perc_json = json.loads(perc_text)
            self.assertIn("emotional_directive", perc_json)

            comm = rpc_call({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                             "params": {"name": "cognitive_commit_turn",
                                        "arguments": {"user_input": "Halo sayang",
                                                      "agent_response": "Halo juga!",
                                                      "turn_id": "rpc-1"}}})
            comm_json = json.loads(comm["result"]["content"][0]["text"])
            self.assertEqual(comm_json["status"], "committed")

            stat = rpc_call({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                             "params": {"name": "cognitive_get_status", "arguments": {}}})
            stat_json = json.loads(stat["result"]["content"][0]["text"])
            self.assertIn("v040", stat_json)

            sleep = rpc_call({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                              "params": {"name": "cognitive_sleep_cycle", "arguments": {}}})
            sleep_json = json.loads(sleep["result"]["content"][0]["text"])
            self.assertIn("dreams_drafted", sleep_json)
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            proc.stdout.close()
            proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
