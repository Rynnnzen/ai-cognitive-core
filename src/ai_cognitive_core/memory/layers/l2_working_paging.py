import sqlite3
from typing import List, Optional
from ai_cognitive_core import config
from ai_cognitive_core.schemas import WorkingChunk


def _truncate_content(content: str) -> str:
    """Potong konten chunk ke 500 karakter dengan penanda (v0.5.1 M8)."""
    if len(content) > 500:
        return content[:499] + "…"
    return content


class WorkingMemoryPager:
    """L2 Working Memory Pager dengan dukungan persistensi SQLite (v0.5.0)."""

    def __init__(self, capacity: Optional[int] = None):
        self.capacity = capacity or int(getattr(config, "WORKING_MEMORY_PERSIST_CAPACITY", 6))
        self.active_pages: List[WorkingChunk] = []

    def promote(self, chunk: WorkingChunk) -> List[WorkingChunk]:
        evicted: List[WorkingChunk] = []
        for existing in self.active_pages:
            if existing.chunk_id == chunk.chunk_id:
                existing.access_count += 1
                return evicted
        # v0.5.1 (M8): dedup juga berdasarkan konten — retry perceive
        # membuat chunk_id baru (UUID) untuk konten yang persis sama.
        for existing in self.active_pages:
            if existing.role == chunk.role and existing.content.strip() == chunk.content.strip():
                existing.access_count += 1
                return evicted
        if len(self.active_pages) >= self.capacity:
            self.active_pages.sort(key=lambda c: (c.access_count, c.timestamp_utc))
            evicted.append(self.active_pages.pop(0))
        self.active_pages.append(chunk)
        return evicted

    def load_from_db(self, conn: sqlite3.Connection) -> None:
        if not getattr(config, "ENABLE_PERSISTENT_WORKING_MEMORY", True):
            return
        try:
            rows = conn.execute(
                """
                SELECT chunk_id, role, content, timestamp_utc, access_count
                FROM working_memory_chunks
                ORDER BY timestamp_utc DESC
                LIMIT ?
                """,
                (self.capacity,),
            ).fetchall()
        except sqlite3.Error:
            return
        self.active_pages = [
            WorkingChunk(
                chunk_id=r[0],
                role=r[1],
                content=r[2],
                timestamp_utc=r[3],
                access_count=int(r[4] or 1),
            )
            for r in reversed(rows)
        ]

    def save_to_db(self, conn: sqlite3.Connection, commit: bool = True) -> None:
        if not getattr(config, "ENABLE_PERSISTENT_WORKING_MEMORY", True):
            return
        try:
            conn.execute("DELETE FROM working_memory_chunks")
            for c in self.active_pages[-self.capacity :]:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO working_memory_chunks
                    (chunk_id, role, content, timestamp_utc, access_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (c.chunk_id, c.role, _truncate_content(c.content), c.timestamp_utc, c.access_count),
                )
            if commit:
                conn.commit()
        except sqlite3.Error:
            pass
