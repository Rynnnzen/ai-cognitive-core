"""Test suite v0.6.0 — anti-repeat heartbeat M11 + 4 ekspansi PAD.

SEMUA tes memakai fixture DB & temp HOME, TIDAK PERNAH menyentuh live state.
Jalankan dari root repo:
  HOME=/tmp/aya_v060_test PYTHONPATH=src python3 -m unittest discover -s tests -v
"""

import importlib
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# HOME sementara HARUS diset sebelum mengimpor ai_cognitive_core (mcp_server
# membuat bridge/heart/memory di level modul).
_TEST_HOME = tempfile.mkdtemp(prefix="aya_v060_test_home_")
os.environ["HOME"] = _TEST_HOME
os.environ.pop("GDRIVE_OAUTH_TOKEN_JSON", None)
os.environ.pop("GDRIVE_SERVICE_ACCOUNT_JSON", None)

from ai_cognitive_core import __version__, config
from ai_cognitive_core.heart.engine import HeartEngine
from ai_cognitive_core.heart.layers.l1_neurochemical import (
    _damp_high_positive,
    update_neurochemistry,
)
from ai_cognitive_core.heart.layers.l3_mood_space import (
    apply_hedonic_elasticity,
    classify_emotional_nuance,
    compute_pad_intensity,
    compute_pad_trajectory,
)
from ai_cognitive_core.memory import v040_store
from ai_cognitive_core.memory.manager import MemoryManager
from ai_cognitive_core.schemas import (
    HeartState,
    NeuroState,
    PADVector,
    StimulusAppraisal,
)

# Seluruh label nuansa (22) & arah trayektori (6) yang dikenal v0.6.0.
NUANCE_LABELS = {
    "Drowsy", "Teasing", "Playful", "Affectionate", "Euphoric", "Cheerful",
    "Flustered", "Clingy", "Protective", "Cozy", "Calm", "Content",
    "Guarded", "Pouty", "Sulky", "Irritated", "Fierce", "Defensive",
    "Vulnerable", "Restless", "Lonely", "Melancholic",
}
TRAJECTORY_DIRECTIONS = {
    "steady", "softening", "warming_up", "escalating", "calming_down", "cooling_down",
}

# Bentuk heart_state.json v0.5.1: 17 kunci, TANPA field baru v0.6.0
# (prev_pad, high_pleasure_streak, last_pad_delta).
OLD_HEART_STATE_V051 = {
    "last_updated_utc": "2026-11-22T10:00:00+00:00",
    "is_resting": False,
    "rest_started_utc": None,
    "total_turns": 42,
    "neuro": {"energy": 0.5, "cortisol": 0.2, "oxytocin": 0.5,
              "dopamine": 0.5, "serotonin": 0.6, "noradrenaline": 0.3},
    "primary_affects": {"SEEKING": 0.5, "CARE": 0.4, "PLAY": 0.3, "LUST": 0.1,
                        "FEAR": 0.1, "RAGE": 0.05, "PANIC_GRIEF": 0.1},
    "pad_current": {"P": 0.05, "A": -0.05, "D": 0.15},
    "pad_baseline": {"P": 0.05, "A": -0.05, "D": 0.15},
    "coactivated_affect": None,
    "emotional_inertia_pi1": 0.35,
    "consecutive_negative_octant_turns": 0,
    "attachment_style": "Secure",
    "core_needs": {"safety": 0.75, "autonomy": 0.85, "expression": 0.65,
                   "playfulness": 0.6, "boundaries": 0.85, "coherence": 0.85,
                   "fairness": 0.8},
    "conscience": {"guilt": 0.0, "shame": 0.0, "lubb_triggered": False,
                   "lubb_reason": None},
    "active_defense": "None",
    "trust_score": 0.99,
    "relationship_stage": "deep_bond",
}


def _hb(memory, elapsed=600):
    """Panggil heartbeat seperti pemakaian nyata (siang, energi penuh)."""
    return memory.evaluate_idle_heartbeat(
        elapsed_seconds=elapsed, energy=0.85, is_resting=False, local_hour=10
    )


class TestV060HeartbeatAntiRepeat(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aya_v060_test_"))
        self.db_path = self.tmp / "mem.db"
        self.heart_path = self.tmp / "heart.json"
        self.memory = MemoryManager(self.db_path)
        self.heart = HeartEngine(self.heart_path)

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

    # --- Reminder ------------------------------------------------------
    def test_reminder_reported_once(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn = self._conn()
        try:
            res = v040_store.create_reminder(conn, text="Ingatkan user minum", due_at=past)
        finally:
            conn.close()
        self.assertTrue(res["stored"])
        hb1 = _hb(self.memory)
        self.assertTrue(hb1["should_initiate"])
        self.assertEqual(hb1["reason"], "due_reminder")
        # Panggilan kedua: sudah surfaced + cooldown -> diam.
        hb2 = _hb(self.memory)
        self.assertFalse(hb2["should_initiate"])
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT status, last_surfaced_at FROM reminder_intents WHERE intent_id = ?",
                (res["intent_id"],),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "surfaced")
        self.assertIsNotNone(row[1])

    def test_reminder_within_cooldown_skipped(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        try:
            res = v040_store.create_reminder(conn, text="Ingatkan user tidur", due_at=past)
            conn.execute(
                "UPDATE reminder_intents SET status = 'surfaced', last_surfaced_at = ? WHERE intent_id = ?",
                (now_iso, res["intent_id"]),
            )
            conn.commit()
        finally:
            conn.close()
        hb = _hb(self.memory)
        self.assertFalse(hb["should_initiate"])

    # --- Worker task ---------------------------------------------------
    def test_worker_alert_reported_once(self):
        self.memory.upsert_worker_task(worker_name="bot", description="x", status="done")
        hb1 = _hb(self.memory)
        self.assertTrue(hb1["should_initiate"])
        self.assertEqual(hb1["reason"], "worker_task_done")
        hb2 = _hb(self.memory)
        self.assertFalse(hb2["should_initiate"])

    def test_worker_alert_reset_on_new_result(self):
        res = self.memory.upsert_worker_task(worker_name="bot", description="x", status="done")
        tid = res["task_id"]
        self.assertTrue(_hb(self.memory)["should_initiate"])
        self.assertFalse(_hb(self.memory)["should_initiate"])
        # Update dengan result_summary BARU -> alerted direset -> lapor lagi.
        self.memory.upsert_worker_task(
            worker_name="bot", description="x", status="done",
            result_summary="selesai, hasil baru", task_id=tid,
        )
        conn = self._conn()
        try:
            alerted = conn.execute(
                "SELECT alerted_utc FROM worker_tasks WHERE task_id = ?", (tid,)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(alerted, "")
        hb3 = _hb(self.memory)
        self.assertTrue(hb3["should_initiate"])
        self.assertEqual(hb3["reason"], "worker_task_done")
        self.assertFalse(_hb(self.memory)["should_initiate"])
        # Update dengan summary yang SAMA -> tidak direset -> tetap diam.
        self.memory.upsert_worker_task(
            worker_name="bot", description="x", status="done",
            result_summary="selesai, hasil baru", task_id=tid,
        )
        hb5 = _hb(self.memory)
        self.assertFalse(hb5["should_initiate"])

    def test_worker_alert_reset_on_status_change(self):
        res = self.memory.upsert_worker_task(worker_name="bot", description="x", status="done")
        tid = res["task_id"]
        self.assertTrue(_hb(self.memory)["should_initiate"])
        self.assertFalse(_hb(self.memory)["should_initiate"])
        # Kembali running lalu done lagi -> lapor lagi.
        self.memory.upsert_worker_task(worker_name="bot", description="x", status="running", task_id=tid)
        conn = self._conn()
        try:
            alerted = conn.execute(
                "SELECT alerted_utc FROM worker_tasks WHERE task_id = ?", (tid,)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(alerted, "")
        self.memory.upsert_worker_task(worker_name="bot", description="x", status="done", task_id=tid)
        hb = _hb(self.memory)
        self.assertTrue(hb["should_initiate"])
        self.assertEqual(hb["reason"], "worker_task_done")

    # --- Dream ---------------------------------------------------------
    def test_dream_reported_once(self):
        conn = self._conn()
        try:
            res = v040_store.store_dream(
                conn, source_episode_ids=["ep_test"], theme="piknik",
                idea_text="Piknik di taman saat sakura mekar.",
                dream_story="Agent bermimpi piknik di bawah sakura.",
            )
        finally:
            conn.close()
        self.assertTrue(res["stored"])
        hb1 = _hb(self.memory, elapsed=3600)
        self.assertTrue(hb1["should_initiate"])
        self.assertEqual(hb1["reason"], "share_dream")
        hb2 = _hb(self.memory, elapsed=3600)
        self.assertFalse(hb2["should_initiate"])
        conn = self._conn()
        try:
            status = conn.execute(
                "SELECT status FROM dream_records WHERE dream_id = ?", (res["dream_id"],)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(status, "surfaced")

    # --- Curiosity -----------------------------------------------------
    def test_curiosity_reported_once(self):
        conn = self._conn()
        try:
            res = v040_store.propose_question(conn, text="Apa makanan favoritmu?", topic="makanan")
        finally:
            conn.close()
        self.assertTrue(res["stored"])
        hb1 = _hb(self.memory, elapsed=3600)
        self.assertTrue(hb1["should_initiate"])
        self.assertEqual(hb1["reason"], "curiosity_checkin")
        hb2 = _hb(self.memory, elapsed=3600)
        self.assertFalse(hb2["should_initiate"])

    def test_curiosity_cooldown_then_fires_again(self):
        conn = self._conn()
        try:
            res = v040_store.propose_question(conn, text="Kamu suka hujan?", topic="cuaca")
        finally:
            conn.close()
        self.assertTrue(res["stored"])
        self.assertTrue(_hb(self.memory, elapsed=3600)["should_initiate"])
        # Masih dalam cooldown 5 menit -> diam.
        self.assertFalse(_hb(self.memory, elapsed=3600)["should_initiate"])
        # Cooldown lewat (meta dimundurkan 1 jam) -> tawar lagi.
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn = self._conn()
        try:
            v040_store.set_meta(conn, "last_curiosity_offered_at", old)
        finally:
            conn.close()
        hb3 = _hb(self.memory, elapsed=3600)
        self.assertTrue(hb3["should_initiate"])
        self.assertEqual(hb3["reason"], "curiosity_checkin")


class TestV060PADFunctions(unittest.TestCase):
    # --- Intensitas ----------------------------------------------------
    def test_compute_pad_intensity(self):
        mag, label = compute_pad_intensity(PADVector(0, 0, 0))
        self.assertEqual((mag, label), (0.0, "mild"))
        mag, label = compute_pad_intensity(PADVector(0.35, 0, 0))
        self.assertAlmostEqual(mag, 0.35)
        self.assertEqual(label, "mild")
        mag, label = compute_pad_intensity(PADVector(0.3, 0.3, 0.3))
        self.assertAlmostEqual(mag, 0.5196, places=4)
        self.assertEqual(label, "moderate")
        mag, label = compute_pad_intensity(PADVector(0.75, 0, 0))
        self.assertAlmostEqual(mag, 0.75)
        self.assertEqual(label, "moderate")
        mag, label = compute_pad_intensity(PADVector(0.5, 0.5, 0.5))
        self.assertAlmostEqual(mag, 0.866, places=3)
        self.assertEqual(label, "intense")

    # --- Trayektori ----------------------------------------------------
    def test_compute_pad_trajectory(self):
        steady = {"dp": 0.0, "da": 0.0, "dd": 0.0, "direction": "steady"}
        self.assertEqual(compute_pad_trajectory(None, PADVector(0.1, 0, 0)), steady)
        cases = [
            (PADVector(-0.5, 0, 0), PADVector(-0.4, 0, 0), "softening"),
            (PADVector(0.2, 0, 0), PADVector(0.3, 0, 0), "warming_up"),
            (PADVector(0.5, 0.1, 0), PADVector(0.4, 0.2, 0), "escalating"),
            (PADVector(0.5, 0.5, 0), PADVector(0.4, 0.4, 0), "calming_down"),
            (PADVector(0, 0.5, 0), PADVector(0, 0.4, 0), "cooling_down"),
            (PADVector(0.1, 0.1, 0.1), PADVector(0.12, 0.11, 0.1), "steady"),
        ]
        for prev, curr, direction in cases:
            with self.subTest(direction=direction):
                out = compute_pad_trajectory(prev, curr)
                self.assertEqual(out["direction"], direction)
                self.assertAlmostEqual(out["dp"], round(curr.P - prev.P, 4))
                self.assertAlmostEqual(out["da"], round(curr.A - prev.A, 4))
                self.assertAlmostEqual(out["dd"], round(curr.D - prev.D, 4))

    # --- Elastisitas hedonik -------------------------------------------
    def test_apply_hedonic_elasticity(self):
        base = PADVector(P=0.05, A=-0.05, D=0.15)
        # Di bawah ambang -> streak direset, PAD utuh.
        pad, streak = apply_hedonic_elasticity(PADVector(P=0.7, A=0, D=0), base, 5)
        self.assertEqual((pad.P, streak), (0.7, 0))
        # Di atas ambang, streak belum 3 -> naik, belum ditarik.
        pad, streak = apply_hedonic_elasticity(PADVector(P=0.8, A=0.1, D=0.2), base, 0)
        self.assertEqual((pad.P, streak), (0.8, 1))
        self.assertEqual((pad.A, pad.D), (0.1, 0.2))
        # Streak mencapai 3 -> P ditarik 0.08 ke arah baseline.
        pad, streak = apply_hedonic_elasticity(PADVector(P=0.8, A=0, D=0), base, 2)
        self.assertAlmostEqual(pad.P, 0.72)
        self.assertEqual(streak, 3)
        # Tarikan tidak pernah melewati baseline.
        pad, streak = apply_hedonic_elasticity(
            PADVector(P=0.8, A=0, D=0), PADVector(P=0.78, A=0, D=0), 5
        )
        self.assertAlmostEqual(pad.P, 0.78)
        self.assertEqual(streak, 6)

    # --- Nuansa --------------------------------------------------------
    def test_classify_emotional_nuance(self):
        def nuance(p, a, d, affect, energy=0.9, phase="daytime"):
            pad = PADVector(P=p, A=a, D=d)
            _, intensity = compute_pad_intensity(pad)
            return classify_emotional_nuance(pad, intensity, affect, energy, phase)

        # Drowsy didahulukan.
        self.assertEqual(nuance(0.5, 0.5, 0.5, "CARE", energy=0.2), "Drowsy")
        self.assertEqual(nuance(0.5, -0.5, 0.5, "CARE", phase="late_night"), "Drowsy")
        # Satu wakil tiap oktan.
        self.assertEqual(nuance(0.8, 0.8, 0.8, "PLAY"), "Euphoric")
        self.assertEqual(nuance(0.4, 0.4, 0.4, "PLAY"), "Teasing")
        self.assertEqual(nuance(0.4, 0.4, -0.4, "CARE"), "Clingy")
        self.assertEqual(nuance(0.5, -0.5, 0.5, "CARE"), "Protective")
        self.assertEqual(nuance(0.1, -0.1, 0.1, "SEEKING"), "Cozy")
        self.assertEqual(nuance(0.1, -0.1, -0.1, "SEEKING"), "Calm")
        self.assertEqual(nuance(-0.8, 0.8, 0.8, "RAGE"), "Fierce")
        self.assertEqual(nuance(-0.1, 0.1, 0.1, "RAGE"), "Defensive")
        self.assertEqual(nuance(-0.1, 0.1, -0.1, "FEAR"), "Flustered")
        self.assertEqual(nuance(-0.4, 0.4, -0.4, "FEAR"), "Vulnerable")
        self.assertEqual(nuance(-0.1, -0.1, 0.1, "RAGE"), "Guarded")
        self.assertEqual(nuance(-0.8, -0.8, 0.8, "RAGE"), "Sulky")
        self.assertEqual(nuance(-0.1, -0.1, -0.1, "PANIC_GRIEF"), "Lonely")
        self.assertEqual(nuance(-0.8, -0.8, -0.8, "PANIC_GRIEF"), "Melancholic")

    # --- Redaman saturasi hormon ---------------------------------------
    def test_hormone_saturation_damping(self):
        # Helper: hanya kenaikan saat jenuh yang diredam.
        self.assertAlmostEqual(_damp_high_positive(0.90, 0.10), 0.035)
        self.assertAlmostEqual(_damp_high_positive(0.88, 0.10), 0.035)
        self.assertAlmostEqual(_damp_high_positive(0.50, 0.10), 0.10)
        self.assertAlmostEqual(_damp_high_positive(0.90, -0.05), -0.05)
        self.assertAlmostEqual(_damp_high_positive(0.90, 0.0), 0.0)
        # Wiring: oksitosin 0.95 + safety terpenuhi -> kenaikan 0.10 diredam
        # jadi 0.035, lalu homeostatik: 0.985 + 0.06*(0.5-0.985) = 0.9559.
        neuro = NeuroState(energy=0.85, cortisol=0.2, oxytocin=0.95,
                           dopamine=0.5, serotonin=0.6, noradrenaline=0.3)
        appraisal = StimulusAppraisal(
            novelty=0.0, goal_conduciveness=0.5, coping_potential=0.5,
            norm_compatibility=0.0, fulfilled_needs=["safety"],
        )
        out = update_neurochemistry(neuro, appraisal, drain_energy=False)
        self.assertEqual(out.oxytocin, 0.9559)


class TestV060Compat(unittest.TestCase):
    def test_old_heart_state_loads(self):
        state = HeartState.from_dict(dict(OLD_HEART_STATE_V051))
        self.assertIsNone(state.prev_pad)
        self.assertEqual(state.high_pleasure_streak, 0)
        self.assertEqual(
            state.last_pad_delta,
            {"dp": 0.0, "da": 0.0, "dd": 0.0, "direction": "steady"},
        )
        # Field lama tetap terbaca apa adanya.
        self.assertEqual(state.total_turns, 42)
        self.assertAlmostEqual(state.trust_score, 0.99)
        self.assertEqual(state.relationship_stage, "deep_bond")

    def test_old_heart_state_file_loads_via_engine(self):
        tmp = Path(tempfile.mkdtemp(prefix="aya_v060_heart_"))
        path = tmp / "heart.json"
        path.write_text(json.dumps(OLD_HEART_STATE_V051), encoding="utf-8")
        engine = HeartEngine(path)
        self.assertIsNone(engine.state.prev_pad)
        self.assertEqual(engine.state.high_pleasure_streak, 0)
        self.assertEqual(engine.state.total_turns, 42)

    def test_new_fields_round_trip(self):
        state = HeartState.from_dict(dict(OLD_HEART_STATE_V051))
        state.prev_pad = PADVector(P=0.5, A=0.1, D=0.2)
        state.high_pleasure_streak = 2
        state.last_pad_delta = {"dp": 0.1, "da": -0.05, "dd": 0.0, "direction": "warming_up"}
        restored = HeartState.from_dict(state.model_dump())
        self.assertEqual(restored.prev_pad, PADVector(P=0.5, A=0.1, D=0.2))
        self.assertEqual(restored.high_pleasure_streak, 2)
        self.assertEqual(restored.last_pad_delta["direction"], "warming_up")

    def test_version_is_060(self):
        self.assertEqual(__version__, "0.6.0")
        self.assertTrue(config.ENABLE_PAD_EXPANSION)


class TestV060MCPStatus(unittest.TestCase):
    """Blok v060 di get_status + field ekspansi di commit_turn (temp HOME terisolasi)."""

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="aya_v060_mcp_home_")
        os.environ["HOME"] = cls.home
        import ai_cognitive_core.mcp_server as ms

        importlib.reload(ms)
        cls.ms = ms

    def test_get_status_has_v060(self):
        ms = self.ms
        st = json.loads(ms.cognitive_get_status())
        self.assertEqual(st["v060"]["core_version"], "0.6.0")
        pe = st["v060"]["pad_expansion"]
        for key in ("pad_magnitude", "mood_intensity", "emotional_nuance",
                    "pad_trajectory", "high_pleasure_streak"):
            self.assertIn(key, pe)
        self.assertIsInstance(pe["pad_magnitude"], float)
        self.assertGreaterEqual(pe["pad_magnitude"], 0.0)
        self.assertLessEqual(pe["pad_magnitude"], 1.74)
        self.assertIn(pe["mood_intensity"], ("mild", "moderate", "intense"))
        self.assertIn(pe["emotional_nuance"], NUANCE_LABELS)
        self.assertIn(pe["pad_trajectory"]["direction"], TRAJECTORY_DIRECTIONS)
        self.assertIsInstance(pe["high_pleasure_streak"], int)
        self.assertGreaterEqual(pe["high_pleasure_streak"], 0)
        # Konsisten dengan PAD saat ini (dihitung ulang dari snapshot).
        mag, intensity = compute_pad_intensity(PADVector(**st["pad_current"]))
        self.assertAlmostEqual(pe["pad_magnitude"], mag)
        self.assertEqual(pe["mood_intensity"], intensity)

    def test_commit_turn_returns_pad_expansion(self):
        ms = self.ms
        out = json.loads(ms.cognitive_perceive_and_think("halo, aku senang banget hari ini"))
        self.assertIn("Nuance=", out["emotional_directive"]["tone_instruction"])
        commit = json.loads(ms.cognitive_commit_turn(
            user_input="halo, aku senang banget hari ini",
            agent_response="halo",
            inner_monologue="tes v0.6.0",
        ))
        self.assertEqual(commit["status"], "committed")
        for key in ("mood_intensity", "emotional_nuance", "pad_trajectory"):
            self.assertIn(key, commit)
        self.assertEqual(commit["mood_intensity"], out["emotional_directive"]["mood_intensity"])
        self.assertEqual(commit["emotional_nuance"], out["emotional_directive"]["emotional_nuance"])
        self.assertEqual(commit["pad_trajectory"], out["emotional_directive"]["pad_trajectory"])


if __name__ == "__main__":
    unittest.main()
