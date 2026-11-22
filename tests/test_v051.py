"""Test suite v0.5.1 — perbaikan audit P1-P5 & M1-M17.

SEMUA tes memakai fixture DB & temp HOME, TIDAK PERNAH menyentuh live state.
Jalankan dari root repo:
  HOME=/tmp/aya_v051_test PYTHONPATH=src python3 -m unittest discover -s tests -v
"""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# HOME sementara HARUS diset sebelum mengimpor ai_cognitive_core (mcp_server
# membuat bridge/heart/memory di level modul).
_TEST_HOME = tempfile.mkdtemp(prefix="agent_v051_test_home_")
os.environ["HOME"] = _TEST_HOME
os.environ.pop("GDRIVE_OAUTH_TOKEN_JSON", None)
os.environ.pop("GDRIVE_SERVICE_ACCOUNT_JSON", None)

from ai_cognitive_core import __version__, config
from ai_cognitive_core.drive_bridge import HAS_GDRIVE_LIB, DriveSyncBridge
from ai_cognitive_core.heart.engine import HeartEngine
from ai_cognitive_core.heart.layers.l1_neurochemical import get_circadian_phase
from ai_cognitive_core.memory import migration, v040_store
from ai_cognitive_core.memory.consolidation import run_sleep_consolidation
from ai_cognitive_core.memory.layers.l3_episodic_graph import run_bounded_ppr
from ai_cognitive_core.memory.manager import MemoryManager
from ai_cognitive_core.schemas import PADVector, WorkingChunk


class TestV051AuditFixes(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agent_v051_test_"))
        self.db_path = self.tmp / "mem.db"
        self.heart_path = self.tmp / "heart.json"
        self.memory = MemoryManager(self.db_path)
        self.heart = HeartEngine(self.heart_path)

    # --- P1: error init Drive tercatat -----------------------------------
    def test_p1_drive_init_error_recorded(self):
        bad_dir = self.tmp / "bad_drive"
        bad_dir.mkdir()
        token_path = bad_dir / "token.json"
        token_path.write_text("{not valid json", encoding="utf-8")
        env = {"GDRIVE_TOKEN_PATH": str(token_path)}
        with patch.dict(os.environ, env):
            os.environ.pop("GDRIVE_OAUTH_TOKEN_JSON", None)
            os.environ.pop("GDRIVE_SERVICE_ACCOUNT_JSON", None)
            bridge = DriveSyncBridge(local_state_dir=str(bad_dir))
        self.assertIsNone(bridge.service)
        self.assertIsNotNone(bridge.last_init_error)
        if HAS_GDRIVE_LIB:
            self.assertIn("oauth", bridge.last_init_error)
        else:
            self.assertIn("not installed", bridge.last_init_error)

    # --- P2: last_sync_utc tidak berubah saat offline --------------------
    def test_p2_last_sync_unchanged_when_offline(self):
        bridge = DriveSyncBridge(local_state_dir=str(self.tmp))
        self.assertIsNone(bridge.service)  # tanpa kredensial di temp dir
        old_sync = "2026-11-22T18:01:39+00:00"
        bridge.meta_path.write_text(
            json.dumps({"last_sync_utc": old_sync, "active_device": "t"}),
            encoding="utf-8",
        )
        self.assertFalse(bridge.push_state(include_memory_db=False, async_mode=False))
        meta = json.loads(bridge.meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["last_sync_utc"], old_sync)
        self.assertIn("last_attempt_utc", meta)

    # --- P3: atomic write + .corrupt + recovery .bak ----------------------
    def test_p3_atomic_save_creates_bak(self):
        self.heart.state.trust_score = 0.60
        self.heart.save()
        self.heart.state.trust_score = 0.70
        self.heart.save()
        bak = self.heart_path.with_name("heart.json.bak")
        self.assertTrue(bak.exists())
        self.assertIn("0.6", bak.read_text(encoding="utf-8"))  # isi save sebelumnya
        self.assertFalse(self.heart_path.with_name("heart.json.tmp").exists())

    def test_p3_corrupt_state_recovers_from_bak(self):
        self.heart.state.trust_score = 0.77
        self.heart.save()
        self.heart.state.trust_score = 0.78
        self.heart.save()  # .bak kini memegang 0.77
        self.heart_path.write_text("{corrupt json!!!", encoding="utf-8")
        engine2 = HeartEngine(self.heart_path)
        self.assertEqual(engine2.state.trust_score, 0.77)
        corrupt_files = list(self.tmp.glob("heart.json.corrupt.*"))
        self.assertEqual(len(corrupt_files), 1)
        self.assertTrue(self.heart_path.exists())  # state pulihan tersimpan kembali

    def test_p3_corrupt_state_no_bak_creates_fresh(self):
        bad_path = self.tmp / "bad_heart.json"
        bad_path.write_text("not json at all", encoding="utf-8")
        engine = HeartEngine(bad_path)
        self.assertEqual(engine.state.trust_score, 0.55)  # default baru
        self.assertEqual(len(list(self.tmp.glob("bad_heart.json.corrupt.*"))), 1)

    # --- P4: dedup commit tanpa turn_id ----------------------------------
    def test_p4_content_dedup_without_turn_id(self):
        pad = PADVector(P=0.1, A=0.1, D=0.1)
        summary = "User: halo | AI (Relaxed): hai"
        r1 = self.memory.commit_turn_bundle(summary, pad)
        self.assertFalse(r1["duplicate"])
        r2 = self.memory.commit_turn_bundle(summary, pad)
        self.assertTrue(r2["duplicate"])
        self.assertEqual(r2["episode_id"], r1["episode_id"])
        conn = sqlite3.connect(str(self.db_path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM episodic_nodes").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)
        # Summary berbeda -> bukan duplikat.
        r3 = self.memory.commit_turn_bundle("User: halo lagi | AI (Relaxed): hai", pad)
        self.assertFalse(r3["duplicate"])

    # --- M1: importance bisa < 0.35 + pruning telemetri ------------------
    def test_m1_importance_can_be_below_threshold(self):
        node = self.memory.encode_episode(
            "obrolan ringan biasa", PADVector(P=0.0, A=0.0, D=0.0)
        )
        self.assertLess(node.importance_score, 0.35)
        self.assertGreaterEqual(node.importance_score, 0.20)
        node2 = self.memory.encode_episode(
            "momen sangat bahagia", PADVector(P=0.9, A=0.8, D=0.5)
        )
        self.assertGreater(node2.importance_score, 0.8)

    def test_m1_energy_telemetry_pruned_to_2000(self):
        conn = sqlite3.connect(str(self.db_path))
        try:
            for _ in range(2005):
                conn.execute(
                    "INSERT INTO energy_telemetry (timestamp_utc, energy_after) VALUES (?, ?)",
                    ("2026-11-23T00:00:00+00:00", 0.5),
                )
            conn.commit()
        finally:
            conn.close()
        stats = run_sleep_consolidation(str(self.db_path))
        conn = sqlite3.connect(str(self.db_path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM energy_telemetry").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 2000)
        self.assertEqual(stats["telemetry_pruned"], 5)

    # --- M5: trust delta dari config -------------------------------------
    def test_m5_trust_delta_from_config(self):
        self.assertEqual(config.TRUST_POS_DELTA, 0.004)
        self.assertEqual(config.TRUST_NEG_DELTA, -0.012)
        self.assertEqual(config.TRUST_STAGE_DEEP_BOND, 0.80)
        t0 = self.heart.state.trust_score
        self.heart.step("makasih sayang kamu lucu banget!")
        self.assertEqual(
            self.heart.state.trust_score, round(t0 + config.TRUST_POS_DELTA, 4)
        )

    # --- M6: jam 05:00 = morning -----------------------------------------
    def test_m6_hour_05_is_morning(self):
        self.assertEqual(get_circadian_phase(5), "morning")
        self.assertEqual(get_circadian_phase(4), "late_night")
        self.assertEqual(get_circadian_phase(10), "morning")
        self.assertEqual(get_circadian_phase(11), "daytime")
        self.assertEqual(get_circadian_phase(17), "daytime")
        self.assertEqual(get_circadian_phase(18), "evening")
        self.assertEqual(get_circadian_phase(22), "evening")
        self.assertEqual(get_circadian_phase(23), "late_night")
        self.assertEqual(get_circadian_phase(0), "late_night")

    # --- M8: dedup konten + penanda truncasi working memory --------------
    def test_m8_working_memory_content_dedup(self):
        self.memory.working.promote(
            WorkingChunk(chunk_id="chk_a", role="user", content="Coba Adit sekalian")
        )
        self.memory.working.promote(
            WorkingChunk(chunk_id="chk_b", role="user", content="Coba Adit sekalian")
        )
        self.assertEqual(len(self.memory.working.active_pages), 1)
        # Role berbeda -> chunk berbeda.
        self.memory.working.promote(
            WorkingChunk(chunk_id="chk_c", role="assistant", content="Coba Adit sekalian")
        )
        self.assertEqual(len(self.memory.working.active_pages), 2)

    def test_m8_truncation_marked_with_ellipsis(self):
        self.memory.working.promote(
            WorkingChunk(chunk_id="chk_long", role="user", content="x" * 600)
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.memory.working.save_to_db(conn, commit=True)
            row = conn.execute(
                "SELECT content FROM working_memory_chunks WHERE chunk_id = 'chk_long'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(len(row[0]), 500)
        self.assertTrue(row[0].endswith("…"))

    # --- M10: baris korup dilewati di recall ------------------------------
    def test_m10_corrupt_episode_row_skipped(self):
        good = self.memory.encode_episode(
            "obrolan tentang pantai dan senja", PADVector(P=0.3, A=0.2, D=0.1)
        )
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                """INSERT INTO episodic_nodes
                (node_id, timestamp_utc, summary, entities_json, pad_json, arousal_weight,
                 stability_status, importance_score, access_count, next_node_id, embedding_blob)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "ep_bad", "2026-11-23T01:00:00+00:00", "baris rusak", "[]",
                    "{pad json rusak", 0.5, "STABLE", 0.9, 1, None, b"\x00\x01\x02",
                ),
            )
            conn.commit()
            winners, _ = run_bounded_ppr(
                conn, "pantai senja", PADVector(P=0.1, A=0.1, D=0.1)
            )
        finally:
            conn.close()
        self.assertEqual([w.node_id for w in winners], [good.node_id])

    # --- M4: EPISODE_SCAN_LIMIT dari config -------------------------------
    def test_m4_episode_scan_limit_from_config(self):
        for i in range(3):
            self.memory.encode_episode(
                f"obrolan nomor {i} tentang pantai", PADVector(P=0.2, A=0.1, D=0.1)
            )
        old = config.EPISODE_SCAN_LIMIT
        config.EPISODE_SCAN_LIMIT = 1
        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                winners, _ = run_bounded_ppr(
                    conn, "pantai", PADVector(P=0.1, A=0.1, D=0.1), top_k=3
                )
            finally:
                conn.close()
        finally:
            config.EPISODE_SCAN_LIMIT = old
        self.assertEqual(len(winners), 1)

    # --- M11: alert worker hanya sekali + migrasi alerted_utc ------------
    def test_m11_migration_adds_alerted_utc(self):
        migration.migrate_db(self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(worker_tasks)").fetchall()}
        finally:
            conn.close()
        self.assertIn("alerted_utc", cols)
        # Idempotent: jalankan lagi tanpa error.
        migration.migrate_db(self.db_path)

    def test_m11_worker_alert_reported_once(self):
        self.memory.upsert_worker_task(
            worker_name="bot", description="x", status="done"
        )
        hb1 = self.memory.evaluate_idle_heartbeat(
            elapsed_seconds=600, energy=0.85, is_resting=False, local_hour=10
        )
        self.assertTrue(hb1["should_initiate"])
        self.assertEqual(hb1["reason"], "worker_task_done")
        hb2 = self.memory.evaluate_idle_heartbeat(
            elapsed_seconds=600, energy=0.85, is_resting=False, local_hour=10
        )
        self.assertFalse(hb2["should_initiate"])  # sudah dilaporkan
        # Helper penanda manual juga bekerja.
        res2 = self.memory.upsert_worker_task(
            worker_name="bot2", description="y", status="failed"
        )
        self.assertTrue(self.memory.mark_worker_task_alerted(res2["task_id"]))
        hb3 = self.memory.evaluate_idle_heartbeat(
            elapsed_seconds=600, energy=0.85, is_resting=False, local_hour=10
        )
        self.assertFalse(hb3["should_initiate"])

    # --- M12: prune tidak pernah hapus tugas aktif ------------------------
    def test_m12_prune_never_deletes_active_tasks(self):
        old_cap = config.MAX_ACTIVE_WORKER_TASKS
        config.MAX_ACTIVE_WORKER_TASKS = 3
        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                base = datetime(2026, 11, 20, tzinfo=timezone.utc)
                rows = [
                    ("wt_run", "running", base + timedelta(minutes=0)),
                    ("wt_d1", "done", base + timedelta(minutes=1)),
                    ("wt_d2", "done", base + timedelta(minutes=2)),
                    ("wt_d3", "done", base + timedelta(minutes=3)),
                ]
                for tid, status, ts in rows:
                    conn.execute(
                        """INSERT INTO worker_tasks
                        (task_id, worker_name, description, status, result_summary,
                         created_utc, updated_utc)
                        VALUES (?, ?, ?, ?, '', ?, ?)""",
                        (tid, "bot", "desc", status, ts.isoformat(), ts.isoformat()),
                    )
                conn.commit()
                # Picu pruning lewat upsert (total jadi 5 > cap 3).
                res = v040_store.upsert_worker_task(
                    conn, worker_name="bot", description="baru", status="done"
                )
                self.assertTrue(res["stored"])
                remaining = {
                    r[0] for r in conn.execute("SELECT task_id FROM worker_tasks").fetchall()
                }
            finally:
                conn.close()
            self.assertIn("wt_run", remaining)  # running paling lama tetap hidup
            self.assertEqual(len(remaining), 3)  # 5 - 2 done terlama
        finally:
            config.MAX_ACTIVE_WORKER_TASKS = old_cap

    # --- M13: inersia pulih bertahap --------------------------------------
    def test_m13_inertia_recovers_gradually(self):
        from ai_cognitive_core.conscious.layers.l5_metacognition import (
            monitor_and_interrupt_inertia,
        )

        self.heart.state.emotional_inertia_pi1 = 0.20
        self.heart.state.consecutive_negative_octant_turns = 0
        monitor_and_interrupt_inertia(self.heart.state)
        self.assertEqual(self.heart.state.emotional_inertia_pi1, 0.22)
        for _ in range(10):
            monitor_and_interrupt_inertia(self.heart.state)
        self.assertEqual(self.heart.state.emotional_inertia_pi1, 0.35)
        # Safeguard tetap bekerja.
        self.heart.state.emotional_inertia_pi1 = 0.35
        self.heart.state.consecutive_negative_octant_turns = 3
        self.assertTrue(monitor_and_interrupt_inertia(self.heart.state))
        self.assertEqual(self.heart.state.emotional_inertia_pi1, 0.20)

    # --- M15: kata kunci pendek butuh token utuh ---------------------------
    def test_m15_short_keyword_needs_whole_token(self):
        self.memory.add_inside_joke(
            phrase="cek api dulu",
            meaning="memeriksa API",
            trigger_keywords=["api"],
        )
        # "tapi"/"rapi" mengandung substring "api" tapi bukan token "api".
        self.assertIsNone(self.memory.match_inside_joke("tapi ini rapi banget"))
        # Token "api" utuh -> cocok.
        hit = self.memory.match_inside_joke("cek api nya dong")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["phrase"], "cek api dulu")

    # --- M14: versi ---------------------------------------------------------
    def test_version_bump(self):
        self.assertEqual(__version__, "0.5.1")


class TestV051MCPTools(unittest.TestCase):
    """Tool MCP (P1 drive_status, P5) lewat modul server, temp HOME terisolasi."""

    @classmethod
    def setUpClass(cls):
        import importlib

        cls.home = tempfile.mkdtemp(prefix="agent_v051_mcp_home_")
        os.environ["HOME"] = cls.home
        import ai_cognitive_core.mcp_server as ms

        importlib.reload(ms)
        cls.ms = ms

    def test_p1_get_status_drive_status(self):
        ms = self.ms
        st = json.loads(ms.cognitive_get_status())
        ds = st["v050"]["drive_status"]
        self.assertFalse(ds["connected"])
        self.assertIsNotNone(ds["last_init_error"])
        self.assertIn("warning", ds)
        self.assertEqual(st["v050"]["core_version"], "0.5.1")

    def test_p5_none_defaults_keep_calibration(self):
        ms = self.ms
        cp = json.loads(
            ms.cognitive_configure_persona(
                attachment_style="Secure",
                baseline_p=0.05,
                baseline_a=-0.05,
                baseline_d=0.15,
                inertia_pi1=0.35,
            )
        )
        self.assertEqual(cp["status"], "persona_updated")
        # Panggil tanpa argumen -> tidak ada yang berubah.
        cp2 = json.loads(ms.cognitive_configure_persona())
        self.assertEqual(cp2["status"], "persona_updated")
        self.assertEqual(cp2["attachment_style"], "Secure")
        self.assertEqual(cp2["emotional_inertia_pi1"], 0.35)
        self.assertEqual(cp2["pad_baseline"]["P"], 0.05)
        self.assertEqual(cp2["pad_baseline"]["A"], -0.05)
        self.assertEqual(cp2["pad_baseline"]["D"], 0.15)
        # Ubah satu field saja -> yang lain tetap.
        cp3 = json.loads(ms.cognitive_configure_persona(baseline_p=0.20))
        self.assertEqual(cp3["pad_baseline"]["P"], 0.20)
        self.assertEqual(cp3["pad_baseline"]["A"], -0.05)
        self.assertEqual(cp3["attachment_style"], "Secure")
        self.assertEqual(cp3["emotional_inertia_pi1"], 0.35)

    def test_p5_invalid_attachment_returns_error_json(self):
        ms = self.ms
        out = json.loads(ms.cognitive_configure_persona(attachment_style="BukanStyle"))
        self.assertEqual(out["status"], "error")
        self.assertIn("message", out)


if __name__ == "__main__":
    unittest.main()
