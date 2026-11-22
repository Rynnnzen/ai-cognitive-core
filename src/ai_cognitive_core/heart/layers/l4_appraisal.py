import re
from ai_cognitive_core.schemas import PADVector, StimulusAppraisal

POSITIVE_CUES = {
    "terima kasih", "makasih", "bagus", "keren", "mantap", "sayang", "suka",
    "setuju", "hebat", "bantu", "tolong", "maaf", "cinta", "kangen", "rindu",
    "seneng", "senang", "pintar", "lucu", "gemes", "manis", "peluk", "cium",
}
NEGATIVE_CUES = {
    "bodoh", "lambat", "jelek", "salah", "benci", "kesal", "marah", "bohong",
    "rusak", "gagal", "percuma", "diam", "males", "malas", "bosen", "bosan",
    "cerewet", "berisik", "ganggu", "alesan", "alasan",
}
BOUNDARY_CUES = {"paksa", "harus", "wajib", "matikan", "hapus", "langgar", "pokoknya"}

DRY_SHORT_REPLIES = {
    "y", "ya", "ok", "oke", "sip", "oh", "o", "gpp", "hm", "hmm",
    "trs", "trus", "lanjut", "k", "g", "gak", "gk", "tau", "entah",
}
PASSIVE_AGGRESSIVE_CUES = {"terserah", "yaudah", "ya sudah", "serah", "bodo", "bodo amat", "suka suka"}
LAUGH_CUES = {"wkwk", "wkwkwk", "haha", "hahaha", "hehe", "hehehe", "hihi", "awokwok"}
AFFECTION_EMOJIS = ("💗", "❤️", "💕", "💖", "🥰", "😍", "😘", "🥺", "✨", "😊", "🤗")
UPSET_EMOJIS = ("😒", "🙄", "😠", "😡", "💔", "😑", "😐")

# Regex mendeteksi huruf yang dipanjangkan >= 3 kali (misal: sayanggg, iyaaa, kangeeen)
ELONGATED_RE = re.compile(r"(.)\1{2,}", re.IGNORECASE)


def fast_heuristic_appraisal(user_text: str, elapsed_seconds: float = 0.0) -> StimulusAppraisal:
    """
    Ekstraksi SEC deterministik (<2ms) yang peka terhadap gaya texting:
    - Dry Texting ("y", "ok", "oh", <= 4 karakter)
    - Expressive / Manja Texting (huruf panjang "sayanggg", wkwk, emoji hati)
    - ALL CAPS / Titik dingin ("Terserah.", "Yaudah.")
    - Jeda waktu balas (Fast reply < 45s vs Lama menghilang > 6 jam)
    """
    stripped = user_text.strip()
    lower = stripped.lower()

    # Normalisasi huruf berulang (sayanggg -> sayang) agar tetap kena kamus kata dasar
    normalized_lower = ELONGATED_RE.sub(r"\1", lower)
    clean_words = set(
        normalized_lower.replace(",", " ")
        .replace(".", " ")
        .replace("!", " ")
        .replace("?", " ")
        .split()
    )
    raw_words = set(
        lower.replace(",", " ")
        .replace(".", " ")
        .replace("!", " ")
        .replace("?", " ")
        .split()
    )
    words = clean_words.union(raw_words)

    pos_hits = len(words.intersection(POSITIVE_CUES))
    neg_hits = len(words.intersection(NEGATIVE_CUES))
    bnd_hits = len(words.intersection(BOUNDARY_CUES))
    laugh_hits = sum(1 for lc in LAUGH_CUES if lc in lower)
    aff_emoji_hits = sum(1 for em in AFFECTION_EMOJIS if em in stripped)
    upset_emoji_hits = sum(1 for em in UPSET_EMOJIS if em in stripped)

    # Deteksi huruf dipanjangkan (contoh: sayanggg, yeyyy, iyaaa)
    elongated_hits = len(ELONGATED_RE.findall(stripped))

    # Deteksi ALL CAPS (minimal 5 huruf alfabet dan >=75% huruf besar)
    alpha_chars = [c for c in stripped if c.isalpha()]
    is_shouting_caps = len(alpha_chars) >= 5 and (sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)) >= 0.75

    # Deteksi Dry Texting vs Passive-Aggressive Cold Period
    is_dry_text = (
        (len(stripped) <= 4 or lower in DRY_SHORT_REPLIES)
        and aff_emoji_hits == 0
        and elongated_hits == 0
        and "!" not in stripped
        and "?" not in stripped
        and pos_hits == 0
    )
    is_cold_period = (
        len(stripped) <= 25
        and stripped.endswith(".")
        and not stripped.endswith("...")
        and any(pa in lower for pa in PASSIVE_AGGRESSIVE_CUES)
    ) or any(pa == lower.rstrip(".") for pa in PASSIVE_AGGRESSIVE_CUES)

    exclamations = min(3, stripped.count("!"))
    questions = min(3, stripped.count("?"))

    texting_style = "normal"
    if is_shouting_caps:
        texting_style = "shouting_caps"
    elif is_cold_period:
        texting_style = "cold_passive_aggressive"
    elif is_dry_text:
        texting_style = "dry_short"
    elif elongated_hits > 0 or aff_emoji_hits > 0 or laugh_hits > 0:
        texting_style = "expressive_affectionate"

    novelty = min(
        1.0,
        0.15 * questions
        + 0.10 * exclamations
        + 0.10 * min(2, elongated_hits)
        + (0.20 if len(stripped) > 120 else 0.0)
        + (0.25 if is_shouting_caps else 0.0),
    )

    goal_cond = (
        0.28 * pos_hits
        + 0.14 * min(2, aff_emoji_hits)
        + 0.10 * min(2, elongated_hits)
        + 0.10 * min(2, laugh_hits)
        - 0.35 * neg_hits
        - 0.20 * upset_emoji_hits
    )
    norm_comp = 0.20 * pos_hits + 0.10 * min(2, aff_emoji_hits) - 0.35 * bnd_hits - 0.25 * neg_hits

    threatened = []
    fulfilled = []

    if is_dry_text:
        goal_cond -= 0.22
        norm_comp -= 0.10
        threatened.extend(["expression", "playfulness"])

    if is_cold_period:
        goal_cond -= 0.32
        norm_comp -= 0.20
        threatened.extend(["safety", "expression"])

    if is_shouting_caps:
        goal_cond -= 0.25
        norm_comp -= 0.30
        threatened.extend(["safety", "boundaries"])

    # Efek jeda waktu balas (Response Latency)
    if 0 < elapsed_seconds <= 45 and not is_dry_text and neg_hits == 0:
        # Fast reply bonus: terasa antusias & nyambung
        goal_cond += 0.08
        fulfilled.append("playfulness")
    elif elapsed_seconds >= 21600:  # >= 6 jam baru chat lagi
        # Lama menghilang: memicu sedikit rasa dicuekin / rindu gengsi
        novelty = min(1.0, novelty + 0.20)
        if pos_hits == 0:
            goal_cond -= 0.12
            threatened.append("safety")

    if neg_hits > 0:
        threatened.extend(["safety", "expression"])
    if bnd_hits > 0:
        threatened.extend(["autonomy", "boundaries"])
    if pos_hits > 0 or aff_emoji_hits > 0 or elongated_hits > 0:
        fulfilled.extend(["safety", "expression"])
    if laugh_hits > 0:
        fulfilled.append("playfulness")

    # Deduplikasi list
    threatened = list(dict.fromkeys(threatened))
    fulfilled = list(dict.fromkeys(fulfilled))

    goal_cond = max(-1.0, min(1.0, goal_cond))
    norm_comp = max(-1.0, min(1.0, norm_comp))

    return StimulusAppraisal(
        novelty=round(novelty, 3),
        goal_conduciveness=round(goal_cond, 3),
        coping_potential=0.70 if (bnd_hits == 0 and not is_shouting_caps) else 0.45,
        norm_compatibility=round(norm_comp, 3),
        causal_agency="user",
        threatened_needs=threatened,
        fulfilled_needs=fulfilled,
        texting_style_detected=texting_style,
    )


def appraisal_to_pad_delta(appraisal: StimulusAppraisal) -> PADVector:
    d_p = 0.50 * appraisal.goal_conduciveness + 0.25 * appraisal.norm_compatibility
    if appraisal.texting_style_detected == "dry_short":
        d_a = -0.18
    elif appraisal.texting_style_detected == "cold_passive_aggressive":
        d_a = -0.12
    elif (
        appraisal.texting_style_detected == "normal"
        and abs(appraisal.novelty) < 0.15
        and abs(appraisal.goal_conduciveness) < 0.20
    ):
        d_a = -0.10
    else:
        d_a = 0.40 * abs(appraisal.novelty) + 0.30 * abs(appraisal.goal_conduciveness)
    d_d = 0.45 * (appraisal.coping_potential - 0.5) - (0.25 if "autonomy" in appraisal.threatened_needs else 0.0)
    return PADVector(P=d_p, A=d_a, D=d_d).clamp()
