import sqlite3
from ai_cognitive_core.schemas import utc_now_iso


def run_sleep_consolidation(db_path: str) -> dict:
    """
    Siklus Tidur Luring (Sharp-Wave Ripples / SWR Replay, Abstraksi ke L4, & Ebbinghaus Pruning).
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT node_id, summary, importance_score, access_count
        FROM episodic_nodes
        WHERE importance_score >= 0.65
        ORDER BY importance_score DESC
        LIMIT 5
        """
    )
    high_episodes = cur.fetchall()
    promoted_facts = 0
    promoted_summaries = []
    for node_id, summary, imp, acc in high_episodes:
        fact_id = f"refl_{node_id[:8]}"
        cur.execute(
            """
            INSERT OR REPLACE INTO semantic_facts
            (fact_id, category, subject, predicate, object_val, confidence, updated_utc)
            VALUES (?, 'reflection_schema', 'self_experience', 'consolidated_insight', ?, ?, ?)
            """,
            (fact_id, summary[:240], min(0.95, imp + 0.1), utc_now_iso()),
        )
        cur.execute("UPDATE episodic_nodes SET stability_status = 'STABLE' WHERE node_id = ?", (node_id,))
        promoted_facts += 1
        promoted_summaries.append(summary[:200])

    cur.execute("UPDATE episodic_nodes SET importance_score = importance_score * 0.92 WHERE access_count <= 1 AND importance_score < 0.35")
    cur.execute("DELETE FROM episodic_nodes WHERE importance_score < 0.12 AND access_count <= 1")
    pruned = cur.rowcount

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    conn.close()

    return {
        "replayed_high_priority_episodes": len(high_episodes),
        "promoted_semantic_reflections": promoted_facts,
        "promoted_summaries": promoted_summaries,
        "pruned_trivial_episodes": pruned,
    }
