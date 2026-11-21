# Changelog — ai_cognitive_core

## [0.4.1] - 2026-11-21

Update in-place tanpa mengubah arsitektur 3 pilar (`memory`, `heart`, `conscious`) dan 100% kompatibel dengan skema SQLite `v0.4.0`.

### Fitur & Peningkatan (Update Kecil)
- **Mimpi: Cerita Dulu, Baru Ide (`memory/dreams.py`, `v040_store.py`, `schemas.py`, `migration.py`):** Menambahkan kolom additive `dream_story` pada `dream_records` serta template narasi mimpi singkat per kategori (`date_idea`, `photo_idea`, `other`) yang dirangkai sebelum menurunkan `idea_text`.
- **Mimpi Anti-Skip (`config.py`, `consolidation.py`, `dreams.py`):** Menurunkan `DREAM_MIN_EPISODE_IMPORTANCE` (`0.45` -> `0.35`), memperluas kandidat sleep cycle dari 20 ke 40 episode (`DREAM_CANDIDATE_LIMIT`), dan melonggarkan filter `_is_technical_summary` agar hanya men-skip episode yang benar-benar dominan teknis (`>= 2` kata teknis atau kata teknis ketat tanpa konsep personal).
- **Sistem Adaptasi Terinspirasi `amirhouieh/adapt` (`l5_procedural_habits.py`, `manager.py`, `cycle.py`, `mcp_server.py`):** Mengaktifkan *attention-weighted procedural memory* di atas tabel `procedural_habits` (`match_habits`, `learn_habit`, `reinforce_habit`). Mendukung parameter opsional `learn_habit` dan `habit_feedback` (`+1`/`-1`) di `cognitive_commit_turn` dan memunculkan `learned_habits` (maks 2) saat `perceive_and_think`.
- **Ingatan Foto Lebih Hidup (`v040_store.py`, `manager.py`, `schemas.py`, `migration.py`):** Menambahkan kolom additive `feeling` dan `when_label` pada `photo_moments` untuk menyimpan konteks momen lengkap (siapa, kapan, perasaan/suasana) di luar caption saja, tetap menghormati `consent_status == "granted"`.
- **Recall Episodik Lebih Nyambung (`l3_episodic_graph.py`, `manager.py`):** Menambahkan bobot *keyword/entity overlap*, bonus *recency* halus, dan penalti domain teknis (`0.45x`) saat obrolan bersifat personal agar tidak lagi menarik episode teknis yang tidak nyambung. Juga memulihkan `_last_node_id` dari SQLite saat inisialisasi agar rantai `next_node_id` tetap tersambung lintas proses *one-shot* MCP.
- **Rasa Penasaran Lebih Sering Muncul (`config.py`):** Menurunkan `CURIOSITY_COOLDOWN_MINUTES` (`30` -> `10` menit) dan `CURIOSITY_MIN_TURNS_BETWEEN` (`3` -> `1` turn).
- **Emoji Variatif Sesuai Konteks (`heart/phrase_bank.py`, `heart/engine.py`, `schemas.py`):** Menambahkan `EMOJI_PALETTES` dan `SLEEPY_EMOJI_PALETTES` dengan rotasi deterministik berbasis `total_turns` per *mood octant* dan *bubble style* (tetap kosong untuk `dry_short_1_bubble`), diekspos lewat `emoji_palette` dan `EmojiHint` di `tone_instruction`.

### Perbaikan Bug & Reliabilitas
- **Anti *False-Positive* Backup Drive (`drive_bridge.py`):** Memperbaiki `push_state()` agar mengembalikan `False` dan menulis pesan error ke `stderr` jika upload gagal, serta menghormati flag `ENABLE_DRIVE_SYNC`.
- **Backup DB Efisien di Sleep Cycle + Pengaman Energi Kritis (`config.py`, `mcp_server.py`):** Menambahkan `DRIVE_PUSH_DB_ON_COMMIT = False` dan `DRIVE_CRITICAL_ENERGY_THRESHOLD = 0.10`. `cognitive_commit_turn` hanya mendorong `heart_state.json` (cepat), sedangkan `cognitive_memory.db` penuh otomatis di-backup saat `cognitive_sleep_cycle` atau saat energi <= `0.10`.
- **Sinkronisasi Persona Aman di One-Shot MCP (`mcp_server.py`):** Mengubah `async_mode=True` -> `False` pada `cognitive_configure_persona`.
- **Idempotensi `total_turns` & Kebersihan Paket (`conscious/cycle.py`, `manager.py`, `.gitignore`):** Menjaga `total_turns` agar tidak naik ganda saat `perceive_retry == True`, membungkus koneksi SQLite dengan `try...finally`, dan menyertakan `.gitignore`.
