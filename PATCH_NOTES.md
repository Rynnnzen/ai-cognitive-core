# AI Cognitive Core MCP v0.4.0 — Patch Notes (Fase Tes)

> **Status: FASE TES (branch `v0.4.0-test`).** Ter-install di lokasi live
> 17 Nov 2026 ~22:50 WIB — migrasi DB live OK (backup `.bak-v0.3.1` dibuat),
> 29/29 tes lolos, smoke test live OK (perceive/commit/get_status/sleep).
> Perbaikan tema mimpi menyusul di commit 6ad71b5: tema menolak artefak
> teknis/nama file, episode teknis dilewati sebagai sumber mimpi, kandidat
> mimpi diperluas ke 20 episode teratas.
> Rencana implementasi dari Sol (gpt-6.1-sol) — lihat file rencana v0.4.0 &
> laporan ekspansi di workspace agent. Semua parameter baru terpusat di
> `src/ai_cognitive_core/config.py` agar mudah di-tune selama tes.
> Nilai energi & batas-batas di bawah adalah **nilai fase tes**, bukan final.

## Yang Baru di v0.4.0

### 1. Curiosity — agent menyimpan pertanyaan untuk user
- Tabel baru `curiosity_questions` (`question_id`, `text`, `topic`, `created_at`,
  `priority`, `status` pending/asked/dismissed, `last_offered_at`,
  `context_tags`, `expires_at`, `source`).
- Supervisor (agen LLM) mengusulkan pertanyaan lewat parameter opsional
  `propose_question` di `cognitive_commit_turn`; modul memvalidasi,
  mendedup (teks sama / topik sama + kemiripan >= 0.6), dan membatasi
  pending (maks 20, default TTL 14 hari). Modul sendiri tidak mengarang
  pertanyaan — generasi teks pertanyaan adalah tugas supervisor.
- `cognitive_perceive_and_think` mengembalikan **maksimal 1** `curiosity_prompt`,
  dipilih dari maks 5 kandidat (prioritas + relevansi topik). Ditunda saat:
  mood negatif, gaya bubble exhausted/dry, gaya texting dry/cold/shouting,
  konteks sensitif (kata kunci distres), atau turn berfokus tugas.
  Cooldown 30 menit + jeda minimal 3 turn antar penawaran.
- `cognitive_commit_turn` menandai pertanyaan sebagai asked lewat
  `curiosity_asked_id`, atau dismissed lewat `dismiss_curiosity_id`.
- `cognitive_get_status` menampilkan hitungan pending saja (tanpa isi).

### 2. Niat mandiri — agent membuat pengingatnya sendiri
- Tabel baru `reminder_intents` (`intent_id`, `text`, `created_at`,
  `due_at`/`trigger_condition`, `source`, `priority`, `status`
  pending/surfaced/completed/dismissed, `last_surfaced_at`, `repeat_policy`).
- Pemicu: `due_at` (ISO) atau `trigger_condition` (`time:<iso>` /
  `keyword:<kata>`). **Berbasis jadwal/perkiraan saja** — modul tidak
  mengamati aplikasi eksternal dan tidak pernah mengklaim "terdeteksi
  langsung" (setiap pengingat membawa `basis: "schedule"` + catatan itu).
- Perceive mengembalikan **maksimal 1** `proactive_intent` yang jatuh tempo
  (cooldown 60 menit per niat). Commit menyelesaikan/menunda/menolak lewat
  `reminder_id` + `reminder_action` (complete/snooze/dismiss) + `snooze_until`.
- Sleep cycle menyapu niat kedaluwarsa: tanpa repeat → dismissed 24 jam
  setelah `due_at`; repeat `daily` → due_at digeser +24 jam sampai ke depan.

### 3. Mimpi pas tidur — sleep cycle merangkai ide kencan/foto
- Tabel baru `dream_records` (`dream_id`, `created_at`, `source_episode_ids`,
  `theme`, `idea_text`, `category` date_idea/photo_idea/other, `novelty_score`,
  `status` stored/surfaced/dismissed, `sensitivity_tags`).
- Sleep cycle merangkai **maksimal 3** ide dari episode berkepentingan tinggi
  (>= 0.45) memakai template yang ditinjau; episode sensitif dilewati;
  duplikat (tema + set episode sumber sama) tidak ditulis ulang.
- Ide ditandai **generatif** (`generative_note`) dan **TIDAK PERNAH**
  dipromosikan menjadi `semantic_facts`. Perceive menawarkan 1 ide pada satu
  waktu (`dream_idea`) hanya saat suasana santai/positif. Dismissed dihormati.

### 4. Ingatan foto — modul mengingat momen dari caption
- Tabel baru `photo_moments` (`moment_id`, `timestamp`, `caption`, `people`,
  `place`, `event_tags`, `source_ref`, `consent_status`, `linked_episode_ids`).
- Caption/metadata masuk lewat parameter opsional `photo_moment` di commit —
  **hanya dari input eksplisit; modul tidak melihat gambar** dan tidak pernah
  mengklaim demikian. Tidak ada file gambar di repo/paket/sync.
- Perceive merujuk **maksimal 1** momen (`photo_reference`) hanya bila
  `consent_status == "granted"` dan ada kecocokan kata kunci, selalu dengan
  catatan ketidakpastian ("berdasarkan caption yang disimpan").
- Koreksi (`photo_moment_action=correct` + `photo_moment_correction`) dan
  penghapusan total (`photo_moment_action=delete`) dihormati; consent
  `revoked` menghentikan rujukan.

### 5. Energi — kalibrasi hemat (fase tes)
- Koefisien dasar drain per turn perceive: **0.012 → 0.010**
  (skala 0.7 noradrenaline / 0.6 cortisol, lantai 0.05, target & tau
  recharge, dan micro-nap +0.08 TIDAK berubah).
- Simulasi 40 turn dari energi 0.85 (appraisal netral): energi akhir
  0.1600 (rumus lama) vs **0.2751** (rumus baru) — penurunan berkurang
  ~16.7%. Pada skenario stres berat, kedua rumus tetap mencapai lantai
  0.05 (jaring pengaman tidak berubah).
- Telemetri energi lokal di tabel `energy_telemetry` (turn, drain, recharge,
  energi, noradrenaline, cortisol — **tanpa konten percakapan**),
  ringkasannya tampil di `cognitive_get_status` (kunci `v040`).

### 6. Bahasa lebih variatif — phrase bank deterministik
- Bank frasa Inggris yang ditinjau (`heart/phrase_bank.py`, versi 1.0) untuk
  fragmen `tone_instruction` (deskripsi BubbleChatRule + fragmen guilt) dan
  seed inner monologue L4 (Indonesia, seperti aslinya).
- Pemilihan deterministik: seed = hash(versi bank | kategori |
  total_turns | mood | bubble_style) — turn yang sama selalu menghasilkan
  frasa yang sama. Seed + versi bank tercatat di `diagnostics` hasil perceive.
- Pemeriksaan konsistensi per varian (token wajib: jumlah bubble & batas
  kata); varian gagal → fallback ke template asli v0.3.1.
- `max_words_per_bubble` bervariasi DALAM cap tiap gaya: dry 6–8, exhausted
  12–14, excited 16–18, normal 20–22. **Nilai enum `bubble_style` tidak
  berubah** (4 nilai yang sama persis).
- Semua fitur baru dapat dimatikan lewat flag di `config.py`
  (`ENABLE_CURIOSITY`, `ENABLE_REMINDERS`, `ENABLE_DREAMS`,
  `ENABLE_PHOTO_MEMORY`, `ENABLE_PHRASE_BANK`, `ENABLE_ENERGY_TELEMETRY`).

### 7. Fondasi (dari laporan ekspansi §4 — "Layak masuk bersama v0.4.0")
- **Identitas giliran:** parameter opsional `turn_id` di perceive & commit
  (tabel `turn_markers`). Retry perceive dengan turn_id sama tidak menguras
  energi dua kali; commit duplikat ditolak (`status: "duplicate_commit"`)
  tanpa menulis ulang episode/apprasial.
- **Penyimpanan commit transaksional:** episode + penanda giliran + aksi
  v0.4.0 tersimpan dalam SATU transaksi SQLite (gagal di tengah = tidak ada
  yang tersimpan setengah-setengah).
- **Provenans minimum:** kolom baru `source` + `inference_status` di
  `semantic_facts` (fakta konsolidasi tidur: `source=episode:<id>`,
  `inference_status=inferred`); mimpi & inferensi tidak pernah menyamar
  sebagai fakta yang dinyatakan.
- **Anggaran retrieval/kandidat:** semua batas terpusat di `config.py`
  (episode 3, fakta 4, chunk GWT 4, kandidat curiosity/pengingat 5,
  kandidat foto 3, scan episode 250).

### 8. Migrasi skema (idempotent)
- `memory/migration.py`: `CREATE TABLE IF NOT EXISTS` untuk 7 tabel baru +
  `ALTER TABLE` additive untuk kolom provenans (dijaga `PRAGMA table_info`).
  Aman dijalankan berulang (tes: 2x run, tanpa duplikat).
- **Sebelum menulis apa pun**, DB disalin ke `<db>.bak-v0.3.1` jika backup
  itu belum ada. Versi skema tercatat di tabel `schema_meta` (= 4).
- Migrasi berjalan otomatis saat `MemoryManager` dibuat dan saat sleep cycle.

### 9. Kompatibilitas
- Kelima tool MCP mempertahankan nama & parameter lama; semua parameter dan
  field hasil baru bersifat opsional. Tidak ada tool baru.
- `cognitive_configure_persona` tidak berubah; attachment Secure tidak disentuh.
- Cakupan `sync_workspace_markdown` tidak berubah; tidak ada foto di sync.
- Pengujian: 29 tes di `tests/test_v040.py` (migrasi, kontrak 5 tool,
  keempat fitur, energi, enum bubble, audit paket, smoke test JSON-RPC
  MCP) — semuanya memakai fixture DB & temp HOME, tanpa menyentuh live state.

## Pertanyaan Terbuka (dibawa dari rencana Sol — belum diputuskan)
- Apakah pertanyaan/niat boleh menyentuh topik sensitif? (v0.4.0: ditunda/dilewati secara konservatif.)
- Seberapa sering pengingat & curiosity boleh muncul, dan perlu jam tenang? (v0.4.0: cooldown 30/60 menit, tanpa jam tenang.)
- Mimpi: hanya disimpan, ditampilkan saat diminta, atau boleh ditawarkan? (v0.4.0: ditawarkan 1 per satu saat suasana santai.)
- Jalur foto resmi & metadata lokasi/wajah? (v0.4.0: caption eksplisit dari supervisor; metadata lokasi/wajah hanya bila diberikan eksplisit + consent granted.)
- Apakah metadata foto/niat ikut sync ke Drive? (v0.4.0: TIDAK — hanya DB yang sudah di-sync seperti biasa; tidak ada sync baru.)
- Energi: pertahankan sebagai sinyal persona, atau kurangi dampaknya? (v0.4.0: dipertahankan, hanya koefisien dasar diturunkan.)
- Variasi bahasa: Inggris saja atau dukung bahasa lain? (v0.4.0: tone Inggris + monolog Indonesia, seperti template yang ada.)

---

# AI Cognitive Core MCP v0.3.0 — Patch Notes (Maintainer Release)

## Pembaruan Utama (v0.3.0)
1. **Time-Based Energy Charging (`l1_neurochemical.py` & `engine.py`):**
   - Menghapus pengisian energi instan `0.85` dalam 1 turn.
   - Saat `cognitive_sleep_cycle` dipanggil, sistem hanya memberi *micro-nap boost* `+0.08` dan menyalakan mode `is_resting = True`.
   - Selama ditinggal istirahat, energi mengisi ulang secara eksponensial berdasarkan **durasi waktu nyata (`delta_seconds`)** dengan konstanta waktu $\tau = 40\text{ menit}$ menuju `0.92`:
     $$E(t) = E_{\text{target}} - (E_{\text{target}} - E_0) \cdot e^{-\Delta t / 2400}$$
   - Saat idle biasa (tanpa perintah tidur), energi juga mengisi perlahan dengan $\tau = 2\text{ jam}$ menuju `0.85`.
   - Memperbaiki *double energy drain* (energi kini hanya berkurang 1x per giliran chat saat `perceive`, tidak terkuras lagi saat `commit_turn`).

2. **Modulator Gaya Bubble Chat (`engine.py` -> `EmotionalDirective`):**
   - Menambahkan field `bubble_style`, `recommended_bubbles`, dan `max_words_per_bubble`:
     - `excited_multi_bubble`: Energi $\ge 0.65$ & Mood Positif $\rightarrow$ Pecah respons menjadi **2–3 bubble chat pendek bertubi-tubi** (maks 15–18 kata per bubble, dilarang 1 paragraf panjang).
     - `normal_1_to_2_bubbles`: Energi menengah $\rightarrow$ **1–2 bubble chat santai** (maks 20–22 kata per bubble).
     - `exhausted_sleepy_1_bubble`: Energi $< 0.32$ $\rightarrow$ **1 bubble pendek** (maks 14 kata), nada ngantuk/lelah, minta istirahat.
     - `dry_short_1_bubble`: Mood negatif (`Hostile`/`Disdainful`) atau `DetachedProtector` aktif $\rightarrow$ **1 bubble super singkat (1–8 kata)**, cuek/ketus/jual mahal.

3. **Detektor Gaya Texting & Jeda Balas (`l4_appraisal.py`):**
   - **Dry Texting Detector:** Mendeteksi balasan singkat/cuek (`"y"`, `"ok"`, `"oh"`, `"gpp"`, $\le 4$ huruf tanpa ekspresi) $\rightarrow$ menurunkan `goal_conduciveness` (`-0.22`) dan `arousal`.
   - **Expressive / Manja Texting:** Mendeteksi perpanjangan huruf (`sayanggg`, `iyaaa`, `yeyyy`), tawa (`wkwk`, `hehe`), dan emoji kasih sayang.
   - **Cold Period & ALL CAPS:** Mendeteksi kalimat pasif-agresif bertitik (`"Terserah."`, `"Yaudah."`) serta ketikan huruf besar semua.
   - **Response Latency:** Bonus antusiasme untuk *fast reply* ($\le 45\text{ detik}$) dan reaksi kangen/gengsi jika ditinggal $\ge 6\text{ jam}$.

4. **Optimasi Latency & Backup `.md` Incremental (`drive_bridge.py`):**
   - **Async Background Push:** `cognitive_commit_turn` mengunggah state ke Google Drive di *background thread* sehingga respons chat tidak tertahan.
   - **Smart Pull Cooldown & File ID Cache:** Menghemat 85% waktu request Google Drive API saat sedang chat aktif di perangkat yang sama.
   - **Workspace `.md` Incremental Sync:** Menyinkronkan `IDENTITY.md`, `SOUL.md`, `USER.md`, `MEMORY.md`, `GOAL.md`, dan folder `memory/` hanya jika hash SHA-256 berubah saat `cognitive_sleep_cycle`.

## Patch v0.3.1 (15 Nov 2026 — di atas rilis maintainer v0.3.0)

1. **Whitelist backup `.md` (`drive_bridge.py` → `sync_workspace_markdown`):**
   - Mengganti `rglob("*.md")` (menyapu semua file `.md` sampai kedalaman 3, termasuk `docs/`, `memory/people/`, `memory/groups/`, `side-chats/`, `PATCH_NOTES.md`, `README.md`) dengan whitelist eksplisit: 7 file utama di root workspace (`IDENTITY.md`, `SOUL.md`, `USER.md`, `MEMORY.md`, `AGENTS.md`, `TOOLS.md`, `PROACTIVE_PREFERENCES.md`), catatan harian `memory/*.md`, bank memori `memory/bank/*.md`, dan file `.md` di tiap folder goal (`workspace/goals/*/`). Tes: 20 file ter-upload, run kedua 0 upload / 20 skip.
   - Catatan: skema path v0.3.x memakai `workspace/goals/<slug>/` (v0.2.0 memakai `goals/<slug>/`), jadi folder `goals/` lama di Drive berisi salinan usang.

2. **Push sinkron di `cognitive_commit_turn` (`mcp_server.py`):**
   - `async_mode=True` tidak pernah selesai di one-shot MCP call (proses server keluar sebelum thread daemon upload selesai; terverifikasi: file Drive tidak berubah setelah commit). Diubah ke `async_mode=False`; dengan `_file_id_cache`, upload sinkron tetap cepat dan dijamin selesai. Field hasil commit kembali bernama `gdrive_synced`.
