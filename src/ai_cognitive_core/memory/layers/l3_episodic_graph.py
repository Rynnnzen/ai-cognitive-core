import hashlib
import json
import math
import sqlite3
from typing import List, Tuple
import numpy as np
from ai_cognitive_core.schemas import EpisodicNode, PADVector, SomaticTag

EMBED_DIM = 128


def deterministic_embed(text: str) -> np.ndarray:
    vec = np.zeros(EMBED_DIM, dtype=np.float32)
    clean = text.lower().strip()
    if not clean:
        return vec
    tokens = clean.split()
    shingles = list(tokens) + [clean[i : i + 3] for i in range(max(0, len(clean) - 2))]
    for sh in shingles:
        h = int(hashlib.md5(sh.encode("utf-8")).hexdigest()[:8], 16)
        idx = h % EMBED_DIM
        sign = 1.0 if ((h >> 8) & 1) == 0 else -1.0
        vec[idx] += sign
    norm = float(np.linalg.norm(vec))
    if norm > 1e-8:
        vec /= norm
    return vec


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-8:
        return 0.0
    return float(np.dot(a, b) / denom)


def pad_congruence_bias(pad_now: PADVector, pad_enc: PADVector) -> float:
    dist = math.sqrt(
        (pad_now.P - pad_enc.P) ** 2
        + (pad_now.A - pad_enc.A) ** 2
        + (pad_now.D - pad_enc.D) ** 2
    )
    return max(0.6, 1.3 - 0.25 * dist)


def run_bounded_ppr(
    conn: sqlite3.Connection,
    query_text: str,
    pad_now: PADVector,
    top_k: int = 4,
    alpha: float = 0.6,
) -> Tuple[List[EpisodicNode], float]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT node_id, timestamp_utc, summary, entities_json, pad_json,
               arousal_weight, stability_status, importance_score, access_count,
               next_node_id, embedding_blob
        FROM episodic_nodes
        ORDER BY timestamp_utc DESC
        LIMIT 250
        """
    )
    rows = cur.fetchall()
    if not rows:
        return [], 1.0

    q_vec = deterministic_embed(query_text)
    nodes: List[EpisodicNode] = []
    vecs: List[np.ndarray] = []
    sims = np.zeros(len(rows), dtype=np.float32)

    id_to_idx = {}
    for i, r in enumerate(rows):
        pad_enc = PADVector(**json.loads(r[4]))
        node = EpisodicNode(
            node_id=r[0],
            timestamp_utc=r[1],
            summary=r[2],
            entities=json.loads(r[3]),
            somatic_tag=SomaticTag(pad_at_encoding=pad_enc, arousal_weight=r[5]),
            stability_status=r[6],
            importance_score=r[7],
            access_count=r[8],
            next_node_id=r[9],
        )
        nodes.append(node)
        id_to_idx[node.node_id] = i
        v = np.frombuffer(r[10], dtype=np.float32) if r[10] else deterministic_embed(node.summary)
        vecs.append(v)
        sims[i] = max(0.0, cosine_sim(q_vec, v))

    n = len(nodes)
    adj = np.zeros((n, n), dtype=np.float32)
    for i, nd in enumerate(nodes):
        if nd.next_node_id and nd.next_node_id in id_to_idx:
            j = id_to_idx[nd.next_node_id]
            adj[i, j] = 1.0
            adj[j, i] = 0.5
        ent_i = set(nd.entities)
        if ent_i:
            for j in range(i + 1, n):
                if ent_i.intersection(nodes[j].entities):
                    adj[i, j] += 0.6
                    adj[j, i] += 0.6

    row_sums = adj.sum(axis=1, keepdims=True)
    trans = np.divide(adj, row_sums, out=np.zeros_like(adj), where=row_sums > 1e-8)

    p0 = sims.copy()
    if p0.sum() > 1e-8:
        p0 /= p0.sum()
    else:
        p0 = np.ones(n, dtype=np.float32) / n

    ppr = p0.copy()
    for _ in range(12):
        ppr = (1.0 - alpha) * (trans.T @ ppr) + alpha * p0

    final_scores = []
    for i, nd in enumerate(nodes):
        bias = pad_congruence_bias(pad_now, nd.somatic_tag.pad_at_encoding)
        score = bias * (0.45 * float(ppr[i]) + 0.55 * float(sims[i]))
        final_scores.append((score, nd))

    final_scores.sort(key=lambda x: x[0], reverse=True)
    max_sim = float(sims.max()) if len(sims) > 0 else 0.0
    ca1_mismatch = round(max(0.0, 1.0 - max_sim), 4)

    winners = [item[1] for item in final_scores[:top_k]]
    return winners, ca1_mismatch
