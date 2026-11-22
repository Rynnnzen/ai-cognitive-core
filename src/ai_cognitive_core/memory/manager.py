import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from ai_cognitive_core import config
from ai_cognitive_core.schemas import (
    EpisodicNode,
    PADVector,
    SemanticFact,
    SomaticTag,
    WorkingChunk,
)
from ai_cognitive_core.memory.layers.l1_sensory_buffer import SensoryRingBuffer
from ai_cognitive_core.memory.layers.l2_working_paging import WorkingMemoryPager
from ai_cognitive_core.memory.layers.l3_episodic_graph import (
    deterministic_embed,
    run_bounded_ppr,
)
from ai_cognitive_core.memory.layers.l4_semantic_schema import retrieve_semantic_facts
from ai_cognitive_core.memory.layers.l5_procedural_habits import (
    learn_habit,
    match_habits,
    reinforce_habit,
)
from ai_cognitive_core.memory import migration, v040_store


class MemoryManager:
    """Orkestrator 5 Layer Memory (SQLite + NumPy Graph PPR)."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.sensory = SensoryRingBuffer()
        self.working = WorkingMemoryPager()
        self._last_node_id: str | None = None
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS episodic_nodes (
                node_id TEXT PRIMARY KEY,
                timestamp_utc TEXT,
                summary TEXT,
                entities_json TEXT,
                pad_json TEXT,
                arousal_weight REAL,
                stability_status TEXT,
                importance_score REAL,
                access_count INTEGER,
                next_node_id TEXT,
                embedding_blob BLOB
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS semantic_facts (
                fact_id TEXT PRIMARY KEY,
                category TEXT,
                subject TEXT,
                predicate TEXT,
                object_val TEXT,
                confidence REAL,
                updated_utc TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS procedural_habits (
                habit_id TEXT PRIMARY KEY,
                trigger_pattern TEXT,
                action_template TEXT,
                success_count INTEGER
            )
            """
        )
        conn.commit()
        conn.close()
        # v0.4.0: migrasi idempotent (tabel baru + kolom provenans + backup
        # <db>.bak-v0.3.1 bila belum ada). Aman dijalankan berulang.
        migration.migrate_db(self.db_path)
        conn2 = sqlite3.connect(str(self.db_path))
        try:
            row = conn2.execute(
                "SELECT node_id FROM episodic_nodes ORDER BY timestamp_utc DESC LIMIT 1"
            ).fetchone()
            if row:
                self._last_node_id = row[0]
            # v0.5.0: muat working memory persisten dari SQLite
            self.working.load_from_db(conn2)
        finally:
            conn2.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def ingest_sensory_input(self, content: str, role: str = "user") -> WorkingChunk:
        chunk = WorkingChunk(
            chunk_id=f"chk_{uuid.uuid4().hex[:8]}",
            role=role,
            content=content,
        )
        self.sensory.push(chunk)
        self.working.promote(chunk)
        conn = self._connect()
        try:
            self.working.save_to_db(conn, commit=True)
        finally:
            conn.close()
        return chunk

    def retrieve_context(self, query_text: str, pad_now: PADVector) -> Tuple[List[EpisodicNode], List[SemanticFact], float]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            episodes, ca1_mismatch = run_bounded_ppr(
                conn, query_text, pad_now, top_k=config.RETRIEVAL_TOP_K_EPISODES
            )
            for ep in episodes:
                conn.execute(
                    "UPDATE episodic_nodes SET stability_status = 'LABILE', access_count = access_count + 1 WHERE node_id = ?",
                    (ep.node_id,),
                )
            conn.commit()
            facts = retrieve_semantic_facts(conn, limit=config.RETRIEVAL_TOP_K_FACTS)
            return episodes, facts, ca1_mismatch
        finally:
            conn.close()

    def _insert_episode(
        self,
        conn: sqlite3.Connection,
        summary: str,
        pad_vector: PADVector,
        entities: List[str] | None = None,
    ) -> EpisodicNode:
        """Sisipkan episode pada koneksi yang diberikan (tanpa commit sendiri)."""
        entities = entities or [w.strip(".,!?").lower() for w in summary.split() if len(w) > 4][:6]
        vec = deterministic_embed(summary)
        arousal_weight = round(min(1.0, 0.4 + 0.6 * abs(pad_vector.A)), 4)
        # v0.5.1 (M1): lantai importance 0.45 -> 0.20 agar obrolan ringan
        # bisa < 0.35 dan terkena peluruhan/pruning Ebbinghaus serta
        # tersaring ambang mimpi (dulu selalu >= 0.45, ambang itu mati).
        importance = round(min(1.0, 0.20 + 0.45 * abs(pad_vector.P) + 0.35 * abs(pad_vector.A)), 4)

        node = EpisodicNode(
            node_id=f"ep_{uuid.uuid4().hex[:10]}",
            summary=summary,
            entities=entities,
            somatic_tag=SomaticTag(pad_at_encoding=pad_vector, arousal_weight=arousal_weight),
            stability_status="STABLE",
            importance_score=importance,
        )

        if self._last_node_id:
            conn.execute(
                "UPDATE episodic_nodes SET next_node_id = ? WHERE node_id = ?",
                (node.node_id, self._last_node_id),
            )
        conn.execute(
            """
            INSERT INTO episodic_nodes
            (node_id, timestamp_utc, summary, entities_json, pad_json, arousal_weight,
             stability_status, importance_score, access_count, next_node_id, embedding_blob)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node.node_id,
                node.timestamp_utc,
                node.summary,
                json.dumps(node.entities),
                node.somatic_tag.pad_at_encoding.model_dump_json(),
                node.somatic_tag.arousal_weight,
                node.stability_status,
                node.importance_score,
                node.access_count,
                node.next_node_id,
                vec.tobytes(),
            ),
        )
        conn.execute(
            "UPDATE episodic_nodes SET stability_status = 'STABLE', pad_json = ? WHERE stability_status = 'LABILE'",
            (pad_vector.model_dump_json(),),
        )
        self._last_node_id = node.node_id
        return node

    def encode_episode(self, summary: str, pad_vector: PADVector, entities: List[str] | None = None) -> EpisodicNode:
        conn = sqlite3.connect(str(self.db_path))
        try:
            node = self._insert_episode(conn, summary, pad_vector, entities)
            conn.commit()
        finally:
            conn.close()
        return node

    # ------------------------------------------------------------------
    # v0.4.0 — penyimpanan commit transaksional (fondasi laporan ekspansi §4)
    # Episode + penanda giliran + aksi v0.4.0 tersimpan dalam SATU transaksi:
    # gagal di tengah jalan = tidak ada yang tersimpan setengah-setengah.
    # ------------------------------------------------------------------

    def commit_turn_bundle(
        self,
        summary: str,
        pad_vector: PADVector,
        turn_id: Optional[str] = None,
        actions: Optional[dict] = None,
    ) -> dict:
        """Simpan satu giliran commit secara transaksional.

        actions (semua opsional):
          propose_question: dict(text, topic, priority, context_tags, expires_at)
          create_reminder: dict(text, due_at, trigger_condition, priority, repeat_policy)
          photo_moment: dict(caption, people, place, event_tags, source_ref,
                             consent_status, timestamp)
          curiosity_asked_id, dismiss_curiosity_id, dismiss_dream_id: str
          reminder_id + reminder_action ("complete"|"snooze"|"dismiss")
          snooze_until: str (ISO, untuk snooze)
          photo_moment_id + photo_moment_action ("correct"|"delete")
          photo_moment_correction: dict
        """
        actions = actions or {}
        conn = sqlite3.connect(str(self.db_path))
        try:
            if turn_id and v040_store.is_turn_committed(conn, turn_id):
                marker = v040_store.get_turn_marker(conn, turn_id)
                return {
                    "duplicate": True,
                    "episode_id": marker["episode_id"] if marker else None,
                    "outcomes": {},
                }

            # v0.5.1 (P4): fallback dedup berbasis konten saat turn_id kosong
            # (pemanggil produksi tidak pernah mengirim turn_id). Episode
            # dengan summary persis sama dalam 120 detik terakhir = retry
            # setelah respons hilang, bukan giliran baru.
            if not turn_id:
                cutoff = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
                existing = conn.execute(
                    """
                    SELECT node_id FROM episodic_nodes
                    WHERE summary = ? AND timestamp_utc >= ?
                    ORDER BY timestamp_utc DESC LIMIT 1
                    """,
                    (summary, cutoff),
                ).fetchone()
                if existing:
                    return {
                        "duplicate": True,
                        "episode_id": existing[0],
                        "outcomes": {},
                    }

            node = self._insert_episode(conn, summary, pad_vector)
            outcomes: dict = {}

            if turn_id:
                v040_store.mark_turn_committed(conn, turn_id, node.node_id, commit=False)

            q = actions.get("propose_question")
            if isinstance(q, dict) and q.get("text"):
                outcomes["curiosity"] = v040_store.propose_question(
                    conn,
                    text=q.get("text", ""),
                    topic=q.get("topic", ""),
                    priority=float(q.get("priority", 0.5)),
                    context_tags=q.get("context_tags"),
                    expires_at=q.get("expires_at"),
                    source=q.get("source", "supervisor"),
                    commit=False,
                )

            r = actions.get("create_reminder")
            if isinstance(r, dict) and r.get("text"):
                outcomes["reminder"] = v040_store.create_reminder(
                    conn,
                    text=r.get("text", ""),
                    due_at=r.get("due_at"),
                    trigger_condition=r.get("trigger_condition"),
                    source=r.get("source", "supervisor"),
                    priority=float(r.get("priority", 0.5)),
                    repeat_policy=r.get("repeat_policy", "none"),
                    commit=False,
                )

            pm = actions.get("photo_moment")
            if isinstance(pm, dict) and pm.get("caption"):
                linked = list(pm.get("linked_episode_ids") or []) + [node.node_id]
                outcomes["photo_moment"] = v040_store.store_photo_moment(
                    conn,
                    caption=pm.get("caption", ""),
                    people=pm.get("people"),
                    place=pm.get("place", ""),
                    event_tags=pm.get("event_tags"),
                    source_ref=pm.get("source_ref", ""),
                    consent_status=pm.get("consent_status", "unknown"),
                    timestamp=pm.get("timestamp"),
                    feeling=pm.get("feeling", ""),
                    when_label=pm.get("when_label", ""),
                    linked_episode_ids=linked,
                    commit=False,
                )

            if actions.get("curiosity_asked_id"):
                outcomes["curiosity_asked"] = v040_store.mark_question_asked(
                    conn, actions["curiosity_asked_id"], commit=False
                )
            if actions.get("dismiss_curiosity_id"):
                outcomes["curiosity_dismissed"] = v040_store.dismiss_question(
                    conn, actions["dismiss_curiosity_id"], commit=False
                )
            if actions.get("dismiss_dream_id"):
                outcomes["dream_dismissed"] = v040_store.dismiss_dream(
                    conn, actions["dismiss_dream_id"], commit=False
                )

            rid = actions.get("reminder_id")
            raction = actions.get("reminder_action")
            if rid and raction:
                outcomes["reminder_action"] = v040_store.apply_reminder_action(
                    conn, rid, raction,
                    snooze_until=actions.get("snooze_until"),
                    commit=False,
                )

            pmid = actions.get("photo_moment_id")
            pmaction = actions.get("photo_moment_action")
            if pmid and pmaction == "delete":
                outcomes["photo_moment_deleted"] = v040_store.delete_photo_moment(
                    conn, pmid, commit=False
                )
            elif pmid and pmaction == "correct" and isinstance(actions.get("photo_moment_correction"), dict):
                outcomes["photo_moment_corrected"] = v040_store.correct_photo_moment(
                    conn, pmid, commit=False, **actions["photo_moment_correction"]
                )

            conn.commit()
            return {"duplicate": False, "episode_id": node.node_id, "outcomes": outcomes}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # v0.4.0 — delegasi ke v040_store (satu koneksi per panggilan)
    # ------------------------------------------------------------------

    def get_turn_marker(self, turn_id: str) -> Optional[dict]:
        conn = self._connect()
        try:
            return v040_store.get_turn_marker(conn, turn_id)
        finally:
            conn.close()

    def mark_turn_perceived(self, turn_id: str, drained: bool) -> None:
        conn = self._connect()
        try:
            v040_store.mark_turn_perceived(conn, turn_id, drained)
        finally:
            conn.close()

    def select_curiosity_prompt(self, **kwargs) -> Optional[dict]:
        conn = self._connect()
        try:
            return v040_store.select_curiosity_prompt(conn, **kwargs)
        finally:
            conn.close()

    def select_due_reminder(self, **kwargs) -> Optional[dict]:
        conn = self._connect()
        try:
            return v040_store.select_due_reminder(conn, **kwargs)
        finally:
            conn.close()

    def select_dream_to_surface(self) -> Optional[dict]:
        conn = self._connect()
        try:
            return v040_store.select_dream_to_surface(conn)
        finally:
            conn.close()

    def select_photo_reference(self, **kwargs) -> Optional[dict]:
        conn = self._connect()
        try:
            return v040_store.select_photo_reference(conn, **kwargs)
        finally:
            conn.close()

    def record_energy_telemetry(self, **kwargs) -> None:
        conn = self._connect()
        try:
            v040_store.record_telemetry(conn, **kwargs)
        finally:
            conn.close()

    def telemetry_summary(self) -> dict:
        conn = self._connect()
        try:
            return v040_store.telemetry_summary(conn)
        finally:
            conn.close()

    def v040_counts(self) -> dict:
        conn = self._connect()
        try:
            return v040_store.v040_counts(conn)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # v0.4.1/v0.5.0 — L5 Procedural Habits, Worker Blackboard, Inside Jokes, Heartbeat
    # ------------------------------------------------------------------

    def match_procedural_habits(self, user_input: str, top_k: int = 3) -> list:
        if not getattr(config, "ENABLE_ADAPTIVE_HABITS", True):
            return []
        conn = self._connect()
        try:
            habits = match_habits(conn, user_input, top_k=top_k)
            return [h.model_dump() for h in habits]
        finally:
            conn.close()

    def learn_procedural_habit(self, trigger_pattern: str, action_template: str) -> dict:
        conn = self._connect()
        try:
            return learn_habit(conn, trigger_pattern, action_template, commit=True)
        finally:
            conn.close()

    def reinforce_procedural_habit(self, habit_id: str, delta: int = 1) -> Optional[dict]:
        conn = self._connect()
        try:
            return reinforce_habit(conn, habit_id, delta=delta, commit=True)
        finally:
            conn.close()

    def upsert_worker_task(self, **kwargs) -> dict:
        conn = self._connect()
        try:
            return v040_store.upsert_worker_task(conn, **kwargs)
        finally:
            conn.close()

    def list_worker_tasks(self, limit: int = 10, only_active: bool = False) -> list:
        conn = self._connect()
        try:
            return v040_store.list_worker_tasks(conn, limit=limit, only_active=only_active)
        finally:
            conn.close()

    def mark_worker_task_alerted(self, task_id: str) -> bool:
        """v0.5.1 (M11): tandai tugas worker sudah dilaporkan via heartbeat."""
        conn = self._connect()
        try:
            return v040_store.mark_worker_task_alerted(conn, task_id)
        finally:
            conn.close()

    def add_inside_joke(self, **kwargs) -> dict:
        conn = self._connect()
        try:
            return v040_store.add_inside_joke(conn, **kwargs)
        finally:
            conn.close()

    def match_inside_joke(self, user_text: str) -> Optional[dict]:
        conn = self._connect()
        try:
            return v040_store.match_inside_joke(conn, user_text=user_text)
        finally:
            conn.close()

    def evaluate_idle_heartbeat(self, **kwargs) -> dict:
        conn = self._connect()
        try:
            return v040_store.evaluate_idle_heartbeat(conn, **kwargs)
        finally:
            conn.close()
