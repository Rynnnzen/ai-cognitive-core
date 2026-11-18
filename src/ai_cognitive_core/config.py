"""
Parameter v0.4.0 dalam SATU tempat (mudah di-tune selama fase tes).

Semua nilai di sini adalah nilai FASE TES — lihat PATCH_NOTES.md bagian v0.4.0
untuk alasan setiap angka. Nilai lama v0.3.1 dicantumkan di komentar sebagai
pembanding. Jangan mengubah nilai enum bubble_style di sini; nilainya dikunci
kontrak eksternal dan didefinisikan di heart/engine.py.

Fitur baru v0.4.0 dapat dimatikan satu per satu lewat flag ENABLE_* di bawah
(default True pada fase tes agar semuanya teruji).
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
CURIOSITY_COOLDOWN_MINUTES = 30  # jeda minimum antar penawaran pertanyaan
CURIOSITY_MIN_TURNS_BETWEEN = 3  # jeda minimum (dalam turn) antar penawaran
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
    "cari", "cek", "buatin", "bikinin", "kirim", "update", "install",
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
DREAM_MIN_EPISODE_IMPORTANCE = 0.45  # episode di bawah ini tidak dipakai sebagai sumber mimpi

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
