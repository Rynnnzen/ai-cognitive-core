"""
Parameter v0.5.1 dalam SATU tempat (mudah di-tune).

Semua nilai di sini adalah nilai live yang sudah disetel selama pemakaian
nyata — lihat CHANGELOG.md untuk alasan setiap angka. Nilai lama v0.3.1 /
v0.4.0 dicantumkan di komentar sebagai pembanding. Jangan mengubah nilai
enum bubble_style di sini; nilainya dikunci kontrak eksternal dan
didefinisikan di heart/engine.py.

Fitur baru dapat dimatikan satu per satu lewat flag ENABLE_* di bawah
(default True).
"""

# ---------------------------------------------------------------------------
# Feature flags v0.4.0 (matikan satu fitur tanpa menyentuh kode lain)
# ---------------------------------------------------------------------------
ENABLE_CURIOSITY = True
ENABLE_REMINDERS = True
ENABLE_DREAMS = True
ENABLE_PHOTO_MEMORY = True
ENABLE_PHRASE_BANK = True
ENABLE_ENERGY_TELEMETRY = True

# ---------------------------------------------------------------------------
# Energi (l1_neurochemical.py mengimpor nilai drain dari sini)
# ---------------------------------------------------------------------------
# Koefisien dasar drain per turn perceive. v0.3.1: 0.012 (drain 0.012-0.028).
# v0.4.0 fase tes: 0.010 (drain 0.010-0.023) — penghematan ~17% per turn.
ENERGY_BASE_DRAIN = 0.010
ENERGY_NORADRENALINE_COEF = 0.7  # tidak berubah dari v0.3.1
ENERGY_CORTISOL_COEF = 0.6       # tidak berubah dari v0.3.1
ENERGY_FLOOR = 0.05              # tidak berubah dari v0.3.1
# Target & tau recharge TIDAK berubah: idle 0.85 (tau 2 jam), resting 0.92
# (tau 40 menit), micro-nap sleep +0.08 (cap 0.92). Nilainya tetap tinggal di
# heart/layers/l1_neurochemical.py dan heart/engine.py.

# ---------------------------------------------------------------------------
# Curiosity
# ---------------------------------------------------------------------------
MAX_PENDING_CURIOSITY = 20       # pertanyaan pending terbanyak yang disimpan
CURIOSITY_COOLDOWN_MINUTES = 5  # v0.4.1/v0.5.0: lebih longgar & sering muncul (v0.4.0: 30)  # jeda minimum antar penawaran pertanyaan
CURIOSITY_MIN_TURNS_BETWEEN = 1  # v0.4.1/v0.5.0: jeda 1 turn (v0.4.0: 3)  # jeda minimum (dalam turn) antar penawaran
CURIOSITY_DEFAULT_TTL_DAYS = 14  # pertanyaan kedaluwarsa setelah 14 hari
CURIOSITY_CANDIDATE_BUDGET = 5   # kandidat yang dinilai per perceive (top 1 dikembalikan)
# Kata kunci distres: curiosity TIDAK ditawarkan saat turn menyentuh topik ini.
CURIOSITY_SENSITIVE_KEYWORDS = (
    "sedih", "meninggal", "sakit", "menangis", "takut", "kecewa",
    "marah", "kesal", "capek banget", "lelah banget", "ketipu",
    "scam", "ditipu", "rugi", "bangkrut",
)
# Kata kunci tugas eksplisit: curiosity ditunda saat user sedang meminta sesuatu.
CURIOSITY_TASK_KEYWORDS = (
    "cari", "cek", "buatin", "bikinin", "install",
    "tolong", "minta", "download", "upload", "lapor", "riset", "bedah",
)

# ---------------------------------------------------------------------------
# Niat mandiri / pengingat
# ---------------------------------------------------------------------------
MAX_PENDING_REMINDERS = 20
REMINDER_COOLDOWN_MINUTES = 60   # jeda minimum sebelum niat yang sama muncul lagi
REMINDER_CANDIDATE_BUDGET = 5    # kandidat yang dinilai per perceive (top 1 dikembalikan)
REMINDER_EXPIRY_GRACE_HOURS = 24  # niat tanpa repeat kedaluwarsa 24 jam setelah due_at
REMINDER_REPEAT_POLICIES = ("none", "daily")

# ---------------------------------------------------------------------------
# Mimpi
# ---------------------------------------------------------------------------
DREAMS_PER_SLEEP_MAX = 3         # ide mimpi terbanyak yang dirangkai per sleep cycle
MAX_STORED_DREAMS = 30           # DreamRecord tersimpan terbanyak (yang lama di-prune)
DREAM_MIN_EPISODE_IMPORTANCE = 0.35  # v0.4.1/v0.5.0: turunkan ambang agar mimpi tidak mudah habis  # episode di bawah ini tidak dipakai sebagai sumber mimpi

# ---------------------------------------------------------------------------
# Ingatan foto
# ---------------------------------------------------------------------------
MAX_PHOTO_MOMENTS = 200
PHOTO_CANDIDATE_BUDGET = 3       # kandidat momen foto yang dinilai per perceive
PHOTO_MIN_KEYWORD_OVERLAP = 1    # minimal 1 kata kunci cocok agar momen dirujuk
# consent_status yang mengizinkan momen dirujuk di percakapan.
PHOTO_SURFACEABLE_CONSENT = ("granted",)

# ---------------------------------------------------------------------------
# Anggaran retrieval / kandidat (fondasi laporan ekspansi §4)
# ---------------------------------------------------------------------------
RETRIEVAL_TOP_K_EPISODES = 3     # sama seperti v0.3.1
RETRIEVAL_TOP_K_FACTS = 4        # sama seperti v0.3.1
GWT_MAX_CHUNKS = 4               # sama seperti v0.3.1
EPISODE_SCAN_LIMIT = 250         # sama seperti v0.3.1 (run_bounded_ppr)

# ---------------------------------------------------------------------------
# Variasi bahasa (phrase bank)
# ---------------------------------------------------------------------------
PHRASE_BANK_VERSION = "1.0"
# Rentang max_words_per_bubble per gaya (tidak pernah di atas cap v0.3.1).
MAX_WORDS_RANGE = {
    "dry_short_1_bubble": (6, 8),
    "exhausted_sleepy_1_bubble": (12, 14),
    "excited_multi_bubble": (16, 18),
    "normal_1_to_2_bubbles": (20, 22),
}

# ---------------------------------------------------------------------------
# Parameter v0.4.1 — Drive Sync, Adaptasi (L5), Mimpi, Emoji, & Guardrail Longgar
# ---------------------------------------------------------------------------
ENABLE_DRIVE_SYNC = True
DRIVE_PUSH_DB_ON_COMMIT = False
DRIVE_CRITICAL_ENERGY_THRESHOLD = 0.10

DREAM_CANDIDATE_LIMIT = 40
DREAM_TECHNICAL_WORD_THRESHOLD = 3

ENABLE_ADAPTIVE_HABITS = True
HABIT_TOP_K = 3
HABIT_MIN_SCORE = -1

RECALL_TECH_DOMAIN_PENALTY = 0.65
LUBB_STRICT_MODE = False
ENABLE_EMOJI_PALETTE = True

# ---------------------------------------------------------------------------
# Parameter v0.5.0 — Ekspansi Penuh
# 1. Persistent Working Memory (L2 SQLite)
# 2. Ritme Sirkadian (jam biologis lokal)
# 3. Idle Heartbeat Proaktif (dengan jam tenang)
# 4. Papan Supervisi Worker Bot (Task Blackboard)
# 5. Evolusi Relasi (Trust) & Inside Jokes
# ---------------------------------------------------------------------------
ENABLE_PERSISTENT_WORKING_MEMORY = True
WORKING_MEMORY_PERSIST_CAPACITY = 6

ENABLE_CIRCADIAN_RHYTHM = True
CIRCADIAN_TZ_OFFSET_HOURS = 7       # Default WIB (UTC+7)
CIRCADIAN_LATE_NIGHT_START = 23     # 23:00 - 04:59: fase begadang (drain lebih cepat)
CIRCADIAN_LATE_NIGHT_END = 5
CIRCADIAN_MORNING_START = 5         # v0.5.1 (M6): 05:00 - 10:59 = morning (sebelumnya 06:00, jam 05:00 jatuh ke evening)
CIRCADIAN_MORNING_END = 11
CIRCADIAN_DAYTIME_END = 18          # v0.5.1 (M6): 11:00 - 17:59 = daytime; 18:00 - 22:59 = evening
CIRCADIAN_LATE_NIGHT_DRAIN_MULT = 1.30
CIRCADIAN_MORNING_RECHARGE_BONUS = 1.15

ENABLE_IDLE_HEARTBEAT = True
QUIET_HOURS_START = 23              # Jam tenang proaktif: 23:00 - 06:59
QUIET_HOURS_END = 7
IDLE_HEARTBEAT_MIN_MINUTES = 45     # Minimal idle 45 menit sebelum sapa proaktif ringan

ENABLE_WORKER_BLACKBOARD = True
MAX_ACTIVE_WORKER_TASKS = 30

ENABLE_RELATIONSHIP_EVOLUTION = True
MAX_INSIDE_JOKES = 50

# ---------------------------------------------------------------------------
# Parameter v0.5.1 — Kalibrasi evolusi relasi (temuan audit M5)
# Trust naik/turun per giliran positif/negatif; ambang stage menentukan
# relationship_stage. v0.5.0 memakai +0.012/-0.020 hardcoded di engine —
# terlalu cepat untuk klaim "evolves slowly" (deep_bond dalam ~21 giliran).
# ---------------------------------------------------------------------------
TRUST_POS_DELTA = 0.004
TRUST_NEG_DELTA = -0.012
TRUST_STAGE_DEEP_BOND = 0.80
TRUST_STAGE_CLOSE = 0.60
TRUST_STAGE_WARM = 0.40

# Batas inersia emosi untuk pemulihan bertahap (temuan audit M13).
INERTIA_BASELINE_PI1 = 0.35
INERTIA_RECOVERY_STEP = 0.02

# ---------------------------------------------------------------------------
# Parameter v0.6.0 — Fondasi ekspansi PAD (4 ekspansi)
# Hanya parameter + field skema; logika engine belum memakai nilai ini.
# Semua default aman; heart_state.json lama tetap terbaca (tanpa migrasi).
# ---------------------------------------------------------------------------
ENABLE_PAD_EXPANSION = True
PAD_INTENSITY_MILD_MAX = 0.35
PAD_INTENSITY_MODERATE_MAX = 0.75
PAD_TRAJECTORY_DEADBAND = 0.06
PAD_HEDONIC_PLEASURE_THRESHOLD = 0.75
PAD_HEDONIC_STREAK_TRIGGER = 3
PAD_HEDONIC_ELASTIC_PULL = 0.08
NEURO_SATURATION_THRESHOLD = 0.88
NEURO_SATURATION_DAMPING = 0.35

# ---------------------------------------------------------------------------
# Parameter v0.6.1 — Aturan seleksi backup foto/media Google Drive
# Foto harian/umum TIDAK ikut backup otomatis ke Drive (photos/).
# Hanya dua kategori yang boleh di-backup:
#   a) character sheet & aset referensi gaya visual utama (ref_keep/),
#      saat ada perubahan model atau art style;
#   b) foto momen yang benar-benar berkesan — ditandai favorit/milestone/
#      penting, atau disimpan di subfolder khusus (memorable/ atau
#      favorites/) di dalam folder sumbernya.
# Aturan ini ditegakkan oleh skrip backup foto (tooling sisi agen, bukan
# bagian paket) yang mengimpor konstanta di bawah ini.
# Foto kiriman user (media_library/) tetap TIDAK pernah di-backup.
# ---------------------------------------------------------------------------
ENABLE_DRIVE_PHOTOS_SYNC = True
# Subfolder lokal (relatif terhadap workspace) berisi character sheet &
# aset referensi gaya visual utama.
DRIVE_PHOTOS_CHARACTER_SHEET_DIR = "ref_keep"
# Subfolder khusus di dalam tiap folder sumber foto yang menandai momen
# berkesan (difavoritkan / milestone / penting).
DRIVE_PHOTOS_MEMORABLE_SUBDIRS = ("memorable", "favorites")
# Folder kandidat avatar — aset identitas visual, ikut di-backup.
DRIVE_PHOTOS_AVATAR_DIR = "avatars"
# Folder sumber foto harian yang TIDAK di-backup massal (hanya subfolder
# memorable/favorites di dalamnya yang ikut).
DRIVE_PHOTOS_DAILY_SOURCE_DIR = "imagine_media"

# ---------------------------------------------------------------------------
# Parameter v0.6.1 — Dashboard web ringan (pengganti Obsidian)
# Endpoint FastAPI di dashboard/; UI statis di dashboard/static/.
# Dashboard bersifat lokal saja (bind 127.0.0.1, tanpa auth) — jangan
# diekspos ke publik. Port bisa diubah lewat COGNITIVE_DASHBOARD_PORT.
# ---------------------------------------------------------------------------
ENABLE_DASHBOARD = True
DASHBOARD_DEFAULT_PORT = 8000
DASHBOARD_GRAPH_LIMIT = 200
