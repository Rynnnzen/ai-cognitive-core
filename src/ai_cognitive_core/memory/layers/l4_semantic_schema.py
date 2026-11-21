import sqlite3
from typing import List
from ai_cognitive_core.schemas import SemanticFact


def retrieve_semantic_facts(conn: sqlite3.Connection, limit: int = 5) -> List[SemanticFact]:
    cur = conn.cursor()
    # v0.4.0: ikut baca kolom provenans bila skema sudah dimigrasi.
    try:
        cur.execute(
            """
            SELECT fact_id, category, subject, predicate, object_val, confidence,
                   updated_utc, source, inference_status
            FROM semantic_facts
            ORDER BY confidence DESC, updated_utc DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        has_provenance = True
    except sqlite3.OperationalError:
        # DB belum dimigrasi (tanpa kolom source/inference_status).
        cur.execute(
            """
            SELECT fact_id, category, subject, predicate, object_val, confidence, updated_utc
            FROM semantic_facts
            ORDER BY confidence DESC, updated_utc DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        has_provenance = False
    facts = []
    for r in rows:
        facts.append(
            SemanticFact(
                fact_id=r[0],
                category=r[1],
                subject=r[2],
                predicate=r[3],
                object_val=r[4],
                confidence=r[5],
                updated_utc=r[6],
                source=r[7] if has_provenance else "",
                inference_status=r[8] if has_provenance else "inferred",
            )
        )
    return facts
