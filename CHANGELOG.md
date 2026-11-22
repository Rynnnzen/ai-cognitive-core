# Changelog — ai_cognitive_core

## [0.5.0] - 2026-11-22

Full expansion release **v0.5.0** — keeping the 3-pillar architecture (`memory`, `heart`, `conscious`), the 5-tool MCP contract, and full compatibility with the `v0.4.0` SQLite database.

### 5 New Expansions (`v0.5.0`)
- **Persistent Working Memory (`l2_working_paging.py`, `manager.py`, `migration.py`):** Adds the additive `working_memory_chunks` table in SQLite (`WORKING_MEMORY_PERSIST_CAPACITY = 6`). Short-term context is now loaded automatically at startup and saved on every incoming message, so the conversation flow stays smooth across one-shot MCP calls.
- **Circadian Rhythm (`l1_neurochemical.py`, `heart/engine.py`, `conscious/cycle.py`, `config.py`):** Adds local biological-clock awareness (default WIB / `UTC+7`, phases `morning`, `daytime`, `evening`, `late_night`). When staying up late (`23:00–04:59`), energy drain rises `1.30x` and arousal dips slightly so sleepiness feels natural; in the morning (`06:00–10:59`), sleep recovery is fresher (`1.15x`).
- **Real Proactivity / Idle Heartbeat (`v040_store.py`, `manager.py`, `mcp_server.py`, `config.py`):** Adds `proactive_heartbeat` evaluation in `cognitive_get_status`, with quiet hours (`23:00–06:59`) to avoid spam. Prioritizes due reminders → worker-bot done/failed status → new dream stories / curiosity questions after idle `>= 45` minutes.
- **Worker Bot Supervision Board (`v040_store.py`, `manager.py`, `heart/engine.py`, `cycle.py`, `mcp_server.py`):** Adds the additive `worker_tasks` table to record delegations to worker bots (`pending`, `running`, `done`, `failed`) via the optional `worker_task` parameter on `cognitive_commit_turn`. Active worker status appears in `worker_blackboard` on `perceive_and_think` & `get_status`, and `done`/`failed` outcomes give a subtle emotional reaction to the heart (`apply_worker_outcome`).
- **Relationship Evolution & Inside Jokes (`schemas.py`, `heart/engine.py`, `v040_store.py`, `cycle.py`, `mcp_server.py`):** Adds `trust_score` (`0.0–1.0`) and `relationship_stage` (`guarded` / `warm` / `close` / `deep_bond`) that evolve slowly based on interaction quality. Adds the additive `inside_jokes` table (`add_inside_joke` on commit, automatic `inside_joke_cue` when relevant on `perceive_and_think`).

### Includes All `v0.4.1` Improvements & Mood Calibration
- **Dynamic Mood Calibration:** Stops the automatic positive pull in `commit_turn`, allows negative arousal in calm chat, connects L1/L2 to L3 PAD, and shifts the default baseline to `Relaxed` `(0.05, -0.05, 0.15)`.
- **Guardrail Relaxation:** Curiosity cooldown `5` minutes, anti-skip dreams (`DREAM_TECHNICAL_WORD_THRESHOLD = 3`, 40 episode candidates), `HABIT_TOP_K = 3`, `HABIT_MIN_SCORE = -1`, `RECALL_TECH_DOMAIN_PENALTY = 0.65`, and `LUBB_STRICT_MODE = False`.
- **Small Updates & Reliability:** Story-first-then-idea dreams (`dream_story`), L5 adaptation system (`amirhouieh/adapt`), rich photo memory metadata (`feeling`, `when_label`), on-topic recall, varied emoji, plus Drive-backup false-positive fixes & efficiency in sleep cycle + critical-energy limit (`<= 0.10`).

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
