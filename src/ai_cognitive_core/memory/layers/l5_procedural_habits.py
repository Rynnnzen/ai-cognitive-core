import sqlite3
from typing import List
from ai_cognitive_core.schemas import ProceduralHabit


def match_habits(conn: sqlite3.Connection, user_input: str) -> List[ProceduralHabit]:
    cur = conn.cursor()
    cur.execute("SELECT habit_id, trigger_pattern, action_template, success_count FROM procedural_habits")
    lower = user_input.lower()
    matched = []
    for r in cur.fetchall():
        if r[1].lower() in lower:
            matched.append(
                ProceduralHabit(
                    habit_id=r[0],
                    trigger_pattern=r[1],
                    action_template=r[2],
                    success_count=r[3],
                )
            )
    return matched
