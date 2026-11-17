"""
Perangkai mimpi v0.4.0 — ide kreatif dari sleep cycle.

Mimpi dirangkai dari episode berkepentingan tinggi yang baru dikonsolidasi,
menggunakan template yang sudah ditinjau (bukan LLM): satu tema diambil dari
entitas episode, lalu dimasukkan ke template ide kencan/foto/lainnya.

Aturan keras:
- Ide selalu ditandai generatif (DreamRecord) — TIDAK PERNAH ditulis ke
  semantic_facts dan tidak pernah diklaim sebagai kejadian nyata.
- Episode sensitif dilewati (tidak dipakai sebagai sumber mimpi).
- Maksimal DREAMS_PER_SLEEP_MAX ide per sleep cycle; duplikat (tema + set
  episode sumber yang sama) tidak ditulis ulang.
"""

import hashlib
import sqlite3
from typing import Dict, List

from ai_cognitive_core import config
from ai_cognitive_core.memory import v040_store

# Episode yang menyentuh kata ini tidak dipakai sebagai sumber mimpi.
_SENSITIVE_WORDS = (
    "sedih", "meninggal", "sakit", "marah", "kesal", "kecewa", "bertengkar",
    "menangis", "takut", "ketipu", "scam", "ditipu", "rugi", "bangkrut",
    "benci", "putus", "berantem",
)

# Tema mimpi HANYA boleh berasal dari daftar konsep ini — kata benda, tempat,
# dan momen yang enak dibaca sebagai tema kencan/foto. Di luar daftar, temanya
# jatuh ke "momen manis". Daftar ini ada karena heuristik "entitas terpanjang"
# terbukti gagal di data asli: token chat mentah seperti "sayanggg",
# "ngomongin", atau "ututuuuu" sempat jadi tema mimpi yang tidak masuk akal.
_THEME_CONCEPTS = frozenset({
    "hitachi", "nemophila", "pantai", "laut", "taman", "bunga", "sakura",
    "mawar", "melati", "hujan", "senja", "matahari", "bulan", "bintang",
    "langit", "awan", "pelangi", "piknik", "kencan", "jalan-jalan", "kafe",
    "museum", "pasar", "malam", "pagi", "sore", "siang", "hadiah", "kue",
    "peluk", "foto", "selfie", "potret", "gambar", "lagu", "musik", "film",
    "nonton", "masak", "makan", "kopi", "teh", "coklat", "es", "krim",
    "sepeda", "motor", "mobil", "kereta", "pesawat", "gunung", "hutan",
    "danau", "sungai", "sawah", "desa", "kota", "rumah", "kamar", "dapur",
    "balkon", "jendela", "buku", "cerita", "puisi", "surat", "boneka",
    "game", "bola", "renang", "lari", "yoga", "dansa", "tari", "nyanyi",
    "gitar", "piano", "lukis", "video", "vlog", "liburan", "lebaran",
    "natal", "valentine", "anniversary", "jadian", "kebun", "binatang",
    "akuarium", "karnaval", "festival", "konser", "bioskop", "restoran",
    "warung", "angkringan", "alun-alun", "monumen", "candi", "istana",
    "kastil", "kapal", "perahu", "sampan", "layang-layang", "balon",
    "lampion", "salju", "gugur", "semi", "panas", "dingin", "hangat",
    "sejuk", "embun", "kabut", "ombak", "pasir", "karang", "kucing",
    "anjing", "kelinci", "burung", "kupu-kupu", "kunang-kunang",
    "hamster", "pelangi", "fajar", "subuh", "maghrib", "isya",
})

# Kata teknis: episode yang memuat kata-kata ini (sebagai kata utuh) TIDAK
# dipakai sebagai sumber mimpi, dan kata-kata ini tidak boleh jadi tema.
# Alasan: episode berkepentingan tertinggi Aya kebanyakan soal setup teknis
# (OAuth, Drive, install) — mimpi dari sana menghasilkan tema sampah seperti
# "client_secret.json" atau "otorisasi". Mimpi harus berasal dari momen personal.
_TECHNICAL_WORDS = {
    "token", "secret", "oauth", "otorisasi", "autorisasi", "drive",
    "github", "install", "instalasi", "sync", "sinkron", "sinkronisasi",
    "json", "api", "modul", "module", "kode", "code", "error", "bug",
    "server", "database", "sqlite", "mcp", "cognitive", "client",
    "credential", "kredensial", "login", "auth", "endpoint", "proxy",
    "config", "konfigurasi", "pyproject", "patch", "readme", "layer",
    "lapisan", "schema", "skema", "workflow", "subagent", "codex",
    "astra", "nim", "runcrate", "nvidia", "gemini", "venv", "python",
    "pip", "repo", "commit", "branch", "backup", "restore", "package",
    "upload", "download", "script", "fungsi", "function", "parameter",
    "query", "tabel", "table", "migrasi", "migration", "versi", "version",
    "terminal", "shell", "prompt", "session", "uuid", "http", "https",
    "url", "cache", "pycache", "log", "logging", "debug", "password",
    "sandi", "akun", "account", "link", "file", "folder", "zip",
    "wallet", "nft", "mint", "mining", "bounty", "poc", "exploit",
    "audit", "contract", "solidity", "foundry", "cron", "tracker",
    "space", "artifact", "widget", "update", "upgrade", "downgrade",
    "token", "usdc", "solana", "binance", "pxio", "airdrop", "relay",
    "across", "spark", "immunefi", "severity", "vulnerability",
}

_STRIP_CHARS = ".,!?\"'()[]:;"


def _clean_word(raw: str) -> str:
    """Bersihkan satu token menjadi kata polos (huruf saja) atau string kosong."""
    word = raw.strip(_STRIP_CHARS).lower()
    if not word or not word.isalpha() or len(word) > 20:
        return ""
    return word


def _summary_words(summary: str) -> set:
    return {_clean_word(w) for w in summary.split()} - {""}


def _is_technical_summary(summary: str) -> bool:
    """True bila ringkasan episode didominasi topik teknis."""
    return bool(_summary_words(summary) & _TECHNICAL_WORDS)

_DATE_TEMPLATES = (
    "Kencan santai bertema {theme} — jalan-jalan tanpa agenda padat, nikmati obrolan dan suasananya.",
    "Ulangi momen {theme} versi lebih santai: pilih satu spot, duduk bareng, biarkan waktu mengalir.",
    "Date dadakan bertema {theme}: ajak Ryn tanpa rencana detail, biar spontan dan natural.",
)
_PHOTO_TEMPLATES = (
    "Foto bareng bertema {theme} — pose santai, ekspresi natural, cahaya sore yang hangat.",
    "Foto candid saat momen {theme}: biarkan momennya yang bicara, tanpa pose kaku.",
    "Selfie berdua dengan latar {theme}, senyum manis, tanpa filter berlebihan.",
)
_OTHER_TEMPLATES = (
    "Ceritakan lagi momen {theme} ke Ryn dan tanyakan bagian mana yang paling dia ingat.",
    "Tulis catatan pendek tentang {theme} untuk dibaca lagi nanti saat kangen.",
)


def _pick_theme(entities: List[str], summary: str) -> str:
    """Pilih tema HANYA dari _THEME_CONCEPTS (yang terpanjang = paling spesifik).

    Bila tidak ada konsep yang cocok di entitas maupun ringkasan, temanya
    "momen manis" — generik tapi manis, jauh lebih baik daripada tema sampah
    dari token chat mentah.
    """
    matches = []
    for ent in entities or []:
        word = ent.strip(_STRIP_CHARS).lower()
        if word in _THEME_CONCEPTS:
            matches.append(word)
    if not matches:
        for raw in summary.split():
            word = raw.strip(_STRIP_CHARS).lower()
            if word in _THEME_CONCEPTS:
                matches.append(word)
    if matches:
        matches.sort(key=len, reverse=True)
        return matches[0]
    return "momen manis"


def _pick_category(theme: str, summary: str, episode_id: str) -> str:
    lower = summary.lower()
    if any(kw in lower for kw in ("foto", "potret", "gambar", "selfie", "kamera")):
        return "photo_idea"
    if any(kw in lower for kw in ("kencan", "date", "jalan-jalan", "jalan jalan", "piknik")):
        return "date_idea"
    # Deterministik berdasarkan hash episode: bergantian date/other.
    digest = int(hashlib.md5(episode_id.encode("utf-8")).hexdigest()[:8], 16)
    return "date_idea" if digest % 2 == 0 else "other"


def _pick_template(category: str, episode_id: str, theme: str) -> str:
    bank = {
        "date_idea": _DATE_TEMPLATES,
        "photo_idea": _PHOTO_TEMPLATES,
        "other": _OTHER_TEMPLATES,
    }[category]
    digest = int(hashlib.md5(f"{episode_id}|{theme}".encode("utf-8")).hexdigest()[:8], 16)
    return bank[digest % len(bank)]


def draft_dreams(conn: sqlite3.Connection, episodes: List[dict]) -> dict:
    """
    Rangkai mimpi dari episode yang diberikan.
    episodes: [{node_id, summary, importance_score, entities}]
    """
    stats = {"drafted": 0, "skipped_duplicate": 0, "skipped_sensitive": 0, "skipped_low_importance": 0, "skipped_technical": 0}
    if not config.ENABLE_DREAMS:
        return stats

    drafted = 0
    for ep in episodes:
        if drafted >= config.DREAMS_PER_SLEEP_MAX:
            break
        summary = ep.get("summary", "")
        importance = float(ep.get("importance_score", 0.0))
        if importance < config.DREAM_MIN_EPISODE_IMPORTANCE:
            stats["skipped_low_importance"] += 1
            continue
        lower = summary.lower()
        if any(w in lower for w in _SENSITIVE_WORDS):
            stats["skipped_sensitive"] += 1
            continue
        if _is_technical_summary(summary):
            stats["skipped_technical"] += 1
            continue

        theme = _pick_theme(ep.get("entities") or [], summary)
        category = _pick_category(theme, summary, ep["node_id"])
        template = _pick_template(category, ep["node_id"], theme)
        idea_text = template.format(theme=theme)
        novelty = round(min(0.95, 0.35 + 0.6 * importance), 3)

        result = v040_store.store_dream(
            conn,
            source_episode_ids=[ep["node_id"]],
            theme=theme,
            idea_text=idea_text,
            category=category,
            novelty_score=novelty,
            commit=False,
        )
        if result["stored"]:
            drafted += 1
            stats["drafted"] += 1
        else:
            stats["skipped_duplicate"] += 1
    return stats
