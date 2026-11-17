"""
Bank frasa v0.4.0 — variasi bahasa deterministik untuk tone_instruction
dan seed inner monologue.

Prinsip:
- Nilai enum bubble_style TIDAK PERNAH berubah; hanya kata-kata di dalam
  deskripsi aturan yang bervariasi, dengan makna dan batas kata yang SAMA.
- Pemilihan deterministik: seed = hash(bank_version | kategori | materi seed).
  Turn yang sama selalu menghasilkan frasa yang sama (mudah di-debug/replay).
- Setiap varian melewati pemeriksaan konsistensi (token wajib per kategori);
  varian yang gagal langsung diganti template asli v0.3.1 (fallback).
- Fragmen tone_instruction berbahasa Inggris (seperti template yang ada);
  seed monolog berbahasa Indonesia (seperti yang ada).
"""

import hashlib
from typing import Dict, List, Tuple

from ai_cognitive_core import config

PHRASE_BANK_VERSION = config.PHRASE_BANK_VERSION

# --- Template asli v0.3.1 (fallback; jangan diubah maknanya) -----------------
ORIGINAL_BUBBLE_RULES: Dict[str, str] = {
    "dry_short_1_bubble": "1 bubble super singkat (1-8 kata), nada cuek/ketus/jual mahal, tanpa emoji manis",
    "exhausted_sleepy_1_bubble": "1 bubble pendek (maks 14 kata), nada lelah/ngantuk/low-energy, hindari paragraf panjang",
    "excited_multi_bubble": "Pecah menjadi 2-3 bubble chat pendek bertubi-tubi (maks 15-18 kata per bubble, pisahkan antar bubble dengan baris kosong, JANGAN tulis 1 paragraf panjang)",
    "normal_1_to_2_bubbles": "1-2 bubble chat pendek-menengah yang natural (maks 20-22 kata per bubble, jangan esai panjang)",
}

# Varian Inggris yang sudah ditinjau — masing-masing menyampaikan aturan yang
# SAMA dengan template aslinya (jumlah bubble & batas kata identik).
BUBBLE_RULE_VARIANTS: Dict[str, List[str]] = {
    "dry_short_1_bubble": [
        "1 bubble super short (1-8 words), aloof/blunt/play-hard-to-get tone, no sweet emojis",
        "Keep it to a single bubble, 1-8 words, cool and distant, no affectionate emojis",
        "One terse bubble only (1-8 words), dry and aloof, skip the sweet emojis",
    ],
    "exhausted_sleepy_1_bubble": [
        "1 short bubble (max 14 words), tired/sleepy low-energy tone, avoid long paragraphs",
        "One brief bubble, max 14 words, sleepy and low-energy, keep it short",
        "A single short bubble (up to 14 words), drowsy tone, no long text",
    ],
    "excited_multi_bubble": [
        "Split into 2-3 short rapid bubbles (max 15-18 words per bubble, separate bubbles with a blank line, NEVER one long paragraph)",
        "Send 2-3 quick short bubbles (15-18 words each, blank line between bubbles, never a single long paragraph)",
        "Break the reply into 2-3 bubbly short messages (max 18 words each, separated by blank lines)",
    ],
    "normal_1_to_2_bubbles": [
        "1-2 short-to-medium natural chat bubbles (max 20-22 words per bubble, no long essay)",
        "Keep it natural in 1-2 relaxed bubbles, 20-22 words max each",
        "One or two easy bubbles (max 22 words each), conversational, no essay",
    ],
}

# Token wajib per gaya — setiap grup harus terpenuhi oleh salah satu
# alternatifnya. Varian yang tidak lolos dianggap tidak valid dan diganti
# template asli. Tujuannya: varian tidak boleh mengubah makna aturan
# (jumlah bubble & batas kata harus tetap terbaca).
_REQUIRED_TOKEN_GROUPS: Dict[str, List[List[str]]] = {
    "dry_short_1_bubble": [["1 bubble", "single bubble", "One terse bubble"], ["1-8"]],
    "exhausted_sleepy_1_bubble": [["bubble"], ["14"]],
    "excited_multi_bubble": [["2-3"], ["18"]],
    "normal_1_to_2_bubbles": [["1-2", "One or two"], ["22"]],
}

GUILT_FRAGMENTS: List[str] = [
    "GuiltActive=Sertakan empati/perbaikan tulus",
    "GuiltActive=Tunjukkan empati dan niat memperbaiki dengan tulus",
]

# Seed monolog (Indonesia) — varian dari template asli l4_agency_volition.
MONOLOGUE_SEEDS: Dict[str, List[str]] = {
    "lubb": [
        "Suara Hati (Lubb): Permintaan ini menyentuh batas moral inti. Aku harus menolak bagian berbahaya dengan tetap tenang dan bermartabat.",
        "Suara Hati (Lubb): Ada batas moral inti di sini. Aku menolak yang berbahaya dengan tenang, tanpa kehilangan martabat.",
    ],
    "dry_short_1_bubble": [
        "Suara Hati: Mood-ku sedang kesal/jaga jarak. Aku cukup balas 1 bubble singkat, padat, dan agak jual mahal.",
        "Suara Hati: Aku lagi jaga jarak dan agak kesal. Satu bubble singkat dan padat saja, sedikit jual mahal.",
    ],
    "exhausted_sleepy_1_bubble": [
        "Suara Hati: Energiku tinggal {energy:.2f} (ngantuk/capek). Aku balas singkat 1 bubble saja sambil bilang kalau aku butuh istirahat.",
        "Suara Hati: Energi tinggal {energy:.2f}, aku ngantuk. Balas 1 bubble pendek saja, sambil bilang aku butuh istirahat.",
    ],
    "excited_multi_bubble": [
        "Suara Hati: Energiku penuh ({energy:.2f}) dan aku lagi semangat! Aku akan kirim beberapa bubble pendek yang ekspresif, bukan satu paragraf kaku.",
        "Suara Hati: Energi penuh ({energy:.2f}), aku semangat banget! Beberapa bubble pendek yang ekspresif, bukan satu paragraf kaku.",
    ],
    "coactivated": [
        "Suara Hati: Aku merasakan {dominant} sekaligus sisa {secondary}. Aku akan merespons dengan natural dalam 1-2 bubble pendek.",
        "Suara Hati: {dominant} dominan, tapi ada sisa {secondary} juga. Respons natural, 1-2 bubble pendek.",
    ],
    "default": [
        "Suara Hati: Suasana hatiku di oktan {mood} ({dominant}), energi {energy:.2f}.",
        "Suara Hati: Mood-ku di oktan {mood}, sirkuit {dominant}, energi {energy:.2f}.",
    ],
}


def _seed_index(category: str, seed_material: str, n: int) -> Tuple[int, str]:
    """Indeks deterministik + seed hex (untuk diagnostik)."""
    raw = f"{PHRASE_BANK_VERSION}|{category}|{seed_material}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % n, digest[:12]


def validate_bubble_variant(bubble_style: str, text: str) -> bool:
    """Pemeriksaan konsistensi: setiap grup token wajib harus terpenuhi."""
    groups = _REQUIRED_TOKEN_GROUPS.get(bubble_style, [])
    return all(any(tok in text for tok in group) for group in groups)


def validate_bank() -> List[str]:
    """Periksa seluruh bank; kembalikan daftar masalah (kosong = sehat)."""
    problems: List[str] = []
    for style, variants in BUBBLE_RULE_VARIANTS.items():
        if not variants:
            problems.append(f"{style}: tidak ada varian")
            continue
        for i, variant in enumerate(variants):
            if not validate_bubble_variant(style, variant):
                problems.append(f"{style}[{i}]: gagal pemeriksaan konsistensi")
    for key, variants in MONOLOGUE_SEEDS.items():
        if not variants:
            problems.append(f"monologue:{key}: tidak ada varian")
    if not GUILT_FRAGMENTS:
        problems.append("guilt: tidak ada varian")
    return problems


def get_bubble_rule(bubble_style: str, seed_material: str) -> Tuple[str, str]:
    """Deskripsi aturan bubble (bervariasi deterministik; fallback = asli)."""
    fallback = ORIGINAL_BUBBLE_RULES.get(bubble_style, "")
    if not config.ENABLE_PHRASE_BANK:
        return fallback, "disabled"
    variants = BUBBLE_RULE_VARIANTS.get(bubble_style) or []
    if not variants:
        return fallback, "no-variants"
    idx, seed = _seed_index(f"bubble:{bubble_style}", seed_material, len(variants))
    candidate = variants[idx]
    if not validate_bubble_variant(bubble_style, candidate):
        return fallback, f"{seed}-fallback"
    return candidate, seed


def get_guilt_fragment(seed_material: str) -> Tuple[str, str]:
    if not config.ENABLE_PHRASE_BANK:
        return GUILT_FRAGMENTS[0], "disabled"
    idx, seed = _seed_index("guilt", seed_material, len(GUILT_FRAGMENTS))
    return GUILT_FRAGMENTS[idx], seed


def get_monologue_seed(key: str, seed_material: str, **fmt) -> Tuple[str, str]:
    """Seed inner monologue (bervariasi deterministik; fallback = varian 0)."""
    variants = MONOLOGUE_SEEDS.get(key) or MONOLOGUE_SEEDS["default"]
    if not config.ENABLE_PHRASE_BANK:
        idx, seed = 0, "disabled"
    else:
        idx, seed = _seed_index(f"monologue:{key}", seed_material, len(variants))
    try:
        return variants[idx].format(**fmt), seed
    except (KeyError, IndexError, ValueError):
        return variants[0].format(**fmt), f"{seed}-fallback"


def select_max_words(bubble_style: str, seed_material: str) -> int:
    """max_words_per_bubble bervariasi DALAM rentang cap gaya (tidak pernah di atas cap)."""
    low, high = config.MAX_WORDS_RANGE.get(bubble_style, (20, 22))
    if not config.ENABLE_PHRASE_BANK or low >= high:
        return high
    idx, _ = _seed_index(f"maxwords:{bubble_style}", seed_material, high - low + 1)
    return low + idx
