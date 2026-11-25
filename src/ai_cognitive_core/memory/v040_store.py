"""
Penyimpanan & seleksi fitur v0.4.0 (Curiosity, Niat mandiri, Mimpi, Foto).

Semua fungsi menerima koneksi sqlite3 yang sudah dibuka; pemanggil yang
memiliki transaksi (commit_turn_bundle) memanggil dengan commit=False agar
episode + penanda giliran + aksi v0.4.0 tersimpan dalam SATU transaksi.
Pemakaian mandiri memakai commit=True (default).

Aturan keras yang ditegakkan di sini:
- Perceive mengembalikan MAKSIMAL 1 curiosity_prompt, 1 proactive_intent,
  1 dream_idea, dan 1 photo_reference.
- Curiosity tidak ditawarkan saat turn sensitif, mendesak, atau berfokus tugas.
- Pengingat berbasis jadwal/perkiraan saja — tidak pernah diklaim "terdeteksi".
- Mimpi tidak pernah dipromosikan menjadi fakta (tidak ada jalur tulis ke
  semantic_facts dari modul ini).
- Momen foto hanya dirujuk bila consent_status == "granted" dan relevan,
  selalu dengan catatan bahwa rujukan berasal dari caption yang disimpan.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from ai_cognitive_core import config
from ai_cognitive_core.schemas import utc_now_iso

_STOPWORDS = {
    "yang", "dan", "di", "ke", "dari", "aku", "kamu", "saya", "ini", "itu",
    "ada", "sudah", "lagi", "banget", "sih", "dong", "ya", "nggak", "tidak",
    "apa", "gimana", "kenapa", "kapan", "dimana", "dengan", "untuk", "atau",
    "juga", "saja", "aja", "kok", "kan", "tuh", "nih", "deh", "loh", "lah",
}

_NEGATIVE_OCTANTS = {"Hostile", "Anxious", "Disdainful", "Bored/Depressed"}
_BLOCKING_BUBBLE_STYLES = {"exhausted_sleepy_1_bubble", "dry_short_1_bubble"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _norm_text(text: str) -> str:
    return " ".join(text.lower().split())


def _tokens(text: str) -> set:
    words = set()
    for raw in text.lower().replace(",", " ").replace(".", " ").replace("!", " ").replace("?", " ").split():
        w = raw.strip("'\"()[]{}:;")
        if len(w) >= 3 and w not in _STOPWORDS:
            words.add(w)
    return words


def _token_overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


def _json_list(values: Optional[List[str]]) -> str:
    return json.dumps(list(values or []), ensure_ascii=False)


def _from_json_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return [str(v) for v in val] if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _maybe_commit(conn: sqlite3.Connection, commit: bool) -> None:
    if commit:
        conn.commit()


# ---------------------------------------------------------------------------
# Meta key-value (schema_meta)
# ---------------------------------------------------------------------------

def get_meta(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str, commit: bool = True) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)", (key, value)
    )
    _maybe_commit(conn, commit)


# ---------------------------------------------------------------------------
# Curiosity
# ---------------------------------------------------------------------------

def propose_question(
    conn: sqlite3.Connection,
    text: str,
    topic: str = "",
    priority: float = 0.5,
    context_tags: Optional[List[str]] = None,
    expires_at: Optional[str] = None,
    source: str = "supervisor",
    commit: bool = True,
) -> dict:
    """Simpan pertanyaan curiosity (validasi + dedup + cap)."""
    text = (text or "").strip()
    if not text:
        return {"stored": False, "question_id": None, "reason": "empty_text"}
    if len(text) > 500:
        return {"stored": False, "question_id": None, "reason": "text_too_long"}

    expire_questions(conn, commit=False)
    norm = _norm_text(text)
    rows = conn.execute(
        "SELECT question_id, text, topic FROM curiosity_questions WHERE status = 'pending'"
    ).fetchall()
    for qid, existing_text, existing_topic in rows:
        if _norm_text(existing_text) == norm:
            return {"stored": False, "question_id": qid, "reason": "duplicate_text"}
        if topic and existing_topic == topic and _token_overlap(text, existing_text) >= 0.6:
            return {"stored": False, "question_id": qid, "reason": "duplicate_topic"}

    if len(rows) >= config.MAX_PENDING_CURIOSITY:
        return {"stored": False, "question_id": None, "reason": "cap_reached"}

    if not expires_at:
        expires_at = (_now() + timedelta(days=config.CURIOSITY_DEFAULT_TTL_DAYS)).isoformat()
    qid = f"cq_{uuid.uuid4().hex[:10]}"
    conn.execute(
        """
        INSERT INTO curiosity_questions
        (question_id, text, topic, created_at, priority, status,
         last_offered_at, context_tags_json, expires_at, source)
        VALUES (?, ?, ?, ?, ?, 'pending', NULL, ?, ?, ?)
        """,
        (
            qid, text, topic, utc_now_iso(),
            max(0.0, min(1.0, float(priority))),
            _json_list(context_tags), expires_at, source,
        ),
    )
    _maybe_commit(conn, commit)
    return {"stored": True, "question_id": qid, "reason": "stored"}


def _curiosity_gate(
    user_text: str,
    mood_octant: str,
    bubble_style: str,
    texting_style: str,
) -> Optional[str]:
    """Kembalikan alasan penundaan, atau None jika boleh ditawarkan."""
    if not config.ENABLE_CURIOSITY:
        return "feature_disabled"
    if mood_octant in _NEGATIVE_OCTANTS:
        return "negative_mood"
    if bubble_style in _BLOCKING_BUBBLE_STYLES:
        return "low_energy_or_dry"
    if texting_style in {"dry_short", "cold_passive_aggressive", "shouting_caps"}:
        return "user_texting_style"
    lower = user_text.lower()
    if any(kw in lower for kw in config.CURIOSITY_SENSITIVE_KEYWORDS):
        return "sensitive_context"
    if any(kw in lower for kw in config.CURIOSITY_TASK_KEYWORDS):
        return "task_focused"
    return None


def select_curiosity_prompt(
    conn: sqlite3.Connection,
    *,
    user_text: str,
    mood_octant: str,
    bubble_style: str,
    texting_style: str,
    total_turns: int,
    commit: bool = True,
) -> Optional[dict]:
    """Pilih MAKSIMAL 1 pertanyaan untuk perceive ini (atau None)."""
    gate_reason = _curiosity_gate(user_text, mood_octant, bubble_style, texting_style)
    if gate_reason:
        return None

    now = _now()
    expire_questions(conn, commit=False)

    # Cooldown waktu + cooldown turn.
    last_offered = _parse_iso(get_meta(conn, "last_curiosity_offered_at"))
    if last_offered and (now - last_offered) < timedelta(minutes=config.CURIOSITY_COOLDOWN_MINUTES):
        return None
    last_turn_raw = get_meta(conn, "last_curiosity_offered_turn")
    if last_turn_raw is not None:
        try:
            if total_turns - int(last_turn_raw) < config.CURIOSITY_MIN_TURNS_BETWEEN:
                return None
        except ValueError:
            pass

    rows = conn.execute(
        """
        SELECT question_id, text, topic, priority, context_tags_json, created_at
        FROM curiosity_questions WHERE status = 'pending'
        ORDER BY priority DESC, created_at ASC
        LIMIT ?
        """,
        (config.CURIOSITY_CANDIDATE_BUDGET,),
    ).fetchall()
    if not rows:
        return None

    # Skor: prioritas + relevansi topik terhadap pesan saat ini.
    best = None
    best_score = -1.0
    for qid, text, topic, priority, tags_json, created_at in rows:
        relevance = 0.0
        topic_text = f"{topic} {' '.join(_from_json_list(tags_json))}"
        if topic_text.strip():
            relevance = _token_overlap(user_text, topic_text)
        score = 0.6 * float(priority) + 0.4 * relevance
        if score > best_score:
            best_score = score
            best = {
                "question_id": qid,
                "text": text,
                "topic": topic,
                "priority": float(priority),
                "score": round(score, 3),
            }

    if best is None:
        return None
    conn.execute(
        "UPDATE curiosity_questions SET last_offered_at = ? WHERE question_id = ?",
        (now.isoformat(), best["question_id"]),
    )
    set_meta(conn, "last_curiosity_offered_at", now.isoformat(), commit=False)
    set_meta(conn, "last_curiosity_offered_turn", str(total_turns), commit=False)
    _maybe_commit(conn, commit)
    return best


def mark_question_asked(conn: sqlite3.Connection, question_id: str, commit: bool = True) -> bool:
    cur = conn.execute(
        "UPDATE curiosity_questions SET status = 'asked' WHERE question_id = ? AND status = 'pending'",
        (question_id,),
    )
    _maybe_commit(conn, commit)
    return cur.rowcount > 0


def dismiss_question(conn: sqlite3.Connection, question_id: str, commit: bool = True) -> bool:
    cur = conn.execute(
        "UPDATE curiosity_questions SET status = 'dismissed' WHERE question_id = ? AND status IN ('pending', 'asked')",
        (question_id,),
    )
    _maybe_commit(conn, commit)
    return cur.rowcount > 0


def expire_questions(conn: sqlite3.Connection, now: Optional[datetime] = None, commit: bool = True) -> int:
    now = now or _now()
    cur = conn.execute(
        "UPDATE curiosity_questions SET status = 'dismissed' WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < ?",
        (now.isoformat(),),
    )
    _maybe_commit(conn, commit)
    return cur.rowcount


def count_pending_questions(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM curiosity_questions WHERE status = 'pending'"
    ).fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Niat mandiri / pengingat
# ---------------------------------------------------------------------------

def create_reminder(
    conn: sqlite3.Connection,
    text: str,
    due_at: Optional[str] = None,
    trigger_condition: Optional[str] = None,
    source: str = "supervisor",
    priority: float = 0.5,
    repeat_policy: str = "none",
    commit: bool = True,
) -> dict:
    """Simpan niat pengingat (validasi + dedup + cap)."""
    text = (text or "").strip()
    if not text:
        return {"stored": False, "intent_id": None, "reason": "empty_text"}
    if not due_at and not trigger_condition:
        return {"stored": False, "intent_id": None, "reason": "no_trigger"}
    if due_at and _parse_iso(due_at) is None:
        return {"stored": False, "intent_id": None, "reason": "bad_due_at"}
    if trigger_condition:
        kind = trigger_condition.split(":", 1)[0]
        if kind not in {"time", "keyword"}:
            return {"stored": False, "intent_id": None, "reason": "bad_trigger_condition"}
        if kind == "time" and _parse_iso(trigger_condition.split(":", 1)[1]) is None:
            return {"stored": False, "intent_id": None, "reason": "bad_trigger_condition"}
    if repeat_policy not in config.REMINDER_REPEAT_POLICIES:
        return {"stored": False, "intent_id": None, "reason": "bad_repeat_policy"}

    norm = _norm_text(text)
    rows = conn.execute(
        "SELECT intent_id, text, due_at FROM reminder_intents WHERE status IN ('pending', 'surfaced')"
    ).fetchall()
    for iid, existing_text, existing_due in rows:
        if _norm_text(existing_text) == norm and existing_due == due_at:
            return {"stored": False, "intent_id": iid, "reason": "duplicate"}
    if len(rows) >= config.MAX_PENDING_REMINDERS:
        return {"stored": False, "intent_id": None, "reason": "cap_reached"}

    iid = f"ri_{uuid.uuid4().hex[:10]}"
    conn.execute(
        """
        INSERT INTO reminder_intents
        (intent_id, text, created_at, due_at, trigger_condition, source,
         priority, status, last_surfaced_at, repeat_policy, basis)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?, 'schedule')
        """,
        (
            iid, text, utc_now_iso(), due_at, trigger_condition, source,
            max(0.0, min(1.0, float(priority))), repeat_policy,
        ),
    )
    _maybe_commit(conn, commit)
    return {"stored": True, "intent_id": iid, "reason": "stored"}


def _trigger_due(trigger_condition: Optional[str], due_at: Optional[str], user_text: str, now: datetime) -> bool:
    if due_at:
        due = _parse_iso(due_at)
        if due and due <= now:
            return True
    if trigger_condition:
        kind, _, value = trigger_condition.partition(":")
        if kind == "time":
            due = _parse_iso(value)
            if due and due <= now:
                return True
        elif kind == "keyword" and value.strip():
            if value.strip().lower() in user_text.lower():
                return True
    return False


def select_due_reminder(
    conn: sqlite3.Connection,
    *,
    user_text: str,
    commit: bool = True,
) -> Optional[dict]:
    """Pilih MAKSIMAL 1 pengingat yang jatuh tempo untuk perceive ini."""
    if not config.ENABLE_REMINDERS:
        return None
    now = _now()
    rows = conn.execute(
        """
        SELECT intent_id, text, due_at, trigger_condition, priority, last_surfaced_at, basis
        FROM reminder_intents WHERE status IN ('pending', 'surfaced')
        ORDER BY priority DESC, due_at ASC
        LIMIT ?
        """,
        (config.REMINDER_CANDIDATE_BUDGET,),
    ).fetchall()

    for iid, text, due_at, trigger, priority, last_surfaced, basis in rows:
        last = _parse_iso(last_surfaced)
        if last and (now - last) < timedelta(minutes=config.REMINDER_COOLDOWN_MINUTES):
            continue
        if not _trigger_due(trigger, due_at, user_text, now):
            continue
        conn.execute(
            "UPDATE reminder_intents SET status = 'surfaced', last_surfaced_at = ? WHERE intent_id = ?",
            (now.isoformat(), iid),
        )
        _maybe_commit(conn, commit)
        return {
            "intent_id": iid,
            "text": text,
            "due_at": due_at,
            "priority": float(priority),
            "basis": basis or "schedule",
            # Penanda jujur: pengingat ini berdasarkan jadwal/perkiraan,
            # BUKAN hasil deteksi langsung kondisi eksternal.
            "basis_note": "Berdasarkan jadwal/perkiraan yang disimpan, bukan deteksi langsung.",
        }
    return None


def apply_reminder_action(
    conn: sqlite3.Connection,
    intent_id: str,
    action: str,
    snooze_until: Optional[str] = None,
    commit: bool = True,
) -> bool:
    """complete | dismiss | snooze (snooze butuh snooze_until ISO yang valid)."""
    if action == "complete":
        cur = conn.execute(
            "UPDATE reminder_intents SET status = 'completed' WHERE intent_id = ? AND status IN ('pending', 'surfaced')",
            (intent_id,),
        )
    elif action == "dismiss":
        cur = conn.execute(
            "UPDATE reminder_intents SET status = 'dismissed' WHERE intent_id = ? AND status IN ('pending', 'surfaced')",
            (intent_id,),
        )
    elif action == "snooze":
        due = _parse_iso(snooze_until)
        if due is None:
            return False
        cur = conn.execute(
            "UPDATE reminder_intents SET status = 'pending', due_at = ?, last_surfaced_at = NULL WHERE intent_id = ? AND status IN ('pending', 'surfaced')",
            (due.isoformat(), intent_id),
        )
    else:
        return False
    _maybe_commit(conn, commit)
    return cur.rowcount > 0


def sweep_expired_reminders(conn: sqlite3.Connection, now: Optional[datetime] = None, commit: bool = True) -> dict:
    """Jalankan saat sleep cycle: niat kedaluwarsa di-dismiss / di-reschedule."""
    now = now or _now()
    grace_cutoff = now - timedelta(hours=config.REMINDER_EXPIRY_GRACE_HOURS)
    rows = conn.execute(
        """
        SELECT intent_id, due_at, repeat_policy FROM reminder_intents
        WHERE status IN ('pending', 'surfaced') AND due_at IS NOT NULL AND due_at < ?
        """,
        (grace_cutoff.isoformat(),),
    ).fetchall()
    expired = 0
    rescheduled = 0
    for iid, due_at, repeat_policy in rows:
        if repeat_policy == "daily":
            due = _parse_iso(due_at) or now
            # Geser ke depan per 24 jam sampai melewati "sekarang".
            while due <= now:
                due += timedelta(days=1)
            conn.execute(
                "UPDATE reminder_intents SET due_at = ?, status = 'pending', last_surfaced_at = NULL WHERE intent_id = ?",
                (due.isoformat(), iid),
            )
            rescheduled += 1
        else:
            conn.execute(
                "UPDATE reminder_intents SET status = 'dismissed' WHERE intent_id = ?",
                (iid,),
            )
            expired += 1
    _maybe_commit(conn, commit)
    return {"expired": expired, "rescheduled": rescheduled}


def count_pending_reminders(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM reminder_intents WHERE status IN ('pending', 'surfaced')"
    ).fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Mimpi
# ---------------------------------------------------------------------------

def store_dream(
    conn: sqlite3.Connection,
    *,
    source_episode_ids: List[str],
    theme: str,
    idea_text: str,
    dream_story: str = "",
    category: str = "other",
    novelty_score: float = 0.5,
    sensitivity_tags: Optional[List[str]] = None,
    commit: bool = True,
) -> dict:
    """Simpan DreamRecord (dedup berdasarkan tema + set episode sumber)."""
    idea_text = (idea_text or "").strip()
    if not idea_text:
        return {"stored": False, "dream_id": None, "reason": "empty_idea"}
    if category not in {"date_idea", "photo_idea", "other"}:
        category = "other"
    theme = (theme or "").strip()
    source_key = _json_list(sorted(source_episode_ids or []))

    rows = conn.execute(
        "SELECT dream_id, theme, source_episode_ids_json FROM dream_records WHERE status IN ('stored', 'surfaced')"
    ).fetchall()
    for did, existing_theme, existing_sources in rows:
        if existing_theme == theme and _json_list(sorted(_from_json_list(existing_sources))) == source_key:
            return {"stored": False, "dream_id": did, "reason": "duplicate_dream"}

    # Prune mimpi tersimpan tertua bila melebihi batas.
    if len(rows) >= config.MAX_STORED_DREAMS:
        oldest = conn.execute(
            "SELECT dream_id FROM dream_records WHERE status = 'stored' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if oldest:
            conn.execute("DELETE FROM dream_records WHERE dream_id = ?", (oldest[0],))

    did = f"dr_{uuid.uuid4().hex[:10]}"
    conn.execute(
        """
        INSERT INTO dream_records
        (dream_id, created_at, source_episode_ids_json, theme, dream_story, idea_text,
         category, novelty_score, status, sensitivity_tags_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'stored', ?)
        """,
        (
            did, utc_now_iso(), source_key, theme, (dream_story or "").strip(), idea_text, category,
            max(0.0, min(1.0, float(novelty_score))), _json_list(sensitivity_tags),
        ),
    )
    _maybe_commit(conn, commit)
    return {"stored": True, "dream_id": did, "reason": "stored"}


def select_dream_to_surface(conn: sqlite3.Connection, commit: bool = True) -> Optional[dict]:
    """Ambil SATU mimpi tertua yang belum pernah ditampilkan (atau None)."""
    if not config.ENABLE_DREAMS:
        return None
    row = conn.execute(
        """
        SELECT dream_id, theme, COALESCE(dream_story, ''), idea_text, category, novelty_score,
               source_episode_ids_json, created_at
        FROM dream_records WHERE status = 'stored'
        ORDER BY created_at ASC LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    did, theme, dream_story, idea_text, category, novelty, sources_json, created_at = row
    conn.execute(
        "UPDATE dream_records SET status = 'surfaced' WHERE dream_id = ?", (did,)
    )
    _maybe_commit(conn, commit)
    return {
        "dream_id": did,
        "theme": theme,
        "dream_story": dream_story,
        "idea_text": idea_text,
        "category": category,
        "novelty_score": float(novelty),
        "source_episode_ids": _from_json_list(sources_json),
        "created_at": created_at,
        # Penanda jujur: ini ide generatif dari sleep cycle, BUKAN kejadian nyata.
        "generative_note": "Ide generatif dari mimpi saat tidur — bukan kejadian nyata.",
    }


def dismiss_dream(conn: sqlite3.Connection, dream_id: str, commit: bool = True) -> bool:
    cur = conn.execute(
        "UPDATE dream_records SET status = 'dismissed' WHERE dream_id = ? AND status IN ('stored', 'surfaced')",
        (dream_id,),
    )
    _maybe_commit(conn, commit)
    return cur.rowcount > 0


def count_stored_dreams(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM dream_records WHERE status = 'stored'"
    ).fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Ingatan foto
# ---------------------------------------------------------------------------

def store_photo_moment(
    conn: sqlite3.Connection,
    *,
    caption: str,
    people: Optional[List[str]] = None,
    place: str = "",
    event_tags: Optional[List[str]] = None,
    source_ref: str = "",
    consent_status: str = "unknown",
    timestamp: Optional[str] = None,
    feeling: str = "",
    when_label: str = "",
    linked_episode_ids: Optional[List[str]] = None,
    commit: bool = True,
) -> dict:
    """Simpan momen foto dari caption/metadata eksplisit (tanpa file gambar)."""
    caption = (caption or "").strip()
    if not caption:
        return {"stored": False, "moment_id": None, "reason": "empty_caption"}
    if consent_status not in {"granted", "revoked", "unknown"}:
        consent_status = "unknown"
    if timestamp and _parse_iso(timestamp) is None:
        return {"stored": False, "moment_id": None, "reason": "bad_timestamp"}

    mid = f"pm_{uuid.uuid4().hex[:10]}"
    conn.execute(
        """
        INSERT INTO photo_moments
        (moment_id, timestamp, caption, people_json, place, event_tags_json,
         source_ref, consent_status, feeling, when_label, linked_episode_ids_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            mid, timestamp or utc_now_iso(), caption, _json_list(people),
            place or "", _json_list(event_tags), source_ref or "",
            consent_status, (feeling or "").strip(), (when_label or "").strip(),
            _json_list(linked_episode_ids),
        ),
    )
    _maybe_commit(conn, commit)
    return {"stored": True, "moment_id": mid, "reason": "stored"}


def select_photo_reference(conn: sqlite3.Connection, *, user_text: str) -> Optional[dict]:
    """Rujuk SATU momen foto bila relevan (consent granted + kata kunci cocok)."""
    if not config.ENABLE_PHOTO_MEMORY:
        return None
    rows = conn.execute(
        """
        SELECT moment_id, timestamp, caption, people_json, place,
               event_tags_json, source_ref, COALESCE(feeling, ''), COALESCE(when_label, '')
        FROM photo_moments WHERE consent_status IN ({})
        ORDER BY timestamp DESC LIMIT ?
        """.format(",".join("?" * len(config.PHOTO_SURFACEABLE_CONSENT))),
        (*config.PHOTO_SURFACEABLE_CONSENT, config.PHOTO_CANDIDATE_BUDGET * 10),
    ).fetchall()
    if not rows:
        return None

    query_tokens = _tokens(user_text)
    best = None
    best_overlap = 0
    for mid, ts, caption, people_json, place, tags_json, source_ref, feeling, when_label in rows:
        people_list = _from_json_list(people_json)
        tags_list = _from_json_list(tags_json)
        haystack = f"{caption} {place} {feeling} {when_label} {' '.join(tags_list)} {' '.join(people_list)}"
        overlap = len(query_tokens & _tokens(haystack))
        if overlap >= config.PHOTO_MIN_KEYWORD_OVERLAP and overlap > best_overlap:
            best_overlap = overlap
            best = {
                "moment_id": mid,
                "timestamp": ts,
                "when_label": when_label,
                "caption": caption,
                "people": people_list,
                "place": place,
                "feeling": feeling,
                "event_tags": tags_list,
                "source_ref": source_ref,
                "keyword_overlap": overlap,
                "uncertainty_note": "Berdasarkan caption & catatan momen yang disimpan — modul tidak melihat isi foto.",
            }
    return best


def correct_photo_moment(
    conn: sqlite3.Connection,
    moment_id: str,
    commit: bool = True,
    **fields,
) -> bool:
    """Koreksi metadata momen foto (caption, place, people, event_tags, consent)."""
    allowed = {"caption", "place", "consent_status", "feeling", "when_label"}
    updates = {}
    for key, value in fields.items():
        if key in allowed and isinstance(value, str):
            updates[key] = value
        elif key in {"people", "event_tags", "linked_episode_ids"} and isinstance(value, list):
            updates[f"{key}_json" if key != "linked_episode_ids" else "linked_episode_ids_json"] = _json_list(value)
    if not updates:
        return False
    if "consent_status" in updates and updates["consent_status"] not in {"granted", "revoked", "unknown"}:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    cur = conn.execute(
        f"UPDATE photo_moments SET {set_clause} WHERE moment_id = ?",
        (*updates.values(), moment_id),
    )
    _maybe_commit(conn, commit)
    return cur.rowcount > 0


def delete_photo_moment(conn: sqlite3.Connection, moment_id: str, commit: bool = True) -> bool:
    """Hapus momen foto (permintaan lupa dihapus total dari DB lokal)."""
    cur = conn.execute("DELETE FROM photo_moments WHERE moment_id = ?", (moment_id,))
    _maybe_commit(conn, commit)
    return cur.rowcount > 0


def count_photo_moments(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM photo_moments").fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Penanda giliran (turn identity — fondasi laporan ekspansi §4)
# ---------------------------------------------------------------------------

def get_turn_marker(conn: sqlite3.Connection, turn_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT turn_id, phase, created_at, updated_at, episode_id, drained "
        "FROM turn_markers WHERE turn_id = ?",
        (turn_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "turn_id": row[0],
        "phase": row[1],
        "created_at": row[2],
        "updated_at": row[3],
        "episode_id": row[4],
        "drained": bool(row[5]),
    }


def mark_turn_perceived(conn: sqlite3.Connection, turn_id: str, drained: bool, commit: bool = True) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO turn_markers (turn_id, phase, created_at, updated_at, episode_id, drained)
        VALUES (?, 'perceived', ?, ?, NULL, ?)
        ON CONFLICT(turn_id) DO UPDATE SET phase = 'perceived', updated_at = excluded.updated_at
        """,
        (turn_id, now, now, 1 if drained else 0),
    )
    _maybe_commit(conn, commit)


def mark_turn_committed(conn: sqlite3.Connection, turn_id: str, episode_id: str, commit: bool = True) -> bool:
    """Tandai giliran selesai. False = sudah pernah di-commit (duplikat)."""
    existing = get_turn_marker(conn, turn_id)
    if existing and existing["phase"] == "committed":
        return False
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO turn_markers (turn_id, phase, created_at, updated_at, episode_id, drained)
        VALUES (?, 'committed', ?, ?, ?, 0)
        ON CONFLICT(turn_id) DO UPDATE SET
            phase = 'committed', updated_at = excluded.updated_at,
            episode_id = excluded.episode_id
        """,
        (turn_id, now, now, episode_id),
    )
    _maybe_commit(conn, commit)
    return True


def is_turn_committed(conn: sqlite3.Connection, turn_id: str) -> bool:
    marker = get_turn_marker(conn, turn_id)
    return bool(marker and marker["phase"] == "committed")


# ---------------------------------------------------------------------------
# Telemetri energi (TANPA konten percakapan)
# ---------------------------------------------------------------------------

def record_telemetry(
    conn: sqlite3.Connection,
    *,
    turn_id: Optional[str],
    drain: Optional[float] = None,
    recharge: Optional[float] = None,
    energy_after: float,
    noradrenaline: float,
    cortisol: float,
    commit: bool = True,
) -> None:
    if not config.ENABLE_ENERGY_TELEMETRY:
        return
    conn.execute(
        """
        INSERT INTO energy_telemetry
        (timestamp_utc, turn_id, drain, recharge, energy_after, noradrenaline, cortisol)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            utc_now_iso(), turn_id,
            round(drain, 4) if drain is not None else None,
            round(recharge, 4) if recharge is not None else None,
            round(energy_after, 4),
            round(noradrenaline, 4),
            round(cortisol, 4),
        ),
    )
    _maybe_commit(conn, commit)


def telemetry_summary(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT COUNT(*), AVG(drain), SUM(drain), SUM(recharge),
               MIN(energy_after), MAX(energy_after)
        FROM energy_telemetry
        """
    ).fetchone()
    count, avg_drain, total_drain, total_recharge, min_e, max_e = row
    return {
        "turns_recorded": int(count or 0),
        "avg_drain_per_turn": round(avg_drain, 4) if avg_drain is not None else None,
        "total_drain": round(total_drain, 4) if total_drain is not None else 0.0,
        "total_recharge": round(total_recharge, 4) if total_recharge is not None else 0.0,
        "min_energy_seen": min_e,
        "max_energy_seen": max_e,
    }


# ---------------------------------------------------------------------------
# Ringkasan hitungan (untuk cognitive_get_status — hitungan saja, tanpa isi)
# ---------------------------------------------------------------------------

def v040_counts(conn: sqlite3.Connection) -> dict:
    return {
        "pending_curiosity_questions": count_pending_questions(conn),
        "pending_reminder_intents": count_pending_reminders(conn),
        "stored_dreams": count_stored_dreams(conn),
        "photo_moments": count_photo_moments(conn),
    }


# ---------------------------------------------------------------------------
# v0.5.0 — Papan Supervisi Worker Bot (Task Blackboard)
# ---------------------------------------------------------------------------

_VALID_WORKER_STATUSES = {"pending", "running", "done", "failed"}


def upsert_worker_task(
    conn: sqlite3.Connection,
    *,
    worker_name: str,
    description: str = "",
    status: str = "pending",
    result_summary: str = "",
    task_id: Optional[str] = None,
    commit: bool = True,
) -> dict:
    """Buat atau perbarui status tugas worker bot di papan supervisi."""
    worker_name = (worker_name or "").strip()
    if not worker_name:
        return {"stored": False, "task_id": None, "reason": "empty_worker_name"}
    if status not in _VALID_WORKER_STATUSES:
        status = "pending"
    now_iso = utc_now_iso()

    if task_id:
        row = conn.execute(
            "SELECT task_id, description, status, result_summary FROM worker_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row:
            desc_val = (description or "").strip() or row[1]
            new_summary = (result_summary or "")[:400]
            # v0.6.0 (M11): reset penanda alert saat tugas berubah — status
            # berubah, kembali pending/running, atau ada result_summary baru —
            # supaya heartbeat melaporkannya lagi (bukan diam selamanya).
            if (
                status != row[2]
                or status in ("pending", "running")
                or (bool(new_summary) and new_summary != (row[3] or ""))
            ):
                conn.execute(
                    "UPDATE worker_tasks SET alerted_utc = '' WHERE task_id = ?",
                    (task_id,),
                )
            conn.execute(
                """
                UPDATE worker_tasks
                SET worker_name = ?, description = ?, status = ?, result_summary = ?, updated_utc = ?
                WHERE task_id = ?
                """,
                (worker_name[:80], desc_val[:300], status, new_summary, now_iso, task_id),
            )
            _maybe_commit(conn, commit)
            return {"stored": True, "task_id": task_id, "status": status, "action": "updated"}

    tid = task_id or f"wt_{uuid.uuid4().hex[:8]}"
    conn.execute(
        """
        INSERT INTO worker_tasks
        (task_id, worker_name, description, status, result_summary, created_utc, updated_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (tid, worker_name[:80], (description or "")[:300], status, (result_summary or "")[:400], now_iso, now_iso),
    )
    # Jaga jumlah baris tidak membengkak.
    # v0.5.1 (M12): prune HANYA tugas terminal (done/failed) terlama —
    # jangan pernah menghapus tugas pending/running yang masih aktif.
    max_tasks = int(getattr(config, "MAX_ACTIVE_WORKER_TASKS", 30))
    total = conn.execute("SELECT COUNT(*) FROM worker_tasks").fetchone()[0]
    if total > max_tasks:
        excess = total - max_tasks
        conn.execute(
            """
            DELETE FROM worker_tasks WHERE task_id IN (
                SELECT task_id FROM worker_tasks
                WHERE status IN ('done', 'failed')
                ORDER BY updated_utc ASC LIMIT ?
            )
            """,
            (excess,),
        )
    _maybe_commit(conn, commit)
    return {"stored": True, "task_id": tid, "status": status, "action": "created"}


def list_worker_tasks(
    conn: sqlite3.Connection,
    *,
    limit: int = 10,
    only_active: bool = False,
) -> List[dict]:
    if not getattr(config, "ENABLE_WORKER_BLACKBOARD", True):
        return []
    if only_active:
        rows = conn.execute(
            """
            SELECT task_id, worker_name, description, status, result_summary, created_utc, updated_utc
            FROM worker_tasks WHERE status IN ('pending', 'running', 'failed')
            ORDER BY updated_utc DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT task_id, worker_name, description, status, result_summary, created_utc, updated_utc
            FROM worker_tasks ORDER BY updated_utc DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "task_id": r[0],
            "worker_name": r[1],
            "description": r[2],
            "status": r[3],
            "result_summary": r[4],
            "created_utc": r[5],
            "updated_utc": r[6],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# v0.5.0 — Inside Jokes & Panggilan Khas
# ---------------------------------------------------------------------------

def add_inside_joke(
    conn: sqlite3.Connection,
    *,
    phrase: str,
    meaning: str = "",
    trigger_keywords: Optional[List[str]] = None,
    commit: bool = True,
) -> dict:
    phrase = (phrase or "").strip()
    if not phrase:
        return {"stored": False, "joke_id": None, "reason": "empty_phrase"}
    norm = _norm_text(phrase)
    existing = conn.execute("SELECT joke_id, phrase FROM inside_jokes").fetchall()
    for jid, ex_phrase in existing:
        if _norm_text(ex_phrase) == norm:
            return {"stored": False, "joke_id": jid, "reason": "duplicate"}

    max_jokes = int(getattr(config, "MAX_INSIDE_JOKES", 50))
    if len(existing) >= max_jokes:
        oldest = conn.execute(
            "SELECT joke_id FROM inside_jokes ORDER BY times_used ASC, created_utc ASC LIMIT 1"
        ).fetchone()
        if oldest:
            conn.execute("DELETE FROM inside_jokes WHERE joke_id = ?", (oldest[0],))

    jid = f"jk_{uuid.uuid4().hex[:8]}"
    kw_list = list(trigger_keywords or [])
    if not kw_list:
        kw_list = list(_tokens(phrase))[:5]
    conn.execute(
        """
        INSERT INTO inside_jokes (joke_id, phrase, meaning, trigger_keywords_json, times_used, created_utc)
        VALUES (?, ?, ?, ?, 0, ?)
        """,
        (jid, phrase[:200], (meaning or "").strip()[:300], _json_list(kw_list), utc_now_iso()),
    )
    _maybe_commit(conn, commit)
    return {"stored": True, "joke_id": jid, "reason": "stored"}


def match_inside_joke(
    conn: sqlite3.Connection,
    *,
    user_text: str,
    commit: bool = True,
) -> Optional[dict]:
    if not getattr(config, "ENABLE_RELATIONSHIP_EVOLUTION", True):
        return None
    rows = conn.execute(
        "SELECT joke_id, phrase, meaning, trigger_keywords_json, times_used FROM inside_jokes"
    ).fetchall()
    if not rows:
        return None
    lower = (user_text or "").lower()
    q_tokens = _tokens(lower)
    best = None
    best_score = 0
    for jid, phrase, meaning, kw_json, times_used in rows:
        kws = [k.lower() for k in _from_json_list(kw_json)]
        # v0.5.1 (M15): kata kunci pendek (< 5 huruf) wajib cocok sebagai
        # token utuh — "api" tidak boleh cocok di "tapi"/"rapi".
        hits = 0
        for k in kws:
            if not k:
                continue
            if len(k) >= 5:
                if k in lower or k in q_tokens:
                    hits += 1
            elif k in q_tokens:
                hits += 1
        if hits > best_score:
            best_score = hits
            best = {
                "joke_id": jid,
                "phrase": phrase,
                "meaning": meaning,
                "times_used": int(times_used) + 1,
            }
    if best:
        conn.execute(
            "UPDATE inside_jokes SET times_used = times_used + 1 WHERE joke_id = ?",
            (best["joke_id"],),
        )
        _maybe_commit(conn, commit)
    return best


# ---------------------------------------------------------------------------
# v0.5.0 — Idle Heartbeat Proaktif (dengan jam tenang lokal)
# ---------------------------------------------------------------------------

def _is_quiet_hour(local_hour: int) -> bool:
    start = int(getattr(config, "QUIET_HOURS_START", 23))
    end = int(getattr(config, "QUIET_HOURS_END", 7))
    if start > end:
        return local_hour >= start or local_hour < end
    return start <= local_hour < end


def mark_worker_task_alerted(
    conn: sqlite3.Connection,
    task_id: str,
    commit: bool = True,
) -> bool:
    """Tandai tugas worker sudah dilaporkan via heartbeat (v0.5.1 M11)."""
    cur = conn.execute(
        "UPDATE worker_tasks SET alerted_utc = ? WHERE task_id = ?",
        (utc_now_iso(), task_id),
    )
    _maybe_commit(conn, commit)
    return cur.rowcount > 0


def evaluate_idle_heartbeat(
    conn: sqlite3.Connection,
    *,
    elapsed_seconds: float,
    energy: float,
    is_resting: bool,
    local_hour: Optional[int] = None,
) -> dict:
    """Evaluasi apakah agen wajar menyapa duluan saat idle (tanpa spam).

    v0.5.1 (M11): alert worker done/failed hanya dilaporkan sekali — tugas
    yang dikembalikan ditandai alerted_utc agar tidak terulang di setiap
    get_status berikutnya.
    """
    if not getattr(config, "ENABLE_IDLE_HEARTBEAT", True):
        return {"should_initiate": False, "reason": "disabled"}

    if local_hour is None:
        tz_offset = int(getattr(config, "CIRCADIAN_TZ_OFFSET_HOURS", 7))
        local_hour = (datetime.now(timezone.utc) + timedelta(hours=tz_offset)).hour

    if _is_quiet_hour(local_hour):
        return {"should_initiate": False, "reason": "quiet_hours", "local_hour": local_hour}
    if is_resting or energy < 0.30:
        return {"should_initiate": False, "reason": "resting_or_low_energy", "local_hour": local_hour}

    now = _now()
    # 1. Prioritas tertinggi: pengingat jatuh tempo berbasis waktu
    rows = conn.execute(
        """
        SELECT intent_id, text, due_at, trigger_condition, last_surfaced_at
        FROM reminder_intents WHERE status IN ('pending', 'surfaced')
        ORDER BY priority DESC, due_at ASC LIMIT 5
        """
    ).fetchall()
    for iid, text, due_at, trigger, last_surfaced in rows:
        last = _parse_iso(last_surfaced)
        if last and (now - last) < timedelta(minutes=config.REMINDER_COOLDOWN_MINUTES):
            continue
        if _trigger_due(trigger, due_at, "", now):
            # v0.6.0 (M11): langsung tandai surfaced + commit supaya
            # cooldown REMINDER_COOLDOWN_MINUTES aktif dan alert yang sama
            # tidak muncul terus-terusan di setiap cek status.
            conn.execute(
                "UPDATE reminder_intents SET status = 'surfaced', last_surfaced_at = ? WHERE intent_id = ?",
                (now.isoformat(), iid),
            )
            _maybe_commit(conn, True)
            return {
                "should_initiate": True,
                "reason": "due_reminder",
                "local_hour": local_hour,
                "suggested_payload": {"intent_id": iid, "text": text, "due_at": due_at},
            }

    # 2. Worker bot ada yang selesai atau gagal -> lapor ke user
    # v0.5.1 (M11): hanya tugas yang belum pernah dilaporkan
    # (alerted_utc kosong); setelah dilaporkan, tandai agar tidak terulang.
    worker_alert = conn.execute(
        """
        SELECT task_id, worker_name, description, status, result_summary
        FROM worker_tasks WHERE status IN ('done', 'failed')
        AND (alerted_utc IS NULL OR alerted_utc = '')
        ORDER BY updated_utc DESC LIMIT 1
        """
    ).fetchone()
    if worker_alert and elapsed_seconds >= 300:
        mark_worker_task_alerted(conn, worker_alert[0], commit=True)
        return {
            "should_initiate": True,
            "reason": f"worker_task_{worker_alert[3]}",
            "local_hour": local_hour,
            "suggested_payload": {
                "task_id": worker_alert[0],
                "worker_name": worker_alert[1],
                "description": worker_alert[2],
                "status": worker_alert[3],
                "result_summary": worker_alert[4],
            },
        }

    # 3. Idle cukup lama -> tawarkan mimpi baru atau pertanyaan curiosity
    min_idle_sec = float(getattr(config, "IDLE_HEARTBEAT_MIN_MINUTES", 45)) * 60.0
    if elapsed_seconds < min_idle_sec:
        return {"should_initiate": False, "reason": "idle_too_short", "local_hour": local_hour}

    dream = conn.execute(
        "SELECT dream_id, theme, COALESCE(dream_story, ''), idea_text FROM dream_records WHERE status = 'stored' ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    if dream:
        # v0.6.0 (M11): langsung tandai surfaced + commit supaya mimpi
        # yang sama tidak muncul berulang kali di setiap cek status.
        conn.execute(
            "UPDATE dream_records SET status = 'surfaced' WHERE dream_id = ?", (dream[0],)
        )
        _maybe_commit(conn, True)
        return {
            "should_initiate": True,
            "reason": "share_dream",
            "local_hour": local_hour,
            "suggested_payload": {
                "dream_id": dream[0],
                "theme": dream[1],
                "dream_story": dream[2],
                "idea_text": dream[3],
            },
        }

    curiosity = conn.execute(
        "SELECT question_id, text, topic FROM curiosity_questions WHERE status = 'pending' ORDER BY priority DESC, created_at ASC LIMIT 1"
    ).fetchone()
    if curiosity:
        # v0.6.0 (M11): hormati cooldown CURIOSITY_COOLDOWN_MINUTES dari
        # last_curiosity_offered_at, lalu tandai pertanyaan ini sudah
        # ditawarkan supaya tidak muncul terus-terusan.
        last_offered = _parse_iso(get_meta(conn, "last_curiosity_offered_at"))
        if last_offered and (now - last_offered) < timedelta(minutes=config.CURIOSITY_COOLDOWN_MINUTES):
            return {"should_initiate": False, "reason": "nothing_pending", "local_hour": local_hour}
        conn.execute(
            "UPDATE curiosity_questions SET last_offered_at = ? WHERE question_id = ?",
            (now.isoformat(), curiosity[0]),
        )
        set_meta(conn, "last_curiosity_offered_at", now.isoformat(), commit=False)
        _maybe_commit(conn, True)
        return {
            "should_initiate": True,
            "reason": "curiosity_checkin",
            "local_hour": local_hour,
            "suggested_payload": {
                "question_id": curiosity[0],
                "text": curiosity[1],
                "topic": curiosity[2],
            },
        }

    return {"should_initiate": False, "reason": "nothing_pending", "local_hour": local_hour}
