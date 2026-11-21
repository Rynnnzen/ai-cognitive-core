# Changelog — ai_cognitive_core

## [0.4.1] - 2026-11-21

In-place update with no changes to the 3-pillar architecture (`memory`, `heart`, `conscious`) and 100% compatible with the `v0.4.0` SQLite schema.

### Features & Improvements (Small Update)
- **Dreams: Story First, Then Idea (`memory/dreams.py`, `v040_store.py`, `schemas.py`, `migration.py`):** Adds the additive `dream_story` column to `dream_records`, plus short dream-narrative templates per category (`date_idea`, `photo_idea`, `other`) composed before deriving `idea_text`.
- **Anti-Skip Dreams (`config.py`, `consolidation.py`, `dreams.py`):** Lowers `DREAM_MIN_EPISODE_IMPORTANCE` (`0.45` -> `0.35`), widens sleep-cycle candidates from 20 to 40 episodes (`DREAM_CANDIDATE_LIMIT`), and relaxes `_is_technical_summary` so it only skips episodes that are genuinely technical (`>= 2` technical words, or strict technical words with no personal concept).
- **Adaptation System, inspired by `amirhouieh/adapt` (`l5_procedural_habits.py`, `manager.py`, `cycle.py`, `mcp_server.py`):** Enables attention-weighted procedural memory on top of the `procedural_habits` table (`match_habits`, `learn_habit`, `reinforce_habit`). Supports the optional `learn_habit` and `habit_feedback` (`+1`/`-1`) parameters in `cognitive_commit_turn` and surfaces `learned_habits` (max 2) in `perceive_and_think`.
- **Richer Photo Memory (`v040_store.py`, `manager.py`, `schemas.py`, `migration.py`):** Adds the additive `feeling` and `when_label` columns to `photo_moments` to store full moment context (who, when, feeling/atmosphere) beyond the caption, while still respecting `consent_status == "granted"`.
- **More Relevant Episodic Recall (`l3_episodic_graph.py`, `manager.py`):** Adds keyword/entity-overlap weighting, a soft recency bonus, and a technical-domain penalty (`0.45x`) during personal chat so off-topic technical episodes are no longer pulled in. Also restores `_last_node_id` from SQLite at initialization so the `next_node_id` chain stays connected across one-shot MCP processes.
- **Curiosity, More Often (`config.py`):** Lowers `CURIOSITY_COOLDOWN_MINUTES` (`30` -> `10` minutes) and `CURIOSITY_MIN_TURNS_BETWEEN` (`3` -> `1` turn).
- **Contextual Emoji Variety (`heart/phrase_bank.py`, `heart/engine.py`, `schemas.py`):** Adds `EMOJI_PALETTES` and `SLEEPY_EMOJI_PALETTES` with deterministic rotation based on `total_turns` per mood octant and bubble style (still empty for `dry_short_1_bubble`), exposed via `emoji_palette` and `EmojiHint` in `tone_instruction`.

### Bug Fixes & Reliability
- **No More False-Positive Drive Backups (`drive_bridge.py`):** Fixes `push_state()` to return `False` and write an error to `stderr` when an upload fails, and to honor the `ENABLE_DRIVE_SYNC` flag.
- **Efficient DB Backup in Sleep Cycle + Critical-Energy Guard (`config.py`, `mcp_server.py`):** Adds `DRIVE_PUSH_DB_ON_COMMIT = False` and `DRIVE_CRITICAL_ENERGY_THRESHOLD = 0.10`. `cognitive_commit_turn` only pushes `heart_state.json` (fast), while the full `cognitive_memory.db` is automatically backed up during `cognitive_sleep_cycle` or when energy <= `0.10`.
- **Safe Persona Sync in One-Shot MCP (`mcp_server.py`):** Changes `async_mode=True` -> `False` in `cognitive_configure_persona`.
- **`total_turns` Idempotency & Package Hygiene (`conscious/cycle.py`, `manager.py`, `.gitignore`):** Keeps `total_turns` from incrementing twice when `perceive_retry == True`, wraps SQLite connections in `try...finally`, and adds `.gitignore`.
