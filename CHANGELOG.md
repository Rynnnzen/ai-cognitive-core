# Changelog — ai_cognitive_core

## [0.6.1] - 2026-11-28

Release **v0.6.1** — lightweight web dashboard (Obsidian replacement) + Drive photo/media backup selection rules. Keeps the 3-pillar architecture (`memory`, `heart`, `conscious`), the 5-tool MCP contract, and full compatibility with the existing `heart_state.json` and database (no migration).

### Lightweight Web Dashboard (`src/ai_cognitive_core/dashboard/`)
- **Safe helpers (`dashboard/helpers.py`):** read-only access to `heart_state.json` and `cognitive_memory.db` (SQLite opened with `mode=ro`, never written), plus scoped read/write to the Markdown memory folder with strict path validation (rejects absolute paths, `..`, and paths outside the allowed memory directories). Paths are configured through environment variables (`COGNITIVE_STATE_DIR`, `COGNITIVE_WORKSPACE_DIR`) with safe defaults — no hardcoded local paths.
- **Last Drive sync info:** read from `sync_meta.json` together with how long ago it was (`ago_seconds` + `ago_human` in Indonesian).
- **FastAPI endpoints (`dashboard/app.py`):** `GET /` (serves the static UI), `GET /api/status` (cognitive condition + PAD expansion + Drive sync), `GET /api/graph` (episodes & entities), `GET /api/memories` (Markdown file list), `GET /api/memory?path=...` (read one file), `PUT /api/memory` (write one file, strict path validation). The dashboard is local-only (binds `127.0.0.1`, no auth) — do not expose it publicly.
- **Colorful Crayon UI + PWA (`dashboard/static/`):** responsive mobile-first interface, warm cream paper background (`#FFFDF7` / `#FAF3E3`), colorful crayon accents, `manifest.json` for Add to Home Screen. Cognitive status bar (PAD expansion, 5 neurochemical bars, energy, circadian phase, heartbeat, last Drive sync badge), Interactive Memory Graph (`vis-network`, node color by emotion, node size by memory weight, detail panel on click), plus a Markdown Memory Reader & Editor.
- **New dependencies:** `fastapi`, `uvicorn` (added to `pyproject.toml`).
- **Tests:** new suite `tests/test_v061_dashboard.py`.

### Drive Photo/Media Backup Selection Rules (`config.py`, `drive_bridge.py`, `backup_photos_to_mcp_drive.py`)
- Daily/general photos are **not** auto-backed-up to Drive (`photos/`). Only: (a) character sheets & main visual-style reference assets (`ref_keep/`) when the model or art style changes; (b) truly memorable photos in dedicated subfolders `memorable/` or `favorites/`; (c) avatar candidates (`avatars/`). The rules live in `config.py` (`DRIVE_PHOTOS_*`) and are enforced by the backup script.
- **Tidy up `workspace_md/` (`drive_bridge.py`):** goal files under `workspace/goals/` now map to `goals/` (the `workspace/` prefix is dropped) so Drive no longer has a `workspace/` subfolder duplicating `goals/`; the old duplicate folder in Drive has been deleted (its contents are stored locally and will re-sync once to the new location).

## [0.6.0] - 2026-11-25

Release **v0.6.0** — anti-repeat heartbeat alerts (M11) + 4 PAD expansions. Keeps the 3-pillar architecture (`memory`, `heart`, `conscious`), the 5-tool MCP contract, and full compatibility with the old `heart_state.json` (all new fields have safe defaults, no migration).

### Anti-Repeat Heartbeat Alert (M11) (`memory/v040_store.py`)
- `evaluate_idle_heartbeat` now marks `due_reminder` and `share_dream` as `surfaced` + commits as soon as they fire, so the `REMINDER_COOLDOWN_MINUTES` cooldown kicks in and the same alert no longer repeats on every status check.
- `curiosity_checkin` now honours the `CURIOSITY_COOLDOWN_MINUTES` cooldown from `last_curiosity_offered_at` and marks the offered question (`last_offered_at` + meta).
- `upsert_worker_task` resets `alerted_utc` when the status changes, returns to `pending`/`running`, or a new `result_summary` arrives — so a changed task is reported again.

### 4 PAD Expansions (`config.py`, `schemas.py`, `heart/layers/l1_neurochemical.py`, `heart/layers/l3_mood_space.py`, `heart/engine.py`, `mcp_server.py`)
1. **Mood intensity (`l3_mood_space.py`, `engine.py`):** `compute_pad_intensity` — Euclidean PAD magnitude + `mild` / `moderate` / `intense` label (thresholds `0.35` / `0.75`); feeds `EmotionalDirective.pad_magnitude` / `mood_intensity` and `tone_instruction`.
2. **Mood trajectory (`l3_mood_space.py`, `engine.py`):** `compute_pad_trajectory` — `dp`/`da`/`dd` deltas + direction `steady` / `softening` / `warming_up` / `escalating` / `calming_down` / `cooling_down` (deadband `0.06`); `step()` stores `prev_pad` and `last_pad_delta`; `tone_instruction` includes `Trajectory=...` when not `steady`.
3. **Hedonic elasticity (`l3_mood_space.py`, `engine.py`):** `apply_hedonic_elasticity` — when `P > 0.75` for 3 turns in a row, `P` is pulled toward the baseline by `0.08` (never below the baseline); `high_pleasure_streak` is stored in state.
4. **Emotional nuance (`l3_mood_space.py`, `engine.py`):** `classify_emotional_nuance` — 22 fine sub-emotions (`Drowsy` first when energy `< 0.32` or `late_night` + `A < -0.15`; then per-octant derivatives); feeds `EmotionalDirective.emotional_nuance` and `tone_instruction` as `Nuance=...`.
- **Neuro saturation damping (`l1_neurochemical.py`):** `_damp_high_positive` damps `oxytocin` / `dopamine` / `serotonin` increases by `0.35x` once the value is `>= 0.88` (decreases are not damped).
- **MCP output (`mcp_server.py`):** `cognitive_commit_turn` also returns `mood_intensity`, `emotional_nuance`, `pad_trajectory`; `cognitive_get_status` adds the `v060` block (`core_version`, `pad_expansion`).
- **Master switch:** `ENABLE_PAD_EXPANSION = True` in `config.py` turns the whole expansion on/off at once.
- **Tests:** new `tests/test_v060.py` (19 tests — 8 anti-repeat heartbeat, 5 PAD functions + damping, 4 old-state compatibility, 2 `v060`/commit fields); full suite 77/77 passing.

## [0.5.1] - 2026-11-23

Audit-fix release **v0.5.1** — in-place fixes for all 5 Important findings (P1–P5) and 15 Minor findings (M1–M6, M8, M10–M17; M7 and M9 intentionally deferred) of the full v0.5.0 audit (2026-11-23), keeping the 3-pillar architecture (`memory`, `heart`, `conscious`), the 5-tool MCP contract, and full compatibility with the `v0.4.0` SQLite database. No schema version bump: the one new column is additive and idempotent.

### Important fixes (P1–P5)
- **Visible Drive init errors (P1) (`drive_bridge.py`, `mcp_server.py`):** `_init_drive_service` no longer swallows refresh/init errors with `except Exception: pass` — it logs them to `stderr` (never printing token/secret contents) and records `last_init_error`. `cognitive_get_status` exposes `drive_status` in the `v050` block (`connected`, `last_sync_utc`, `last_init_error`, plus a warning when offline or unsynced for over 6 hours).
- **Honest sync stamp (P2) (`drive_bridge.py`):** `push_state` writes `last_sync_utc` to `sync_meta.json` only AFTER the heart/DB upload actually succeeds; offline or failed pushes leave it untouched and record `last_attempt_utc` instead.
- **Atomic heart-state writes & no silent reset (P3) (`heart/engine.py`):** `save()` writes to a temp file and swaps it in with `os.replace()`, keeping a last-good `heart_state.json.bak`. `_load()` logs corrupt state, quarantines it as `heart_state.json.corrupt.<timestamp>`, and recovers from `.bak` before falling back to a fresh state.
- **Content-based commit dedup (P4) (`memory/manager.py`):** when `turn_id` is empty (production callers never send one), `commit_turn_bundle` rejects an episode whose exact summary already exists within the last 120 seconds, returning the existing episode id instead of writing a duplicate row.
- **Safe persona defaults (P5) (`mcp_server.py`):** all `cognitive_configure_persona` parameters now default to `None` (keep the current value); only explicitly provided fields change. Invalid `attachment_style` returns a clean JSON error instead of raising `ValueError`.

### Minor fixes (M1–M17)
- **Ebbinghaus pruning revived (M1/M2) (`manager.py`, `consolidation.py`):** importance floor lowered from `0.45` to `0.20` (`0.20 + 0.45|P| + 0.35|A|`), so light chats can fall below the `0.35` decay/dream thresholds; `energy_telemetry` is pruned to the newest 2000 rows per sleep cycle.
- **Single tech-domain penalty & scan limit (M3/M4) (`l3_episodic_graph.py`):** `domain_mult` now applies once (final score), so the effective penalty is truly `0.65x`; the SQL scan uses `config.EPISODE_SCAN_LIMIT` instead of a hardcoded `250`.
- **Slower trust evolution (M5) (`config.py`, `heart/engine.py`):** `TRUST_POS_DELTA = 0.004`, `TRUST_NEG_DELTA = -0.012`, and the stage thresholds moved to `config.py`.
- **05:00 is morning (M6) (`config.py`, `l1_neurochemical.py`, `README.md`):** `CIRCADIAN_MORNING_START = 5` and `CIRCADIAN_DAYTIME_END = 18` in config; no hour falls through to the wrong phase.
- **Working-memory dedup & truncation marker (M8) (`l2_working_paging.py`):** `promote()` dedups on `(role, content)` as well as `chunk_id`; over-long chunks are stored as `content[:499] + "…"`.
- **Per-row recall resilience (M10) (`l3_episodic_graph.py`, `conscious/cycle.py`):** corrupt episode rows are skipped instead of failing the whole recall; optional perceive features (curiosity, reminder, dream, photo, inside joke, habits, worker blackboard) are each guarded so one failure cannot kill a turn.
- **Fire-once heartbeat alerts & active-task protection (M11/M12) (`v040_store.py`, `migration.py`, `manager.py`):** additive `alerted_utc` column on `worker_tasks`; `evaluate_idle_heartbeat` reports each done/failed task once (`mark_worker_task_alerted` helper); pruning only ever deletes the oldest `done`/`failed` tasks, never `pending`/`running`.
- **Gradual inertia recovery (M13) (`l5_metacognition.py`, `cycle.py`):** after a negative streak ends, inertia recovers `+0.02` per turn toward `0.35` instead of staying locked at `0.20`.
- **Version & matching cleanups (M14–M17):** `mcp_server.py` imports `__version__` (no more hardcoded `"0.5.0"`); short inside-joke keywords (< 5 chars) must match as whole tokens; the fallback MCP server returns a JSON-RPC error instead of hanging the client; stale comments/docstrings refreshed in `config.py`, `migration.py`, `dreams.py`, `l4_appraisal.py`.
- **Tests:** new `tests/test_v051.py` (23 tests) covering P1–P5, M1, M4–M6, M8, M10–M13, M15, and the version bump. Full suite: 58/58 passing.

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
