import uuid
from typing import List
from ai_cognitive_core.schemas import CoalitionCandidate, ConsciousBroadcast


def ignite_global_workspace(
    candidates: List[CoalitionCandidate],
    max_chunks: int = 4,
) -> ConsciousBroadcast:
    ranked = sorted(candidates, key=lambda c: c.total_salience, reverse=True)
    winners = ranked[:max_chunks]
    return ConsciousBroadcast(
        broadcast_id=f"gwt_{uuid.uuid4().hex[:8]}",
        network_mode="CEN",
        winning_chunks=winners,
    )
