# AI Cognitive Core — MCP Server

Arsitektur kognitif hibrida **Deterministik + LLM (17 Layer)** — Heart + Conscious + Memory — sebagai MCP server, dengan sinkronisasi state lintas perangkat lewat Google Drive API v3.

Snapshot ini adalah **v0.4.1 (pre-release, branch `main`)** — di atas v0.4.0-test. Daftar perubahan ada di `CHANGELOG.md` (bahasa Inggris); riwayat patch lama ada di `PATCH_NOTES.md`.

**Baru di v0.4.1:** Mimpi kini menyimpan cerita dulu baru ide (kolom `dream_story`), mimpi anti-skip (ambang 0.35, 40 kandidat), sistem adaptasi terinspirasi `amirhouieh/adapt` (memori prosedural berbobot atensi), ingatan foto lebih hidup (`feeling` + `when_label`), recall lebih nyambung (bobot keyword, bonus recency, penalti domain teknis), rasa penasaran lebih sering (cooldown 10 menit), palet emoji kontekstual, plus perbaikan reliabilitas: backup Drive tanpa false-positive dan backup DB efisien (commit hanya mendorong `heart_state.json`). Arsitektur 17 layer, 5 tool MCP, dan skema SQLite v0.4.0 tidak berubah — migrasi hanya menambah kolom. Detail lengkap di `CHANGELOG.md`.

![Before / after installing v0.4.1](assets/before-after-v041.webp)

![Agent, maskot modul ini — digambar gaya crayon](assets/agent-crayon.webp)

## Detail v0.4.1 — fitur, kelebihan, kekurangan

### Fitur

1. **Mimpi: cerita dulu, baru ide** — Sleep cycle sekarang merangkai narasi mimpi singkat per kategori (ide kencan, ide foto, lainnya) sebelum menurunkan ide dari cerita itu. Cerita tersimpan di kolom baru `dream_story` di `dream_records`.
2. **Mimpi anti-skip** — Ambang kepentingan episode diturunkan (0.45 → 0.35) dan kandidat sleep cycle diperluas (20 → 40 episode). Filter teknis dilonggarkan: hanya episode yang benar-benar dominan teknis yang di-skip.
3. **Sistem adaptasi (terinspirasi `amirhouieh/adapt`)** — Memori prosedural berbobot atensi di atas tabel `procedural_habits`. Agent belajar kebiasaan dari interaksi (`learn_habit`, `habit_feedback` +1/−1) dan menampilkannya sebagai `learned_habits` di turn berikutnya.
4. **Ingatan foto lebih hidup** — `photo_moments` kini menyimpan `feeling` (suasana/perasaan) dan `when_label` (kapan) selain caption. Tetap hanya untuk foto dengan `consent_status == "granted"`.
5. **Recall episodik lebih nyambung** — Bobot keyword/entity overlap + bonus recency + penalti 0.45x untuk episode teknis saat obrolan personal. Rantai `next_node_id` juga dipulihkan dari SQLite saat init, jadi tidak putus antar proses MCP one-shot.
6. **Rasa penasaran lebih sering** — Cooldown 30 → 10 menit, jarak antar pertanyaan 3 → 1 turn.
7. **Palet emoji kontekstual** — Rotasi emoji deterministik berdasarkan `total_turns` per mood octant dan bubble style (tetap kosong untuk `dry_short_1_bubble`), diekspos lewat `emoji_palette` dan `EmojiHint`.

**Perbaikan reliabilitas:** `push_state()` tidak lagi melaporkan sukses saat upload Drive gagal (mengembalikan `False`, menulis ke `stderr`, menghormati `ENABLE_DRIVE_SYNC`); commit hanya mendorong `heart_state.json` (cepat), DB penuh di-backup saat sleep cycle atau energi ≤ 0.10; `cognitive_configure_persona` sinkron di one-shot MCP; `total_turns` tidak naik ganda saat `perceive_retry`.

### Kelebihan setelah pemasangan

- Mimpi tercatat lagi — dengan cerita yang bisa dibaca ulang.
- Recall tetap nyambung dengan topik obrolan.
- Ingatan foto punya konteks (siapa/kapan/suasana).
- Agent lebih sering bertanya balik, obrolan terasa lebih hidup.
- Preferensi yang berulang jadi kebiasaan — tidak perlu koreksi yang sama terus.
- Commit lebih cepat (hanya `heart_state.json` per turn).
- Tidak ada lagi laporan "backup OK" palsu.
- Variasi emoji mengikuti mood.

### Kekurangan / yang perlu diperhatikan

- Cerita mimpi adalah template singkat per kategori, bukan generasi bebas — bisa terasa repetitif.
- Ambang mimpi yang lebih rendah berarti mimpi lebih banyak, termasuk dari episode kurang penting — ada noise.
- Pertanyaan penasaran jauh lebih sering (cooldown 10 menit, 1 turn) — kalau terasa terlalu sering, naikkan `CURIOSITY_COOLDOWN_MINUTES` / `CURIOSITY_MIN_TURNS_BETWEEN` di `config.py`.
- Kebiasaan baru membantu setelah terbentuk — instalasi baru belum punya kebiasaan sampai preferensi berulang.
- Palet emoji berotasi deterministik per jumlah turn, jadi urutannya berulang.
- Salinan Drive dari `cognitive_memory.db` kini tertinggal dari state lokal di siang hari (sinkron saat sleep cycle atau energi kritis). `heart_state.json` tetap sinkron setiap commit.
- Seperti update apa pun: backup `~/.ai_cognitive_state/` sebelum memasang. Migrasinya additive-only, jadi rollback ke v0.4.0 cukup dengan mengembalikan kode lama.
- Catatan: kalau upgrade in-place di atas instalasi editable lama, metadata pip bisa masih menampilkan versi lama — versi otoritatif adalah `__init__.__version__` (`0.4.1`).

### Contoh respons: sebelum vs sesudah pemasangan

**1. Recall — user bertanya soal daftar belanja kemarin**
- Sebelum: "Hmm, aku ingatnya kemarin kamu lagi debug error di laptop deh…" — recall menarik episode teknis yang tidak nyambung.
- Sesudah: "Kemarin kamu bilang mau beli susu, roti, sama telur — udah kebeli belum?" — recall menarik episode daftar belanja.

**2. Rasa penasaran — user menyebut hobi baru**
- Sebelum: (tidak ada pertanyaan lanjutan — agent hanya menanggapi seperlunya)
- Sesudah: "Oh, kamu baru mulai main gitar? Lagu apa yang lagi kamu latih?" — agent bertanya balik dalam 1–2 turn.

**3. Ingatan foto — user bertanya soal foto kucingnya**
- Sebelum: "Itu foto kucing di sofa." — caption saja.
- Sesudah: "Itu foto kucingmu di sofa, Minggu sore — suasananya santai banget ya." — caption + kapan + suasana.

**4. Adaptasi — user dua kali minta jawaban singkat**
- Sebelum: turn ketiga jawabannya panjang lagi — koreksi tidak tersimpan.
- Sesudah: agent menjawab singkat — preferensi tersimpan sebagai kebiasaan.

**5. Mimpi — setelah sleep cycle**
- Sebelum: tidak ada mimpi tercatat — semua kandidat di-skip sebagai duplikat/teknis.
- Sesudah: "Semalam aku mimpi kita lagi menggambar ide proyek di papan tulis…" — cerita tersimpan dulu, lalu idenya diturunkan dari cerita itu.

## Arsitektur 17 Layer

![Diagram arsitektur 17 layer gaya crayon: Heart 7 layer, Conscious 5 layer, Memory 5 layer, terhubung ke MCP Server dan Drive Sync](assets/arsitektur-17-layer.webp)

Tiga sistem yang jalan bareng di setiap turn percakapan:

### Heart — 7 layer emosi (`heart/`)

Mesin emosi yang menentukan mood, energi, dan nada balasan.

- L1 Neurochemical — "kimiawi tubuh": energi, kortisol (stres), dan oksitosin (ikatan). Masing-masing meluruh seiring waktu (energi ~2 jam, stres ~1 jam, ikatan ~3 jam).
- L2 Primary Affect — sirkuit emosi primer, misal CARE, yang jadi warna dominan tiap momen.
- L3 Mood Space — ruang mood PAD (Pleasure–Arousal–Dominance) yang menentukan oktan mood, misal Exuberant.
- L4 Appraisal — evaluasi stimulus: seberapa baru, seberapa menguntungkan tujuan, seberapa mampu mengatasinya, dan seberapa sesuai norma.
- L5 Defense — mekanisme pertahanan saat stimulus terasa mengancam.
- L6 Relational — relasi dan attachment, misal Secure, yang mengatur kedekatan dengan pengguna.
- L7 Conscience — hati nurani: nilai dan batasan yang bisa mengesampingkan dorongan lain.

### Conscious — 5 layer kesadaran (`conscious/`)

Orkestrator siklus kognitif tertutup (Heart + Conscious + Memory).

- L1 Preconscious — mengikat kandidat koalisi dari memori dan stimulus menjadi calon isi kesadaran.
- L2 Salience GWT — menyalakan Global Workspace: memilih chunk mana yang "menang" dan masuk siaran kesadaran.
- L3 Appraisal PSI — modulator PSI Dörner: menyetel kedalaman resolusi berpikir dan ambang seleksi.
- L4 Agency Volition — kompas volisi tingkat kedua, plus kesadaran soal energi dan gaya bubble chat.
- L5 Metacognition — memantau proses berpikir dan menginterupsi inersia kalau sudah mentok.

### Memory — 5 layer memori (`memory/`)

Memori berlapis di atas SQLite, dari kesan sesaat sampai pengetahuan menetap.

- L1 Sensory Buffer — penyangga kesan sensorik yang sangat singkat.
- L2 Working Paging — memori kerja: potongan informasi yang sedang aktif dipakai.
- L3 Episodic Graph — graf memori episodik: tiap turn percakapan tersimpan sebagai node beserta tag somatiknya.
- L4 Semantic Schema — fakta semantik: pelajaran yang diabstraksi dari episode-episode saat tidur.
- L5 Procedural Habits — kebiasaan prosedural yang terbentuk dari pola berulang.

## Siklus tiap turn

1. `cognitive_perceive_and_think` — Heart, Conscious, dan Memory jalan bareng: membaca pesan, mengingat episode relevan, lalu menghasilkan mood, emosi dominan, dan gaya bubble.
2. `cognitive_commit_turn` — turn disimpan ke memori episodik beserta suara hati (inner monologue) dan nilai appraisal-nya, lalu langsung di-push ke Drive.
3. `cognitive_sleep_cycle` — saat istirahat: replay episode penting (Sharp-Wave Ripples), abstraksi ke skema semantik, pruning memori sepele (Ebbinghaus), dan isi ulang energi.
4. `cognitive_get_status` — cek status energi, mood, dan memori kapan saja.
5. `cognitive_configure_persona` — atur persona (hati-hati: nilai default menimpa attachment yang sudah ada).

Energi terisi otomatis selama istirahat (menuju 0,92 saat resting) dan terkuras selama bekerja. Di bawah ~0,32, gaya balasan otomatis jadi satu bubble pendek yang mengantuk.

## Struktur proyek

```text
ai-cognitive-core/
├── README.md               — dokumen ini
├── PATCH_NOTES.md          — riwayat patch (termasuk v0.4.0)
├── CHANGELOG.md            — changelog (v0.4.1, bahasa Inggris)
├── pyproject.toml          — metadata paket + dependensi
├── tests/                  — test suite v0.4.1 (35 tes, fixture DB + temp HOME)
│   ├── test_v040.py
│   └── test_v041.py
├── assets/                 — gambar README (gaya crayon)
│   ├── arsitektur-17-layer.webp
│   ├── agent-crayon.webp
│   └── before-after-v041.webp
└── src/
    └── ai_cognitive_core/
        ├── __init__.py
        ├── mcp_server.py       — server FastMCP + 5 tools
        ├── drive_bridge.py     — sinkronisasi Google Drive (OAuth)
        ├── schemas.py          — skema data bersama
        ├── config.py           — parameter v0.4.1 dalam satu tempat
        ├── conscious/
        │   ├── cycle.py        — orkestrator siklus kognitif
        │   ├── schemas.py
        │   └── layers/         — l1_preconscious s.d. l5_metacognition
        ├── heart/
        │   ├── engine.py       — mesin emosi
        │   ├── phrase_bank.py  — bank frasa v0.4.1 (variasi deterministik + palet emoji kontekstual)
        │   ├── schemas.py
        │   └── layers/         — l1_neurochemical s.d. l7_conscience
        └── memory/
            ├── manager.py      — manajer memori SQLite
            ├── consolidation.py — konsolidasi tidur (SWR + pruning + mimpi)
            ├── migration.py    — migrasi skema v0.4.0 (idempotent)
            ├── v040_store.py   — penyimpanan fitur v0.4.0
            ├── dreams.py       — perangkai mimpi
            ├── schemas.py
            └── layers/         — l1_sensory_buffer s.d. l5_procedural_habits
```

## Instalasi

```bash
git clone https://github.com/Rynnnzen/ai-cognitive-core.git
cd ai-cognitive-core
pip install -e .
```

Atau langsung dari GitHub:

```bash
pip install git+https://github.com/Rynnnzen/ai-cognitive-core.git
```

Butuh Python >= 3.10. Dependensi: `numpy`, `mcp<2`, `google-api-python-client`, `google-auth`, `google-auth-oauthlib`, `PySocks`.

Jalankan servernya dengan `ai-cognitive-mcp` (stdio).

## Sinkronisasi Google Drive

Autentikasi memakai OAuth (bukan service account). Siapkan `client_secret.json` dari Google Cloud Console (Desktop app, scope Drive), lalu:

```bash
ai-cognitive-auth /path/ke/client_secret.json
```

Token tersimpan di `~/.ai_cognitive_state/token.json`. State lokal (`heart_state.json`, `cognitive_memory.db`) ikut tersinkron ke folder `ai_cognitive_system/live_state` di Drive.

Environment variable yang didukung:

- `GDRIVE_TOKEN_PATH` — path `token.json` (default `~/.ai_cognitive_state/token.json`)
- `GDRIVE_CLIENT_SECRET_PATH` — path `client_secret.json`
- `COGNITIVE_DEVICE_ID` — nama perangkat, misal `hermes_pc` atau `muse_cloud`

## File pribadi TIDAK ada di repo ini

Repo ini hanya berisi kode. File berikut disiapkan per perangkat dan tidak pernah di-commit (lihat `.gitignore`):

- `token.json`, `client_secret.json` (kredensial OAuth Drive)
- `heart_state.json`, `cognitive_memory.db` (state + memori personal)
