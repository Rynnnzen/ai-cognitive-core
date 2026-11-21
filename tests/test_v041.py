import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_cognitive_core import config
from ai_cognitive_core.drive_bridge import DriveSyncBridge
from ai_cognitive_core.heart import phrase_bank
from ai_cognitive_core.heart.engine import HeartEngine
from ai_cognitive_core.conscious.cycle import CognitiveCycleRunner
from ai_cognitive_core.memory import dreams as dreams_mod
from ai_cognitive_core.memory import v040_store
from ai_cognitive_core.memory.manager import MemoryManager
from ai_cognitive_core.schemas import PADVector


class TestV041Features(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agent_v041_test_"))
        self.db_path = self.tmp / "mem.db"
        self.heart_path = self.tmp / "heart.json"
        self.memory = MemoryManager(self.db_path)
        self.heart = HeartEngine(self.heart_path)
        self.runner = CognitiveCycleRunner(self.heart, self.memory)

    def test_dream_story_and_anti_skip(self):
        conn = sqlite3.connect(str(self.db_path))
        try:
            eps = [
                {
                    "node_id": "ep_personal_1",
                    "summary": "Kita jalan sore di pantai sambil update cerita seru tentang senja",
                    "importance_score": 0.35,
                    "entities": ["pantai", "senja"],
                },
                {
                    "node_id": "ep_tech_1",
                    "summary": "Setup oauth token sqlite migration dan debug mcp server",
                    "importance_score": 0.90,
                    "entities": ["oauth", "sqlite"],
                },
            ]
            stats = dreams_mod.draft_dreams(conn, eps)
            self.assertEqual(stats["drafted"], 1)
            self.assertEqual(stats["skipped_technical"], 1)
            d = v040_store.select_dream_to_surface(conn)
            self.assertIsNotNone(d)
            self.assertTrue(d["dream_story"])
            self.assertTrue(d["idea_text"])
        finally:
            conn.close()

    def test_adaptive_habits_learn_match_reinforce(self):
        res = self.memory.learn_procedural_habit(
            "capek lelah ngantuk",
            "Jawab singkat 1 kalimat lembut, jangan kasih daftar panjang.",
        )
        self.assertTrue(res["stored"])
        hid = res["habit_id"]

        matched = self.memory.match_procedural_habits("aku lagi capek banget hari ini")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["habit_id"], hid)

        # Reinforce negative until < 0 -> tidak dimunculkan lagi
        self.memory.reinforce_procedural_habit(hid, delta=-2)
        self.assertEqual(self.memory.match_procedural_habits("aku lagi capek banget"), [])

    def test_photo_moment_rich_metadata(self):
        bundle = self.memory.commit_turn_bundle(
            "User: liat foto pantai | AI: manis banget",
            PADVector(P=0.4, A=0.2, D=0.2),
            actions={
                "photo_moment": {
                    "caption": "Selfie sore di pantai",
                    "people": ["user", "agent"],
                    "place": "Pantai Pangandaran",
                    "feeling": "hangat dan bahagia",
                    "when_label": "sore minggu lalu",
                    "consent_status": "granted",
                }
            },
        )
        self.assertTrue(bundle["outcomes"]["photo_moment"]["stored"])
        ref = self.memory.select_photo_reference(user_text="inget pas sore bahagia di pantai nggak?")
        self.assertIsNotNone(ref)
        self.assertEqual(ref["feeling"], "hangat dan bahagia")
        self.assertEqual(ref["when_label"], "sore minggu lalu")
        self.assertEqual(ref["people"], ["user", "agent"])

    def test_recall_domain_alignment_and_chain_persistence(self):
        ep1 = self.memory.encode_episode(
            "User: tes codex oauth sqlite migration bug mcp server | AI: oke aku debug",
            PADVector(P=0.1, A=0.1, D=0.2),
            entities=["codex", "oauth", "sqlite"],
        )
        ep2 = self.memory.encode_episode(
            "User: lagi pengen manja-manjaan peluk hangat sore ini | AI: sini peluk",
            PADVector(P=0.5, A=0.2, D=0.1),
            entities=["manja", "peluk", "hangat"],
        )
        # Re-open MemoryManager (simulasi one-shot MCP) -> _last_node_id harus terpulihkan
        mem2 = MemoryManager(self.db_path)
        self.assertEqual(mem2._last_node_id, ep2.node_id)
        episodes, _, _ = mem2.retrieve_context(
            "pengen manja peluk hangat nih", PADVector(P=0.5, A=0.2, D=0.1)
        )
        self.assertTrue(episodes)
        self.assertEqual(episodes[0].node_id, ep2.node_id)

    def test_emoji_palette_and_retry_total_turns(self):
        r1 = self.runner.perceive_and_think("halo kamu lagi apa?", turn_id="t_retry_1")
        turns_after_1 = self.heart.state.total_turns
        r2 = self.runner.perceive_and_think("halo kamu lagi apa?", turn_id="t_retry_1")
        self.assertEqual(self.heart.state.total_turns, turns_after_1)
        self.assertIsInstance(r1["emotional_directive"]["emoji_palette"], list)
        self.assertEqual(phrase_bank.select_emoji_palette("Hostile", "dry_short_1_bubble", "1"), [])

    def test_drive_bridge_push_no_false_positive(self):
        bridge = DriveSyncBridge(local_state_dir=str(self.tmp))
        # Simulasikan service gagal saat upload
        class _BrokenService:
            def files(self):
                raise RuntimeError("network down")
        bridge.service = _BrokenService()
        ok = bridge.push_state(include_memory_db=False, async_mode=False)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
