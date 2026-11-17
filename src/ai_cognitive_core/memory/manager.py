import json
import sqlite3
import uuid
from pathlib import Path
from typing import List, Tuple
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

    def ingest_sensory_input(self, content: str, role: str = "user") -> WorkingChunk:
        chunk = WorkingChunk(
            chunk_id=f"chk_{uuid.uuid4().hex[:8]}",
            role=role,
            content=content,
        )
        self.sensory.push(chunk)
        self.working.promote(chunk)
        return chunk

    def retrieve_context(self, query_text: str, pad_now: PADVector) -> Tuple[List[EpisodicNode], List[SemanticFact], float]:
        conn = sqlite3.connect(str(self.db_path))
        episodes, ca1_mismatch = run_bounded_ppr(conn, query_text, pad_now, top_k=3)

        for ep in episodes:
            conn.execute(
                "UPDATE episodic_nodes SET stability_status = 'LABILE', access_count = access_count + 1 WHERE node_id = ?",
                (ep.node_id,),
            )
        conn.commit()
        facts = retrieve_semantic_facts(conn, limit=4)
        conn.close()
        return episodes, facts, ca1_mismatch

    def encode_episode(self, summary: str, pad_vector: PADVector, entities: List[str] | None = None) -> EpisodicNode:
        entities = entities or [w.strip(".,!?").lower() for w in summary.split() if len(w) > 4][:6]
        vec = deterministic_embed(summary)
        arousal_weight = round(min(1.0, 0.4 + 0.6 * abs(pad_vector.A)), 4)
        importance = round(min(1.0, 0.45 + 0.35 * abs(pad_vector.P) + 0.20 * abs(pad_vector.A)), 4)

        node = EpisodicNode(
            node_id=f"ep_{uuid.uuid4().hex[:10]}",
            summary=summary,
            entities=entities,
            somatic_tag=SomaticTag(pad_at_encoding=pad_vector, arousal_weight=arousal_weight),
            stability_status="STABLE",
            importance_score=importance,
        )

        conn = sqlite3.connect(str(self.db_path))
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
        conn.commit()
        conn.close()
        self._last_node_id = node.node_id
        return node
