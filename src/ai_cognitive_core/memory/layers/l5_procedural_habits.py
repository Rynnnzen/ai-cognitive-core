"""
L5 Procedural Habits v0.4.1/v0.5.0 — Sistem Adaptasi (terinspirasi amirhouieh/adapt,
Voyager Skill Library, dan Reflexion).
"""

import sqlite3
import uuid
from typing import List, Optional
from ai_cognitive_core import config
from ai_cognitive_core.schemas import ProceduralHabit

_STOPWORDS = {
    "yang", "dan", "di", "ke", "dari", "aku", "kamu", "saya", "ini", "itu",
    "ada", "sudah", "lagi", "sih", "dong", "ya", "aja", "kok", "kan", "deh",
}


def _tokenize(text: str) -> set:
    tokens = set()
    for raw in text.lower().replace(",", " ").replace(".", " ").replace("?", " ").replace("!", " ").split():
        w = raw.strip("'\"()[]{}:;")
        if len(w) >= 3 and w not in _STOPWORDS:
            tokens.add(w)
    return tokens


def match_habits(
    conn: sqlite3.Connection,
    user_input: str,
    top_k: int = 3,
) -> List[ProceduralHabit]:
    min_score = int(getattr(config, "HABIT_MIN_SCORE", -1))
    cur = conn.cursor()
    cur.execute(
        "SELECT habit_id, trigger_pattern, action_template, success_count "
        "FROM procedural_habits WHERE success_count >= ?",
        (min_score,),
    )
    lower = (user_input or "").lower()
    input_tokens = _tokenize(lower)

    scored = []
    for hid, trigger, action, count in cur.fetchall():
        trig_lower = (trigger or "").strip().lower()
        if not trig_lower:
            continue

        score = 0.0
        if trig_lower in lower:
            score = 1.0
        else:
            trig_tokens = _tokenize(trig_lower)
            if trig_tokens and input_tokens:
                common = trig_tokens & input_tokens
                if common:
                    overlap = len(common) / len(trig_tokens)
                    if overlap >= 0.30 or len(common) >= 2:
                        score = 0.55 + 0.35 * overlap

        if score > 0.0:
            attention_boost = min(0.35, max(0, int(count)) * 0.05)
            scored.append((
                score + attention_boost,
                ProceduralHabit(
                    habit_id=hid,
                    trigger_pattern=trigger,
                    action_template=action,
                    success_count=int(count),
                ),
            ))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in scored[:top_k]]


def learn_habit(
    conn: sqlite3.Connection,
    trigger_pattern: str,
    action_template: str,
    commit: bool = True,
) -> dict:
    trigger = (trigger_pattern or "").strip()
    action = (action_template or "").strip()
    if not trigger or not action:
        return {"stored": False, "habit_id": None, "reason": "empty_trigger_or_action"}

    cur = conn.cursor()
    row = cur.execute(
        "SELECT habit_id, success_count FROM procedural_habits WHERE lower(trigger_pattern) = lower(?)",
        (trigger,),
    ).fetchone()

    if row:
        hid, count = row
        cur.execute(
            "UPDATE procedural_habits SET action_template = ?, success_count = ? WHERE habit_id = ?",
            (action[:400], max(1, int(count)), hid),
        )
        status = "updated"
    else:
        hid = f"hab_{uuid.uuid4().hex[:8]}"
        cur.execute(
            "INSERT INTO procedural_habits (habit_id, trigger_pattern, action_template, success_count) "
            "VALUES (?, ?, ?, ?)",
            (hid, trigger[:160], action[:400], 1),
        )
        status = "created"

    if commit:
        conn.commit()
    return {"stored": True, "habit_id": hid, "status": status}


def reinforce_habit(
    conn: sqlite3.Connection,
    habit_id: str,
    delta: int = 1,
    commit: bool = True,
) -> Optional[dict]:
    if not habit_id:
        return None
    cur = conn.cursor()
    row = cur.execute(
        "SELECT success_count FROM procedural_habits WHERE habit_id = ?",
        (habit_id,),
    ).fetchone()
    if not row:
        return {"updated": False, "reason": "not_found"}

    new_count = int(row[0]) + int(delta)
    cur.execute(
        "UPDATE procedural_habits SET success_count = ? WHERE habit_id = ?",
        (new_count, habit_id),
    )
    if commit:
        conn.commit()
    return {"updated": True, "habit_id": habit_id, "success_count": new_count}
