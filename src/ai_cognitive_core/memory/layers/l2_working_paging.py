from typing import List
from ai_cognitive_core.schemas import WorkingChunk


class WorkingMemoryPager:
    def __init__(self, capacity: int = 4):
        self.capacity = capacity
        self.active_pages: List[WorkingChunk] = []

    def promote(self, chunk: WorkingChunk) -> List[WorkingChunk]:
        evicted: List[WorkingChunk] = []
        for existing in self.active_pages:
            if existing.chunk_id == chunk.chunk_id:
                existing.access_count += 1
                return evicted
        if len(self.active_pages) >= self.capacity:
            self.active_pages.sort(key=lambda c: (c.access_count, c.timestamp_utc))
            evicted.append(self.active_pages.pop(0))
        self.active_pages.append(chunk)
        return evicted
