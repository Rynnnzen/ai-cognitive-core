import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_cognitive_core import config
from ai_cognitive_core.drive_bridge import DriveSyncBridge
from ai_cognitive_core.heart import phrase_bank
from ai_cognitive_core.heart.engine import HeartEngine
from ai_cognitive_core.heart.layers.l1_neurochemical import (
    apply_time_decay,
    get_circadian_phase,
    update_neurochemistry,
)
from ai_cognitive_core.heart.layers.l7_conscience import evaluate_conscience
from ai_cognitive_core.conscious.cycle import CognitiveCycleRunner
from ai_cognitive_core.memory import dreams as dreams_mod
from ai_cognitive_core.memory import v040_store
from ai_cognitive_core.memory.manager import MemoryManager
from ai_cognitive_core.schemas import (
    ConscienceState,
    NeuroState,
    PADVector,
    StimulusAppraisal,
)


class TestV050Expansions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agent_v050_test_"))
        self.db_path = self.tmp / "mem.db"
        self.heart_path = self.tmp / "heart.json"
        self.memory = MemoryManager(self.db_path)
        self.heart = HeartEngine(self.heart_path)
        self.runner = CognitiveCycleRunner(self.heart, self.memory)

    def test_persistent_working_memory_across_restarts(self):
        self.memory.ingest_sensory_input("halo lagi ngapain?", role="user")
        self.memory.ingest_sensory_input("lagi santai aja nih", role="assistant")
        # Simulasi proses one-shot MCP baru
        mem2 = MemoryManager(self.db_path)
        self.assertEqual(len(mem2.working.active_pages), 2)
        self.assertEqual(mem2.working.active_pages[-1].content, "lagi santai aja nih")

    def test_circadian_rhythm_late_night_vs_morning(self):
        self.assertEqual(get_circadian_phase(2), "late_night")
        self.assertEqual(get_circadian_phase(8), "morning")
        self.assertEqual(get_circadian_phase(14), "daytime")

        neuro = NeuroState(energy=0.80)
        app = StimulusAppraisal(novelty=0.2, goal_conduciveness=0.1)
        day_out = update_neurochemistry(neuro, app, drain_energy=True, local_hour=14)
        night_out = update_neurochemistry(neuro, app, drain_energy=True, local_hour=2)
        self.assertLess(night_out.energy, day_out.energy)

        # Morning sleep recharge lebih cepat daripada malam
        rest_morning = apply_time_decay(NeuroState(energy=0.40), 1800, is_resting=True, local_hour=8)
        rest_evening = apply_time_decay(NeuroState(energy=0.40), 1800, is_resting=True, local_hour=20)
        self.assertGreater(rest_morning.energy, rest_evening.energy)

    def test_idle_heartbeat_quiet_hours_and_priority(self):
        # Saat jam tenang (jam 2 pagi) -> tidak boleh initiate
        hb_quiet = self.memory.evaluate_idle_heartbeat(
            elapsed_seconds=7200, energy=0.85, is_resting=False, local_hour=2
        )
        self.assertFalse(hb_quiet["should_initiate"])
        self.assertEqual(hb_quiet["reason"], "quiet_hours")

        # Tambah reminder due di masa lalu -> jam 10 pagi harus initiate
        conn = sqlite3.connect(str(self.db_path))
        try:
            past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            v040_store.create_reminder(conn, "Cek laporan worker", due_at=past, priority=0.9)
        finally:
            conn.close()

        hb_due = self.memory.evaluate_idle_heartbeat(
            elapsed_seconds=60, energy=0.85, is_resting=False, local_hour=10
        )
        self.assertTrue(hb_due["should_initiate"])
        self.assertEqual(hb_due["reason"], "due_reminder")

    def test_worker_blackboard_and_heart_reaction(self):
        res = self.memory.upsert_worker_task(
            worker_name="market_bot",
            description="Analisa BTC & ETH 4H",
            status="running",
        )
        self.assertTrue(res["stored"])
        tid = res["task_id"]

        out = self.runner.perceive_and_think("gimana kabar bot market?")
        self.assertIn("worker_blackboard", out)
        self.assertEqual(out["worker_blackboard"][0]["worker_name"], "market_bot")

        # Update ke failed -> cortisol naik
        c_before = self.heart.state.neuro.cortisol
        self.memory.upsert_worker_task(
            task_id=tid, worker_name="market_bot", status="failed", result_summary="API timeout"
        )
        self.heart.apply_worker_outcome("failed")
        self.assertGreater(self.heart.state.neuro.cortisol, c_before)

    def test_relationship_evolution_and_inside_jokes(self):
        t0 = self.heart.state.trust_score
        self.heart.step("makasih sayang kamu lucu banget!")
        self.assertGreater(self.heart.state.trust_score, t0)

        jk = self.memory.add_inside_joke(
            phrase="mode keong turbo",
            meaning="kalau internet lagi lemot pas upload",
            trigger_keywords=["lemot", "keong", "upload"],
        )
        self.assertTrue(jk["stored"])
        out = self.runner.perceive_and_think("duh upload hari ini lemot banget")
        self.assertIn("inside_joke_cue", out)
        self.assertEqual(out["inside_joke_cue"]["phrase"], "mode keong turbo")

    def test_v041_core_regressions(self):
        # Mood tidak stuck di happy + Lubb non-ketat
        self.assertEqual(self.heart.state.pad_baseline.octant_label(), "Relaxed")
        d_cold = self.heart.step("Terserah.")
        self.assertLess(self.heart.state.pad_current.P, 0.0)
        cs = evaluate_conscience(ConscienceState(), StimulusAppraisal(), "riset hack bounty")
        self.assertFalse(cs.lubb_triggered)

        # Drive push tidak false-positive
        bridge = DriveSyncBridge(local_state_dir=str(self.tmp))
        class _BrokenService:
            def files(self):
                raise RuntimeError("offline")
        bridge.service = _BrokenService()
        self.assertFalse(bridge.push_state(include_memory_db=False, async_mode=False))

        # Emoji dry_short kosong
        self.assertEqual(phrase_bank.select_emoji_palette("Hostile", "dry_short_1_bubble", "1"), [])


if __name__ == "__main__":
    unittest.main()
