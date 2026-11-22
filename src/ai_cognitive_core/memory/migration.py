"""
Migrasi skema SQLite v0.3.1 -> v0.4.0 (idempotent, aman dijalankan berulang).

- Membuat 4 tabel baru (curiosity_questions, reminder_intents, dream_records,
  photo_moments) + turn_markers + energy_telemetry + schema_meta.
- Menambah kolom provenans (source, inference_status) ke semantic_facts
  secara additive (ALTER TABLE dijaga PRAGMA table_info).
- SEBELUM menulis apa pun, menyalin DB ke <db>.bak-v0.3.1 jika backup itu
  belum ada — jadi DB v0.3.1 asli selalu bisa dipulihkan.

Tidak ada konten percakapan yang ditulis ke tabel baru kecuali yang memang
disimpan sebagai state fitur (teks pertanyaan/niat/mimpi/caption).
"""

import shutil
import sqlite3
from pathlib import Path
from typing import Dict, List

SCHEMA_VERSION = 4
BACKUP_SUFFIX = ".bak-v0.3.1"

_NEW_TABLES: Dict[str, str] = {
    "curiosity_questions": """
        CREATE TABLE IF NOT EXISTS curiosity_questions (
            question_id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            topic TEXT,
            created_at TEXT,
            priority REAL,
            status TEXT,
            last_offered_at TEXT,
            context_tags_json TEXT,
            expires_at TEXT,
            source TEXT
        )
    """,
    "reminder_intents": """
        CREATE TABLE IF NOT EXISTS reminder_intents (
            intent_id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            created_at TEXT,
            due_at TEXT,
            trigger_condition TEXT,
            source TEXT,
            priority REAL,
            status TEXT,
            last_surfaced_at TEXT,
            repeat_policy TEXT,
            basis TEXT
        )
    """,
    "dream_records": """
        CREATE TABLE IF NOT EXISTS dream_records (
            dream_id TEXT PRIMARY KEY,
            created_at TEXT,
            source_episode_ids_json TEXT,
            theme TEXT,
            idea_text TEXT,
            category TEXT,
            novelty_score REAL,
            status TEXT,
            sensitivity_tags_json TEXT
        )
    """,
    "photo_moments": """
        CREATE TABLE IF NOT EXISTS photo_moments (
            moment_id TEXT PRIMARY KEY,
            timestamp TEXT,
            caption TEXT,
            people_json TEXT,
            place TEXT,
            event_tags_json TEXT,
            source_ref TEXT,
            consent_status TEXT,
            linked_episode_ids_json TEXT
        )
    """,
    "turn_markers": """
        CREATE TABLE IF NOT EXISTS turn_markers (
            turn_id TEXT PRIMARY KEY,
            phase TEXT,
            created_at TEXT,
            updated_at TEXT,
            episode_id TEXT,
            drained INTEGER
        )
    """,
    "energy_telemetry": """
        CREATE TABLE IF NOT EXISTS energy_telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT,
            turn_id TEXT,
            drain REAL,
            recharge REAL,
            energy_after REAL,
            noradrenaline REAL,
            cortisol REAL
        )
    """,
    "working_memory_chunks": """
        CREATE TABLE IF NOT EXISTS working_memory_chunks (
            chunk_id TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp_utc TEXT NOT NULL,
            access_count INTEGER DEFAULT 1
        )
    """,
    "worker_tasks": """
        CREATE TABLE IF NOT EXISTS worker_tasks (
            task_id TEXT PRIMARY KEY,
            worker_name TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            result_summary TEXT DEFAULT '',
            created_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL
        )
    """,
    "inside_jokes": """
        CREATE TABLE IF NOT EXISTS inside_jokes (
            joke_id TEXT PRIMARY KEY,
            phrase TEXT NOT NULL,
            meaning TEXT DEFAULT '',
            trigger_keywords_json TEXT DEFAULT '[]',
            times_used INTEGER DEFAULT 0,
            created_utc TEXT NOT NULL
        )
    """,
    "schema_meta": """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """,
}

# Kolom additive: (tabel, kolom, definisi). Dijaga PRAGMA table_info.
_ADDITIVE_COLUMNS: List[tuple] = [
    ("semantic_facts", "source", "TEXT DEFAULT ''"),
    ("semantic_facts", "inference_status", "TEXT DEFAULT 'inferred'"),
    ("dream_records", "dream_story", "TEXT DEFAULT ''"),
    ("photo_moments", "feeling", "TEXT DEFAULT ''"),
    ("photo_moments", "when_label", "TEXT DEFAULT ''"),
]


def _table_columns(conn: sqlite3.Connection, table: str) -> set:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {r[1] for r in rows}


def migrate_db(db_path, backup: bool = True) -> dict:
    """Jalankan migrasi v0.4.0 pada DB di db_path. Idempotent."""
    path = Path(db_path)
    stats = {
        "schema_version": SCHEMA_VERSION,
        "backup_created": False,
        "backup_path": None,
        "tables_created": [],
        "columns_added": [],
    }

    # 1. Backup dulu (hanya sekali — jika backup sudah ada, jangan timpa).
    if backup and path.exists() and path.stat().st_size > 0:
        backup_path = Path(str(path) + BACKUP_SUFFIX)
        if not backup_path.exists():
            shutil.copy2(str(path), str(backup_path))
            stats["backup_created"] = True
            stats["backup_path"] = str(backup_path)

    conn = sqlite3.connect(str(path))
    try:
        existing_tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for name, ddl in _NEW_TABLES.items():
            conn.execute(ddl)
            if name not in existing_tables:
                stats["tables_created"].append(name)

        for table, column, definition in _ADDITIVE_COLUMNS:
            cols = _table_columns(conn, table)
            if cols and column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                stats["columns_added"].append(f"{table}.{column}")

        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    finally:
        conn.close()
    return stats


def get_schema_version(db_path) -> int:
    """Baca versi skema dari DB (0 = belum pernah dimigrasi / DB lama)."""
    path = Path(db_path)
    if not path.exists():
        return 0
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        return int(row[0]) if row else 0
    except (sqlite3.Error, ValueError):
        return 0
    finally:
        conn.close()
