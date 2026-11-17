from typing import List
from ai_cognitive_core.schemas import CoalitionCandidate, EpisodicNode, WorkingChunk


def bind_coalition_candidates(
    working_chunks: List[WorkingChunk],
    recalled_episodes: List[EpisodicNode],
    dominant_affect: str,
) -> List[CoalitionCandidate]:
    candidates: List[CoalitionCandidate] = []
    for wc in working_chunks:
        candidates.append(
            CoalitionCandidate(
                chunk_id=wc.chunk_id,
                source="working_memory",
                content=wc.content,
                base_salience=0.80 if wc.role == "user" else 0.55,
                affective_boost=0.35,
            )
        )
    for ep in recalled_episodes:
        candidates.append(
            CoalitionCandidate(
                chunk_id=ep.node_id,
                source="episodic_recall",
                content=ep.summary,
                base_salience=ep.importance_score,
                affective_boost=ep.somatic_tag.arousal_weight,
            )
        )
    candidates.append(
        CoalitionCandidate(
            chunk_id="heart_drive_signal",
            source="heart_drive",
            content=f"Dorongan afektif aktif: {dominant_affect}",
            base_salience=0.65,
            affective_boost=0.50,
        )
    )
    return candidates
