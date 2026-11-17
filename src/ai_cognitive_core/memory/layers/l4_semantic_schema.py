import sqlite3
from typing import List
from ai_cognitive_core.schemas import SemanticFact


def retrieve_semantic_facts(conn: sqlite3.Connection, limit: int = 5) -> List[SemanticFact]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT fact_id, category, subject, predicate, object_val, confidence, updated_utc
        FROM semantic_facts
        ORDER BY confidence DESC, updated_utc DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [
        SemanticFact(
            fact_id=r[0],
            category=r[1],
            subject=r[2],
            predicate=r[3],
            object_val=r[4],
            confidence=r[5],
            updated_utc=r[6],
        )
        for r in cur.fetchall()
    ]
