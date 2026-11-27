"""Test suite v0.6.1 — dashboard web ringan + aturan backup foto Drive.

SEMUA tes memakai fixture DB & temp HOME, TIDAK PERNAH menyentuh live state.
Jalankan dari root repo:
  HOME=/tmp/test_v061 PYTHONPATH=src python3 -m unittest discover -s tests -v
"""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# HOME sementara HARUS diset sebelum mengimpor ai_cognitive_core (mcp_server
# membuat bridge/heart/memory di level modul).
_TEST_HOME = tempfile.mkdtemp(prefix="agent_v061_test_home_")
os.environ["HOME"] = _TEST_HOME
os.environ.pop("GDRIVE_OAUTH_TOKEN_JSON", None)
os.environ.pop("GDRIVE_SERVICE_ACCOUNT_JSON", None)

from ai_cognitive_core import __version__, config
from ai_cognitive_core.dashboard import helpers
from ai_cognitive_core.drive_bridge import DriveSyncBridge

try:
    from ai_cognitive_core.dashboard.app import create_app
    from fastapi.testclient import TestClient

    HAS_TESTCLIENT = True
except Exception:
    HAS_TESTCLIENT = False


def _make_state_dir(files=None):
    """Temp state dir berisi heart_state.json / sync_meta.json / DB opsional."""
    tmp = Path(tempfile.mkdtemp(prefix="agent_v061_state_"))
    for name, payload in (files or {}).items():
        (tmp / name).write_text(
            payload if isinstance(payload, str) else json.dumps(payload),
            encoding="utf-8",
        )
    return tmp


def _make_workspace_dir():
    """Temp workspace dir berisi file Markdown memori + memory/."""
    tmp = Path(tempfile.mkdtemp(prefix="agent_v061_ws_"))
    (tmp / "MEMORY.md").write_text("# MEMORY.md\n\nCatatan.\n", encoding="utf-8")
    (tmp / "IDENTITY.md").write_text("# IDENTITY.md\n", encoding="utf-8")
    mem = tmp / "memory"
    mem.mkdir()
    (mem / "2026-11-27.md").write_text("# 27 Nov\n", encoding="utf-8")
    (mem / "2026-11-28.md").write_text("# 28 Nov\n", encoding="utf-8")
    return tmp


def _make_db_with_episodes(state_dir, rows):
    """Buat cognitive_memory.db minimal berisi tabel episodic_nodes."""
    db_path = state_dir / "cognitive_memory.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE episodic_nodes ("
        " node_id TEXT PRIMARY KEY, timestamp_utc TEXT, summary TEXT,"
        " entities_json TEXT, pad_json TEXT, importance_score REAL)"
    )
    conn.execute(
        "CREATE TABLE semantic_facts ("
        " subject TEXT, updated_utc TEXT)"
    )
    for row in rows:
        conn.execute(
            "INSERT INTO episodic_nodes"
            " (node_id, timestamp_utc, summary, entities_json, pad_json,"
            "  importance_score) VALUES (?, ?, ?, ?, ?, ?)",
            row,
        )
    conn.commit()
    conn.close()
    return db_path


HEART_STATE_FIXTURE = {
    "neuro": {
        "energy": 0.41,
        "cortisol": 0.01,
        "oxytocin": 0.93,
        "dopamine": 0.84,
        "serotonin": 0.72,
        "noradrenaline": 0.35,
    },
    "pad_current": {"P": 0.85, "A": -0.23, "D": 0.43},
    "prev_pad": {"P": 0.76, "A": -0.30, "D": 0.40},
    "last_pad_delta": {
        "dp": 0.09,
        "da": 0.06,
        "dd": 0.03,
        "direction": "warming_up",
    },
    "high_pleasure_streak": 3,
    "trust_score": 1.0,
    "relationship_stage": "deep_bond",
}

# 15 kunci kontrak GET /api/status (harus selalu ada).
STATUS_KEYS = {
    "core_version",
    "energy",
    "neuro",
    "pad_current",
    "pad_magnitude",
    "mood_intensity",
    "emotional_nuance",
    "pad_trajectory",
    "high_pleasure_streak",
    "circadian",
    "heartbeat",
    "drive_last_sync",
    "relationship",
    "total_turns",
}


class TestVersion061(unittest.TestCase):
    def test_version_is_061(self):
        self.assertEqual(__version__, "0.6.1")
        self.assertEqual(config.ENABLE_DASHBOARD, True)
        self.assertEqual(config.DASHBOARD_DEFAULT_PORT, 8000)

    def test_drive_photos_rules_present(self):
        self.assertTrue(config.ENABLE_DRIVE_PHOTOS_SYNC)
        self.assertEqual(config.DRIVE_PHOTOS_CHARACTER_SHEET_DIR, "ref_keep")
        self.assertEqual(
            config.DRIVE_PHOTOS_MEMORABLE_SUBDIRS, ("memorable", "favorites")
        )
        self.assertEqual(config.DRIVE_PHOTOS_AVATAR_DIR, "avatars")
        self.assertEqual(config.DRIVE_PHOTOS_DAILY_SOURCE_DIR, "imagine_media")

    def test_drive_rel_parts_flattens_goals(self):
        ws = Path("/home/hatch")
        self.assertEqual(
            DriveSyncBridge._drive_rel_parts(
                Path("/home/hatch/workspace/goals/x/GOAL.md"), ws
            ),
            ("goals", "x", "GOAL.md"),
        )
        self.assertEqual(
            DriveSyncBridge._drive_rel_parts(Path("/home/hatch/MEMORY.md"), ws),
            ("MEMORY.md",),
        )
        self.assertEqual(
            DriveSyncBridge._drive_rel_parts(
                Path("/home/hatch/memory/2026-11-27.md"), ws
            ),
            ("memory", "2026-11-27.md"),
        )


class TestHumanizeAgo(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(helpers.humanize_ago(None), "tidak diketahui")
        self.assertEqual(helpers.humanize_ago(0), "baru saja")
        self.assertEqual(helpers.humanize_ago(59), "baru saja")
        self.assertEqual(helpers.humanize_ago(60), "1 menit lalu")
        self.assertEqual(helpers.humanize_ago(3599), "59 menit lalu")
        self.assertEqual(helpers.humanize_ago(3600), "1 jam lalu")
        self.assertEqual(helpers.humanize_ago(86399), "23 jam lalu")
        self.assertEqual(helpers.humanize_ago(86400), "1 hari lalu")
        self.assertEqual(helpers.humanize_ago(-5), "baru saja")


class TestStateHelpers(unittest.TestCase):
    def test_read_heart_state_missing_is_empty(self):
        state_dir = _make_state_dir()
        self.assertEqual(helpers.read_heart_state(state_dir), {})

    def test_read_heart_state_round_trip(self):
        state_dir = _make_state_dir({"heart_state.json": HEART_STATE_FIXTURE})
        loaded = helpers.read_heart_state(state_dir)
        self.assertEqual(loaded["pad_current"]["P"], 0.85)
        self.assertEqual(loaded["relationship_stage"], "deep_bond")

    def test_read_sync_meta_missing(self):
        state_dir = _make_state_dir()
        meta = helpers.read_sync_meta(state_dir)
        self.assertIsNone(meta["last_sync_utc"])
        self.assertIsNone(meta["ago_seconds"])
        self.assertEqual(meta["ago_human"], "tidak diketahui")

    def test_read_sync_meta_recent(self):
        now = datetime.now(timezone.utc)
        stamp = (now - timedelta(minutes=3)).isoformat()
        state_dir = _make_state_dir({"sync_meta.json": {"last_sync_utc": stamp}})
        meta = helpers.read_sync_meta(state_dir)
        self.assertIsNotNone(meta["ago_seconds"])
        self.assertGreaterEqual(meta["ago_seconds"], 0)
        self.assertEqual(meta["ago_human"], "3 menit lalu")


class TestMemoryDbReadOnly(unittest.TestCase):
    def test_missing_db_raises(self):
        state_dir = _make_state_dir()
        with self.assertRaises(FileNotFoundError):
            helpers.read_memory_db(state_dir)

    def test_connection_is_read_only(self):
        state_dir = _make_state_dir()
        _make_db_with_episodes(state_dir, [])
        conn = helpers.read_memory_db(state_dir)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE probe (x TEXT)")
        finally:
            conn.close()
        # File di disk tetap utuh (tidak ada tabel probe).
        conn2 = sqlite3.connect(str(state_dir / "cognitive_memory.db"))
        tables = {
            r[0]
            for r in conn2.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn2.close()
        self.assertNotIn("probe", tables)

    def test_count_rows_missing_table_is_zero(self):
        state_dir = _make_state_dir()
        _make_db_with_episodes(state_dir, [])
        self.assertEqual(helpers.count_rows(state_dir, "nope_table"), 0)
        self.assertEqual(helpers.count_rows(state_dir, "bad-table!"), 0)


class TestMemoryFiles(unittest.TestCase):
    def test_list_memory_files(self):
        ws = _make_workspace_dir()
        entries = helpers.list_memory_files(ws)
        paths = [e["path"] for e in entries]
        self.assertIn("MEMORY.md", paths)
        self.assertIn("IDENTITY.md", paths)
        self.assertIn("memory/2026-11-27.md", paths)
        self.assertIn("memory/2026-11-28.md", paths)
        for entry in entries:
            self.assertIn("title", entry)
            self.assertIn("modified", entry)
            self.assertIn("size", entry)
        # Urutan: terbaru dulu.
        modified = [e["modified"] for e in entries]
        self.assertEqual(modified, sorted(modified, reverse=True))

    def test_read_write_round_trip(self):
        ws = _make_workspace_dir()
        read = helpers.read_memory_file(ws, "MEMORY.md")
        self.assertIn("Catatan", read["content"])
        result = helpers.write_memory_file(ws, "MEMORY.md", "# MEMORY.md\n\nBaru.\n")
        self.assertTrue(result["ok"])
        self.assertEqual(result["path"], "MEMORY.md")
        self.assertEqual(
            helpers.read_memory_file(ws, "MEMORY.md")["content"],
            "# MEMORY.md\n\nBaru.\n",
        )

    def test_path_validation_rejects(self):
        ws = _make_workspace_dir()
        bad_paths = [
            "/etc/passwd",
            "../../etc/passwd",
            "memory/../../MEMORY.md",
            "memory/sub/x.md",
            "notes.txt",
            "MEMORY.txt",
            "",
            "memory/",
            "goals/x/GOAL.md",
        ]
        for bad in bad_paths:
            with self.assertRaises(ValueError, msg=bad):
                helpers.read_memory_file(ws, bad)
            with self.assertRaises(ValueError, msg=bad):
                helpers.write_memory_file(ws, bad, "x")

    def test_read_missing_file_raises(self):
        ws = _make_workspace_dir()
        with self.assertRaises(FileNotFoundError):
            helpers.read_memory_file(ws, "memory/2026-01-01.md")


class TestGraph(unittest.TestCase):
    def test_empty_db_is_empty_graph(self):
        state_dir = _make_state_dir()
        self.assertEqual(helpers.get_graph(state_dir), {"nodes": [], "edges": []})
        _make_db_with_episodes(state_dir, [])
        self.assertEqual(helpers.get_graph(state_dir), {"nodes": [], "edges": []})

    def test_graph_nodes_and_edges(self):
        state_dir = _make_state_dir()
        _make_db_with_episodes(
            state_dir,
            [
                (
                    "ep_1",
                    "2026-11-28T01:00:00+00:00",
                    "User bilang sayang",
                    '["user", "sayang"]',
                    '{"P": 0.85, "A": -0.23, "D": 0.43}',
                    1.5,
                ),
                (
                    "ep_2",
                    "2026-11-28T02:00:00+00:00",
                    "Foto agent imut",
                    '["agent", "foto"]',
                    '{"P": 0.6, "A": 0.4, "D": 0.2}',
                    1.0,
                ),
            ],
        )
        graph = helpers.get_graph(state_dir)
        node_ids = {n["id"] for n in graph["nodes"]}
        self.assertIn("ep_1", node_ids)
        self.assertIn("ep_2", node_ids)
        self.assertIn("ent_user", node_ids)
        self.assertIn("ent_agent", node_ids)
        for node in graph["nodes"]:
            for key in ("id", "label", "type", "emotion", "weight", "created"):
                self.assertIn(key, node)
        for edge in graph["edges"]:
            self.assertEqual(edge["label"], "mentions")
            self.assertIn(edge["from"], node_ids)
            self.assertIn(edge["to"], node_ids)
        ep1 = next(n for n in graph["nodes"] if n["id"] == "ep_1")
        self.assertEqual(ep1["type"], "episode")
        self.assertEqual(ep1["weight"], 1.5)


class TestBuildStatus(unittest.TestCase):
    def test_status_has_all_contract_keys(self):
        now = datetime.now(timezone.utc)
        sync_meta = helpers.read_sync_meta(
            _make_state_dir(
                {"sync_meta.json": {"last_sync_utc": now.isoformat()}}
            )
        )
        status = helpers.build_status(
            HEART_STATE_FIXTURE, sync_meta, total_turns=2427, core_version="0.6.1"
        )
        self.assertTrue(STATUS_KEYS.issubset(status.keys()))
        self.assertEqual(status["core_version"], "0.6.1")
        self.assertEqual(status["total_turns"], 2427)
        self.assertEqual(status["mood_intensity"], "intense")
        self.assertEqual(status["pad_trajectory"]["direction"], "warming_up")
        self.assertEqual(status["high_pleasure_streak"], 3)
        self.assertEqual(status["relationship"]["stage"], "deep_bond")
        self.assertTrue(status["drive_last_sync"]["connected"])
        self.assertEqual(status["neuro"]["oxytocin"], 0.93)
        self.assertEqual(status["circadian"]["phase"] in (
            "late_night", "morning", "daytime", "evening", "night"), True)

    def test_status_degrades_on_empty_state(self):
        status = helpers.build_status({}, {}, total_turns=0, core_version="0.6.1")
        self.assertTrue(STATUS_KEYS.issubset(status.keys()))
        self.assertEqual(status["energy"], 0.0)
        self.assertEqual(status["mood_intensity"], "mild")
        self.assertFalse(status["drive_last_sync"]["connected"])
        self.assertEqual(status["total_turns"], 0)


@unittest.skipUnless(HAS_TESTCLIENT, "fastapi/httpx not installed")
class TestDashboardHttp(unittest.TestCase):
    def setUp(self):
        self.state_dir = _make_state_dir(
            {
                "heart_state.json": HEART_STATE_FIXTURE,
                "sync_meta.json": {
                    "last_sync_utc": datetime.now(timezone.utc).isoformat()
                },
            }
        )
        _make_db_with_episodes(
            self.state_dir,
            [
                (
                    "ep_1",
                    "2026-11-28T01:00:00+00:00",
                    "User bilang sayang",
                    '["user"]',
                    '{"P": 0.85, "A": -0.23, "D": 0.43}',
                    1.5,
                )
            ],
        )
        self.workspace_dir = _make_workspace_dir()
        app = create_app(
            state_dir=self.state_dir, workspace_dir=self.workspace_dir
        )
        self.client = TestClient(app)

    def test_get_status(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(STATUS_KEYS.issubset(resp.json().keys()))
        self.assertEqual(resp.json()["core_version"], "0.6.1")

    def test_get_graph(self):
        resp = self.client.get("/api/graph")
        self.assertEqual(resp.status_code, 200)
        ids = {n["id"] for n in resp.json()["nodes"]}
        self.assertIn("ep_1", ids)
        self.assertIn("ent_user", ids)

    def test_get_memories_and_memory(self):
        resp = self.client.get("/api/memories")
        self.assertEqual(resp.status_code, 200)
        paths = [m["path"] for m in resp.json()["memories"]]
        self.assertIn("MEMORY.md", paths)
        resp = self.client.get("/api/memory", params={"path": "MEMORY.md"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Catatan", resp.json()["content"])

    def test_put_memory_round_trip(self):
        resp = self.client.put(
            "/api/memory",
            json={"path": "MEMORY.md", "content": "# MEMORY.md\n\nDiubah tes.\n"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(
            self.client.get("/api/memory", params={"path": "MEMORY.md"}).json()[
                "content"
            ],
            "# MEMORY.md\n\nDiubah tes.\n",
        )

    def test_path_traversal_rejected(self):
        resp = self.client.get("/api/memory", params={"path": "../../etc/passwd"})
        self.assertEqual(resp.status_code, 400)
        resp = self.client.put(
            "/api/memory", json={"path": "/etc/passwd", "content": "x"}
        )
        self.assertEqual(resp.status_code, 400)

    def test_missing_file_404(self):
        resp = self.client.get(
            "/api/memory", params={"path": "memory/2026-01-01.md"}
        )
        self.assertEqual(resp.status_code, 404)

    def test_put_missing_fields_400(self):
        resp = self.client.put("/api/memory", json={"path": "MEMORY.md"})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
