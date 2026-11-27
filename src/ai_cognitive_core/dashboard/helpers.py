"""Safe data-access helpers for the ai_cognitive_core dashboard (v0.6.1).

Design notes
------------
* Read-only where it matters: ``heart_state.json`` and
  ``cognitive_memory.db`` are never written by this module. The SQLite
  database is always opened in read-only URI mode (``mode=ro``) and no
  INSERT / UPDATE / DELETE is ever issued.
* Markdown memory files may be read and written, but only inside the
  explicitly allowed directories (the workspace root for a fixed list of
  root files, and ``workspace/memory/`` for daily notes). Every path is
  validated strictly before any filesystem access.
* All paths are configurable through environment variables with safe
  defaults. No user-specific local path is hardcoded anywhere:
  ``COGNITIVE_STATE_DIR`` (default ``~/.ai_cognitive_state``) and
  ``COGNITIVE_WORKSPACE_DIR`` (default: the current working directory).

This module only uses the standard library, so it can be imported and
unit-tested without FastAPI or any other optional dependency.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration (environment variables with safe defaults)
# ---------------------------------------------------------------------------
ENV_STATE_DIR = "COGNITIVE_STATE_DIR"
ENV_WORKSPACE_DIR = "COGNITIVE_WORKSPACE_DIR"

DEFAULT_STATE_DIRNAME = ".ai_cognitive_state"

# Markdown files that may be read/written at the workspace root.
ROOT_MEMORY_FILES = (
    "IDENTITY.md",
    "SOUL.md",
    "USER.md",
    "MEMORY.md",
    "AGENTS.md",
    "TOOLS.md",
    "PROACTIVE_PREFERENCES.md",
)

# Subdirectory holding the daily Markdown notes (top level only).
MEMORY_SUBDIR = "memory"

# Graph limits.
GRAPH_DEFAULT_LIMIT = 200
GRAPH_MAX_LIMIT = 500
GRAPH_MAX_ENTITIES = 30
GRAPH_MAX_FACTS = 50

# Tokens that are too noisy to become graph entity nodes.
_ENTITY_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{2,40}$")
_FACT_SUBJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,39}$")

# Indonesian labels for the circadian phases (used in heartbeat summaries).
_CIRCADIAN_LABEL_ID = {
    "late_night": "larut malam",
    "morning": "pagi",
    "daytime": "siang",
    "evening": "sore",
    "night": "malam",
}


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
def resolve_state_dir(explicit: Optional[Any] = None) -> Path:
    """Return the cognitive state directory (heart + memory DB + sync meta).

    Priority: explicit argument > ``COGNITIVE_STATE_DIR`` env var >
    ``~/.ai_cognitive_state``.
    """
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get(ENV_STATE_DIR)
    if env:
        return Path(env).expanduser()
    return Path.home() / DEFAULT_STATE_DIRNAME


def resolve_workspace_dir(explicit: Optional[Any] = None) -> Path:
    """Return the workspace directory holding the Markdown memory files.

    Priority: explicit argument > ``COGNITIVE_WORKSPACE_DIR`` env var >
    the current working directory.
    """
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get(ENV_WORKSPACE_DIR)
    if env:
        return Path(env).expanduser()
    return Path.cwd()


# ---------------------------------------------------------------------------
# Small JSON / time helpers
# ---------------------------------------------------------------------------
def _read_json_file(path: Path) -> Dict[str, Any]:
    """Read a JSON file, returning {} when it is missing or corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_utc(timestamp: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into an aware UTC datetime (or None)."""
    if not isinstance(timestamp, str) or not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_from_mtime(mtime: float) -> str:
    """Format a filesystem mtime as an ISO-8601 UTC timestamp."""
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def humanize_ago(ago_seconds: Optional[float]) -> str:
    """Humanize a "seconds ago" delta in Indonesian.

    Examples: "baru saja", "5 menit lalu", "2 jam lalu", "3 hari lalu".
    """
    if ago_seconds is None:
        return "tidak diketahui"
    seconds = max(0, int(ago_seconds))
    if seconds < 60:
        return "baru saja"
    if seconds < 3600:
        return f"{seconds // 60} menit lalu"
    if seconds < 86400:
        return f"{seconds // 3600} jam lalu"
    return f"{seconds // 86400} hari lalu"


# ---------------------------------------------------------------------------
# heart_state.json / sync_meta.json (read-only)
# ---------------------------------------------------------------------------
def read_heart_state(state_dir: Optional[Any] = None) -> Dict[str, Any]:
    """Read ``heart_state.json`` from the state dir (never writes).

    Returns the parsed dict, or {} when the file is missing or corrupt.
    """
    return _read_json_file(resolve_state_dir(state_dir) / "heart_state.json")


def read_sync_meta(state_dir: Optional[Any] = None) -> Dict[str, Any]:
    """Read ``sync_meta.json`` and attach last-sync timing info.

    Returned keys include the raw file contents plus:
    ``last_sync_utc`` (ISO string or None), ``ago_seconds`` (float or
    None), and ``ago_human`` (Indonesian, e.g. "20 menit lalu").
    """
    meta = _read_json_file(resolve_state_dir(state_dir) / "sync_meta.json")
    last_sync = _parse_utc(meta.get("last_sync_utc"))
    if last_sync is None:
        meta["last_sync_utc"] = None
        meta["ago_seconds"] = None
        meta["ago_human"] = "tidak diketahui"
    else:
        meta["last_sync_utc"] = last_sync.isoformat()
        meta["ago_seconds"] = max(
            0.0, (datetime.now(timezone.utc) - last_sync).total_seconds()
        )
        meta["ago_human"] = humanize_ago(meta["ago_seconds"])
    return meta


# ---------------------------------------------------------------------------
# cognitive_memory.db (read-only)
# ---------------------------------------------------------------------------
def read_memory_db(state_dir: Optional[Any] = None) -> sqlite3.Connection:
    """Open ``cognitive_memory.db`` in READ-ONLY mode and return a connection.

    The database is opened through a ``mode=ro`` SQLite URI, so the file
    can never be modified through this connection. The caller owns the
    connection and must close it. Raises FileNotFoundError when the file
    does not exist.
    """
    db_path = resolve_state_dir(state_dir) / "cognitive_memory.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"cognitive_memory.db not found: {db_path}")
    # Quote the path for the URI (spaces and '#' must not break parsing).
    from urllib.parse import quote

    uri = "file:" + quote(str(db_path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def count_rows(state_dir: Optional[Any] = None, table: str = "turn_markers") -> int:
    """Return COUNT(*) for a table, or 0 when the DB/table is unavailable.

    The table name is restricted to plain identifiers to rule out any
    SQL injection through this helper.
    """
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", table or ""):
        return 0
    try:
        conn = read_memory_db(state_dir)
    except (FileNotFoundError, sqlite3.Error):
        return 0
    try:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        return int(row["n"]) if row is not None else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Markdown memory files (list / read / write with strict path validation)
# ---------------------------------------------------------------------------
def _validate_memory_path(workspace_dir: Path, rel_path: Any) -> Tuple[Path, str]:
    """Validate a requested memory path and return (absolute path, rel posix).

    Allowed shapes only:
    * one of the fixed root files, e.g. ``MEMORY.md`` (workspace root);
    * a top-level daily note, e.g. ``memory/2026-11-27.md``.

    Rejects absolute paths, ``..`` segments, non-``.md`` files, nested
    subdirectories, and anything escaping the allowed directories.
    Raises ValueError on any violation.
    """
    if not isinstance(rel_path, str) or not rel_path:
        raise ValueError("path must be a non-empty string")
    candidate = Path(rel_path)
    if candidate.is_absolute():
        raise ValueError("absolute paths are not allowed")
    if ".." in candidate.parts:
        raise ValueError("parent-directory segments are not allowed")
    if candidate.suffix.lower() != ".md":
        raise ValueError("only .md files may be accessed")

    base = workspace_dir.resolve()
    if len(candidate.parts) == 1 and candidate.name in ROOT_MEMORY_FILES:
        resolved = (base / candidate.name).resolve()
        if resolved.parent != base:
            raise ValueError("path escapes the workspace root")
    elif (
        len(candidate.parts) == 2
        and candidate.parts[0] == MEMORY_SUBDIR
    ):
        memory_dir = (base / MEMORY_SUBDIR).resolve()
        resolved = (memory_dir / candidate.parts[1]).resolve()
        if resolved.parent != memory_dir:
            raise ValueError("path escapes the memory directory")
    else:
        raise ValueError(f"path is not an allowed memory file: {rel_path}")
    return resolved, resolved.relative_to(base).as_posix()


def _memory_entry(path: Path, rel_posix: str) -> Dict[str, Any]:
    stat = path.stat()
    return {
        "path": rel_posix,
        "title": path.name,
        "modified": _iso_from_mtime(stat.st_mtime),
        "size": stat.st_size,
    }


def list_memory_files(workspace_dir: Optional[Any] = None) -> List[Dict[str, Any]]:
    """List the Markdown memory files (root files + top-level daily notes).

    Returns entries ``{"path", "title", "modified", "size"}`` sorted by
    modification time, newest first. Missing files are skipped.
    """
    base = resolve_workspace_dir(workspace_dir)
    entries: List[Dict[str, Any]] = []
    for name in ROOT_MEMORY_FILES:
        candidate = base / name
        if candidate.is_file():
            entries.append(_memory_entry(candidate, name))
    memory_dir = base / MEMORY_SUBDIR
    if memory_dir.is_dir():
        for candidate in memory_dir.glob("*.md"):
            if candidate.is_file():
                entries.append(
                    _memory_entry(candidate, f"{MEMORY_SUBDIR}/{candidate.name}")
                )
    entries.sort(key=lambda item: item["modified"], reverse=True)
    return entries


def read_memory_file(
    workspace_dir: Optional[Any] = None, rel_path: str = ""
) -> Dict[str, Any]:
    """Read one Markdown memory file (strict path validation).

    Raises ValueError on an invalid path and FileNotFoundError when the
    file does not exist.
    """
    base = resolve_workspace_dir(workspace_dir)
    resolved, rel_posix = _validate_memory_path(base, rel_path)
    if not resolved.is_file():
        raise FileNotFoundError(f"memory file not found: {rel_posix}")
    content = resolved.read_text(encoding="utf-8")
    return {
        "path": rel_posix,
        "content": content,
        "modified": _iso_from_mtime(resolved.stat().st_mtime),
    }


def write_memory_file(
    workspace_dir: Optional[Any] = None, rel_path: str = "", content: str = ""
) -> Dict[str, Any]:
    """Write one Markdown memory file atomically (strict path validation).

    The file is written to a temporary file in the same directory and
    then moved into place with ``os.replace``, so a reader never sees a
    half-written file. Raises ValueError on an invalid path.
    """
    if not isinstance(content, str):
        raise ValueError("content must be a string")
    base = resolve_workspace_dir(workspace_dir)
    resolved, rel_posix = _validate_memory_path(base, rel_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(resolved.parent), prefix=resolved.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, resolved)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return {
        "ok": True,
        "path": rel_posix,
        "modified": _iso_from_mtime(resolved.stat().st_mtime),
    }


# ---------------------------------------------------------------------------
# Memory graph (episodes + entities, from the read-only DB)
# ---------------------------------------------------------------------------
def _octant_from_pad(pad_json: Any) -> str:
    """Derive the PAD mood-octant label from a stored pad_json value.

    Reuses ``PADVector.octant_label()`` from the core schemas when it can
    be imported; otherwise falls back to the same sign-based rules.
    Returns "unknown" when no usable PAD vector is present.
    """
    try:
        pad = json.loads(pad_json) if isinstance(pad_json, str) else {}
        p = float(pad.get("P", 0.0))
        a = float(pad.get("A", 0.0))
        d = float(pad.get("D", 0.0))
    except (ValueError, TypeError, AttributeError):
        return "unknown"
    try:
        from ai_cognitive_core.schemas import PADVector

        return PADVector(P=p, A=a, D=d).octant_label()
    except Exception:
        if p >= 0 and a >= 0 and d >= 0:
            return "Exuberant"
        if p >= 0 and a >= 0:
            return "Dependent"
        if p >= 0 and a < 0 and d >= 0:
            return "Relaxed"
        if p >= 0 and a < 0:
            return "Docile"
        if p < 0 and a >= 0 and d >= 0:
            return "Hostile"
        if p < 0 and a >= 0:
            return "Anxious"
        if p < 0 and a < 0 and d >= 0:
            return "Disdainful"
        return "Bored/Depressed"


def _is_entity_token(token: Any) -> bool:
    """Accept only clean lowercase keyword tokens as graph entities."""
    return isinstance(token, str) and bool(_ENTITY_TOKEN_RE.match(token))


def get_graph(
    state_dir: Optional[Any] = None, limit: int = GRAPH_DEFAULT_LIMIT
) -> Dict[str, Any]:
    """Build the episode/entity graph from the read-only memory DB.

    Nodes: the newest episodic nodes (bounded by ``limit``) plus the most
    frequent entity keywords found in their ``entities_json`` lists, plus
    short ``semantic_facts`` subjects. Edges: episode -> entity
    ("mentions"). Node weight reflects memory importance
    (``importance_score`` for episodes, mention frequency for entities).
    Degrades gracefully to an empty graph when the DB or a table is
    missing — it never raises for missing data.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = GRAPH_DEFAULT_LIMIT
    limit = max(1, min(limit, GRAPH_MAX_LIMIT))

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    try:
        conn = read_memory_db(state_dir)
    except (FileNotFoundError, sqlite3.Error):
        return {"nodes": nodes, "edges": edges}

    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "episodic_nodes" not in tables:
            return {"nodes": nodes, "edges": edges}

        rows = conn.execute(
            "SELECT node_id, timestamp_utc, summary, entities_json, pad_json,"
            " importance_score FROM episodic_nodes"
            " ORDER BY timestamp_utc DESC LIMIT ?",
            (limit,),
        ).fetchall()

        # Episode nodes + per-episode entity mentions.
        entity_mentions: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            node_id = row["node_id"]
            summary = (row["summary"] or "").replace("\n", " ").strip()
            label = summary[:60] + ("…" if len(summary) > 60 else "")
            try:
                weight = float(row["importance_score"])
            except (TypeError, ValueError):
                weight = 1.0
            weight = round(max(0.0, min(2.0, weight)) or 1.0, 4)
            nodes.append(
                {
                    "id": node_id,
                    "label": label or node_id,
                    "type": "episode",
                    "emotion": _octant_from_pad(row["pad_json"]),
                    "weight": weight,
                    "created": row["timestamp_utc"] or "",
                }
            )
            try:
                entities = json.loads(row["entities_json"] or "[]")
            except (ValueError, TypeError):
                entities = []
            for token in entities if isinstance(entities, list) else []:
                if _is_entity_token(token):
                    entity_mentions.setdefault(token, []).append(nodes[-1])

        # Entity nodes: the most frequently mentioned keywords.
        counts = Counter({token: len(eps) for token, eps in entity_mentions.items()})
        top_entities = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[
            :GRAPH_MAX_ENTITIES
        ]
        top_tokens = {token for token, _ in top_entities}
        for token, count in top_entities:
            mentioning = entity_mentions[token]
            dominant_emotion = Counter(
                ep["emotion"] for ep in mentioning if ep["emotion"] != "unknown"
            ).most_common(1)
            nodes.append(
                {
                    "id": f"ent_{token}",
                    "label": token,
                    "type": "entity",
                    "emotion": dominant_emotion[0][0] if dominant_emotion else "unknown",
                    "weight": round(0.5 + min(count, 10) * 0.1, 4),
                    "created": min(
                        (ep["created"] for ep in mentioning if ep["created"]),
                        default="",
                    ),
                }
            )
            for episode in mentioning:
                edges.append(
                    {"from": episode["id"], "to": f"ent_{token}", "label": "mentions"}
                )

        # Semantic-fact subjects as additional entity nodes (no edges:
        # their objects are free text, not graph targets).
        if "semantic_facts" in tables:
            existing_ids = {node["id"] for node in nodes}
            for row in conn.execute(
                "SELECT subject, updated_utc FROM semantic_facts"
                " ORDER BY updated_utc DESC LIMIT ?",
                (GRAPH_MAX_FACTS,),
            ).fetchall():
                subject = (row["subject"] or "").strip()
                if not _FACT_SUBJECT_RE.match(subject):
                    continue
                slug = re.sub(r"[^A-Za-z0-9_\-]", "_", subject).lower()
                node_id = f"ent_fact_{slug}"
                if node_id in existing_ids:
                    continue
                existing_ids.add(node_id)
                nodes.append(
                    {
                        "id": node_id,
                        "label": subject,
                        "type": "entity",
                        "emotion": "unknown",
                        "weight": 1.0,
                        "created": row["updated_utc"] or "",
                    }
                )
    except sqlite3.Error:
        return {"nodes": [], "edges": []}
    finally:
        conn.close()
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Status payload (pure computation over heart_state + sync_meta)
# ---------------------------------------------------------------------------
def _pad_vector(state: Dict[str, Any]) -> Tuple[float, float, float]:
    pad = state.get("pad_current") or {}
    try:
        return float(pad.get("P", 0.0)), float(pad.get("A", 0.0)), float(pad.get("D", 0.0))
    except (TypeError, ValueError):
        return 0.0, 0.0, 0.0


def _pad_intensity(p: float, a: float, d: float) -> Tuple[float, str]:
    """PAD magnitude + intensity label, reusing the core helper when possible."""
    try:
        from ai_cognitive_core.heart.layers.l3_mood_space import compute_pad_intensity
        from ai_cognitive_core.schemas import PADVector

        return compute_pad_intensity(PADVector(P=p, A=a, D=d))
    except Exception:
        magnitude = round(math.sqrt(p * p + a * a + d * d), 4)
        if magnitude <= 0.35:
            return magnitude, "mild"
        if magnitude <= 0.75:
            return magnitude, "moderate"
        return magnitude, "intense"


def _pad_trajectory(state: Dict[str, Any]) -> Dict[str, Any]:
    """PAD delta + direction; prefers the stored delta, else recomputes."""
    stored = state.get("last_pad_delta") or {}
    if isinstance(stored, dict) and stored.get("direction"):
        try:
            return {
                "direction": str(stored["direction"]),
                "dp": round(float(stored.get("dp", 0.0)), 4),
                "da": round(float(stored.get("da", 0.0)), 4),
                "dd": round(float(stored.get("dd", 0.0)), 4),
            }
        except (TypeError, ValueError):
            pass
    try:
        from ai_cognitive_core.heart.layers.l3_mood_space import compute_pad_trajectory
        from ai_cognitive_core.schemas import PADVector

        p, a, d = _pad_vector(state)
        prev = state.get("prev_pad") or {}
        prev_pad = PADVector(
            P=float(prev.get("P", p)), A=float(prev.get("A", a)), D=float(prev.get("D", d))
        )
        return compute_pad_trajectory(prev_pad, PADVector(P=p, A=a, D=d))
    except Exception:
        return {"direction": "steady", "dp": 0.0, "da": 0.0, "dd": 0.0}


def _circadian() -> Tuple[int, str]:
    """Current local hour + circadian phase, reusing the core helper."""
    try:
        from ai_cognitive_core.heart.layers.l1_neurochemical import (
            current_local_hour,
            get_circadian_phase,
        )

        hour = int(current_local_hour())
        return hour, get_circadian_phase(hour)
    except Exception:
        hour = datetime.now(timezone.utc).hour
        # Fallback assumes WIB (UTC+7), matching the core default.
        hour = (hour + 7) % 24
        if hour >= 23 or hour < 5:
            return hour, "late_night"
        if 5 <= hour < 11:
            return hour, "morning"
        if 11 <= hour < 18:
            return hour, "daytime"
        return hour, "evening"


def _emotional_nuance(
    state: Dict[str, Any],
    p: float,
    a: float,
    d: float,
    intensity: str,
    energy: float,
    phase: str,
) -> str:
    """Fine-grained emotional nuance (v0.6.0 PAD expansion)."""
    try:
        from ai_cognitive_core.heart.layers.l3_mood_space import (
            classify_emotional_nuance,
        )
        from ai_cognitive_core.schemas import PADVector

        affects = state.get("primary_affects") or {}
        dominant = "CARE"
        if isinstance(affects, dict) and affects:
            dominant = str(max(affects, key=lambda k: float(affects[k] or 0.0)))
        return classify_emotional_nuance(
            PADVector(P=p, A=a, D=d), intensity, dominant, energy, phase
        )
    except Exception:
        return "Calm"


def build_status(
    state: Dict[str, Any],
    sync_meta: Dict[str, Any],
    total_turns: int,
    core_version: str,
) -> Dict[str, Any]:
    """Assemble the /api/status payload from heart state + sync metadata.

    Every field degrades to a sensible default when the underlying data
    is missing, so the endpoint never fails with a 500 on partial state.
    """
    neuro = state.get("neuro") or {}
    try:
        energy = float(neuro.get("energy", 0.0))
    except (TypeError, ValueError):
        energy = 0.0

    def _neuro_value(key: str) -> float:
        try:
            return round(float(neuro.get(key, 0.0)), 4)
        except (TypeError, ValueError):
            return 0.0

    p, a, d = _pad_vector(state)
    magnitude, intensity = _pad_intensity(p, a, d)
    trajectory = _pad_trajectory(state)
    hour, phase = _circadian()
    nuance = _emotional_nuance(state, p, a, d, intensity, energy, phase)
    octant = _octant_from_pad(json.dumps({"P": p, "A": a, "D": d}))

    try:
        streak = int(state.get("high_pleasure_streak", 0))
    except (TypeError, ValueError):
        streak = 0
    try:
        trust = round(float(state.get("trust_score", 0.0)), 4)
    except (TypeError, ValueError):
        trust = 0.0
    stage = str(state.get("relationship_stage") or "unknown")
    last_sync_utc = sync_meta.get("last_sync_utc")

    heartbeat_summary = (
        f"Energi {energy:.2f} · mood {octant} · "
        f"{_CIRCADIAN_LABEL_ID.get(phase, phase)} · {int(total_turns)} turn"
    )

    return {
        "core_version": core_version,
        "energy": round(energy, 4),
        "neuro": {
            "cortisol": _neuro_value("cortisol"),
            "oxytocin": _neuro_value("oxytocin"),
            "dopamine": _neuro_value("dopamine"),
            "serotonin": _neuro_value("serotonin"),
            "noradrenaline": _neuro_value("noradrenaline"),
        },
        "pad_current": {"P": round(p, 4), "A": round(a, 4), "D": round(d, 4)},
        "pad_magnitude": magnitude,
        "mood_intensity": intensity,
        "emotional_nuance": nuance,
        "pad_trajectory": trajectory,
        "high_pleasure_streak": streak,
        "circadian": {"local_hour": hour, "phase": phase},
        "heartbeat": {"summary": heartbeat_summary},
        "drive_last_sync": {
            "last_sync_utc": last_sync_utc,
            "ago_seconds": sync_meta.get("ago_seconds"),
            "ago_human": sync_meta.get("ago_human", "tidak diketahui"),
            "connected": bool(last_sync_utc),
        },
        "relationship": {"trust_score": trust, "stage": stage},
        "total_turns": int(total_turns),
    }
