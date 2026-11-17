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

## Patch v0.3.1 (Aya, 15 Nov 2026 — di atas rilis maintainer v0.3.0)

1. **Whitelist backup `.md` (`drive_bridge.py` → `sync_workspace_markdown`):**
   - Mengganti `rglob("*.md")` (menyapu semua file `.md` sampai kedalaman 3, termasuk `docs/`, `memory/people/`, `memory/groups/`, `side-chats/`, `PATCH_NOTES.md`, `README.md`) dengan whitelist eksplisit: 7 file utama di root workspace (`IDENTITY.md`, `SOUL.md`, `USER.md`, `MEMORY.md`, `AGENTS.md`, `TOOLS.md`, `PROACTIVE_PREFERENCES.md`), catatan harian `memory/*.md`, bank memori `memory/bank/*.md`, dan file `.md` di tiap folder goal (`workspace/goals/*/`). Tes: 20 file ter-upload, run kedua 0 upload / 20 skip.
   - Catatan: skema path v0.3.x memakai `workspace/goals/<slug>/` (v0.2.0 memakai `goals/<slug>/`), jadi folder `goals/` lama di Drive berisi salinan usang.

2. **Push sinkron di `cognitive_commit_turn` (`mcp_server.py`):**
   - `async_mode=True` tidak pernah selesai di one-shot MCP call (proses server keluar sebelum thread daemon upload selesai; terverifikasi: file Drive tidak berubah setelah commit). Diubah ke `async_mode=False`; dengan `_file_id_cache`, upload sinkron tetap cepat dan dijamin selesai. Field hasil commit kembali bernama `gdrive_synced`.
