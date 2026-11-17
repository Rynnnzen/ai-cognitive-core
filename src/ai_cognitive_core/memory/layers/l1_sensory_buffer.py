from collections import deque
from typing import Deque, List
from ai_cognitive_core.schemas import WorkingChunk


class SensoryRingBuffer:
    def __init__(self, max_items: int = 8):
        self._buf: Deque[WorkingChunk] = deque(maxlen=max_items)

    def push(self, chunk: WorkingChunk) -> None:
        self._buf.append(chunk)

    def recent(self, k: int = 4) -> List[WorkingChunk]:
        return list(self._buf)[-k:]
