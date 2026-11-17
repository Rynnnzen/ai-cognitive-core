import json
import sqlite3
from ai_cognitive_core.schemas import utc_now_iso
from ai_cognitive_core.memory import migration, v040_store
from ai_cognitive_core.memory import dreams as dreams_mod


def run_sleep_consolidation(db_path: str) -> dict:
    """
    Siklus Tidur Luring (Sharp-Wave Ripples / SWR Replay, Abstraksi ke L4, & Ebbinghaus Pruning).

    v0.4.0:
    - Fakta yang dipromosikan mendapat provenans (source + inference_status).
    - Setelah konsolidasi, rangkai mimpi (maks 3, generatif, dedup otomatis).
    - Sapu niat pengingat yang kedaluwarsa (dismiss / reschedule harian).
    - Mimpi TIDAK PERNAH dipromosikan menjadi fakta.
    """
    # Pastikan skema v0.4.0 ada (idempotent; juga membackup DB lama sekali).
    migration.migrate_db(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT node_id, summary, importance_score, access_count, entities_json
        FROM episodic_nodes
        WHERE importance_score >= 0.65
        ORDER BY importance_score DESC
        LIMIT 5
        """
    )
    high_episodes = cur.fetchall()
    promoted_facts = 0
    promoted_summaries = []
    for node_id, summary, imp, acc, entities_json in high_episodes:
        fact_id = f"refl_{node_id[:8]}"
        cur.execute(
            """
            INSERT OR REPLACE INTO semantic_facts
            (fact_id, category, subject, predicate, object_val, confidence,
             updated_utc, source, inference_status)
            VALUES (?, 'reflection_schema', 'self_experience', 'consolidated_insight', ?, ?, ?, ?, 'inferred')
            """,
            (fact_id, summary[:240], min(0.95, imp + 0.1), utc_now_iso(), f"episode:{node_id}"),
        )
        cur.execute("UPDATE episodic_nodes SET stability_status = 'STABLE' WHERE node_id = ?", (node_id,))
        promoted_facts += 1
        promoted_summaries.append(summary[:200])

    cur.execute("UPDATE episodic_nodes SET importance_score = importance_score * 0.92 WHERE access_count <= 1 AND importance_score < 0.35")
    cur.execute("DELETE FROM episodic_nodes WHERE importance_score < 0.12 AND access_count <= 1")
    pruned = cur.rowcount

    # v0.4.0: rangkai mimpi dari episode berkepentingan tinggi (generatif).
    dream_episodes = [
        {
            "node_id": node_id,
            "summary": summary,
            "importance_score": imp,
            "entities": json.loads(entities_json) if entities_json else [],
        }
        for node_id, summary, imp, acc, entities_json in high_episodes
    ]
    dream_stats = dreams_mod.draft_dreams(conn, dream_episodes)

    # v0.4.0: sapu niat pengingat kedaluwarsa.
    reminder_sweep = v040_store.sweep_expired_reminders(conn, commit=False)
    v040_store.expire_questions(conn, commit=False)

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    conn.close()

    return {
        "replayed_high_priority_episodes": len(high_episodes),
        "promoted_semantic_reflections": promoted_facts,
        "promoted_summaries": promoted_summaries,
        "pruned_trivial_episodes": pruned,
        "dreams_drafted": dream_stats["drafted"],
        "dreams_skipped_duplicate": dream_stats["skipped_duplicate"],
        "dreams_skipped_sensitive": dream_stats["skipped_sensitive"],
        "reminders_expired": reminder_sweep["expired"],
        "reminders_rescheduled": reminder_sweep["rescheduled"],
    }
