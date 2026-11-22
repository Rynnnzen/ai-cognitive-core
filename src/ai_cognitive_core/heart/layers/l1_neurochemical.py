import math

from datetime import datetime, timedelta, timezone
from typing import Optional


def current_local_hour(tz_offset_hours: Optional[int] = None) -> int:
    offset = int(getattr(config, "CIRCADIAN_TZ_OFFSET_HOURS", 7)) if tz_offset_hours is None else int(tz_offset_hours)
    return (datetime.now(timezone.utc) + timedelta(hours=offset)).hour


def get_circadian_phase(local_hour: int) -> str:
    ln_start = int(getattr(config, "CIRCADIAN_LATE_NIGHT_START", 23))
    ln_end = int(getattr(config, "CIRCADIAN_LATE_NIGHT_END", 5))
    m_start = int(getattr(config, "CIRCADIAN_MORNING_START", 6))
    m_end = int(getattr(config, "CIRCADIAN_MORNING_END", 11))
    is_late = (local_hour >= ln_start or local_hour < ln_end) if ln_start > ln_end else (ln_start <= local_hour < ln_end)
    if is_late:
        return "late_night"
    if m_start <= local_hour < m_end:
        return "morning"
    if 11 <= local_hour < 18:
        return "daytime"
    return "evening"

from ai_cognitive_core import config
from ai_cognitive_core.schemas import NeuroState, StimulusAppraisal

# Konstanta peluruhan spesifik per hormon (detik^-1)
DECAY_RATES = {
    "energy": 1.0 / 7200.0,         # Mode aktif/idle biasa: paruh pulih ~2 jam
    "cortisol": 1.0 / 3600.0,       # Stres meluruh ~1 jam
    "oxytocin": 1.0 / 10800.0,      # Ikatan bertahan ~3 jam
    "dopamine": 1.0 / 1800.0,       # Antusiasme ~30 menit
    "serotonin": 1.0 / 14400.0,     # Kestabilan mood ~4 jam
    "noradrenaline": 1.0 / 600.0,   # Kejut/fokus ~10 menit
}

# Saat sleep/rest mode aktif, energi pulih ~3x lebih cepat (tau = 40 menit / 2400 detik)
SLEEP_ENERGY_RECOVERY_TAU = 2400.0
SLEEP_TARGET_ENERGY = 0.92

BASELINES = NeuroState()


def apply_time_decay(
    neuro: NeuroState,
    delta_seconds: float,
    is_resting: bool = False,
    local_hour: Optional[int] = None,
) -> NeuroState:
    if delta_seconds <= 0:
        return neuro
    data = neuro.model_dump()
    base = BASELINES.model_dump()

    for k, val in data.items():
        if k == "energy":
            if is_resting:
                # Recharging kurva eksponensial sesuai durasi tidur nyata
                tau = SLEEP_ENERGY_RECOVERY_TAU
                if local_hour is not None and getattr(config, "ENABLE_CIRCADIAN_RHYTHM", True):
                    if get_circadian_phase(local_hour) == "morning":
                        tau = tau / float(getattr(config, "CIRCADIAN_MORNING_RECHARGE_BONUS", 1.15))
                decay = math.exp(-delta_seconds / tau)
                target = max(SLEEP_TARGET_ENERGY, val)
                data["energy"] = round(min(1.0, target - (target - val) * decay), 4)
            else:
                # Pemulihan pasif saat idle biasa (hanya jika jeda > 60 detik)
                if delta_seconds > 60.0 and val < base["energy"]:
                    decay = math.exp(-DECAY_RATES["energy"] * delta_seconds)
                    data["energy"] = round(base["energy"] + (val - base["energy"]) * decay, 4)
        else:
            lam = DECAY_RATES[k]
            # Saat sedang tidur/istirahat, kortisol & noradrenalin luruh 2x lebih cepat
            effective_lam = lam * 2.0 if (is_resting and k in {"cortisol", "noradrenaline"}) else lam
            decay = math.exp(-effective_lam * delta_seconds)
            data[k] = round(base[k] + (val - base[k]) * decay, 4)

    return NeuroState(**data)


def update_neurochemistry(
    neuro: NeuroState,
    appraisal: StimulusAppraisal,
    drain_energy: bool = True,
    local_hour: Optional[int] = None,
) -> NeuroState:
    # Social buffering: Oksitosin meredam lonjakan kortisol
    social_buffer = max(0.35, 1.0 - 0.55 * neuro.oxytocin)
    fatigue_sens = 1.0 + max(0.0, 0.5 - neuro.energy) * 0.8

    stress_impulse = max(0.0, -appraisal.goal_conduciveness) * (1.0 - 0.5 * appraisal.coping_potential)
    reward_impulse = max(0.0, appraisal.goal_conduciveness) + 0.3 * max(0.0, appraisal.novelty)

    # Homeostatic damping per turn (mencegah hormon mentok permanen di 1.0)
    base = BASELINES
    damping = 0.06

    raw_cort = neuro.cortisol + 0.22 * stress_impulse * social_buffer * fatigue_sens - 0.08 * reward_impulse
    cortisol = min(1.0, max(0.0, raw_cort + damping * (base.cortisol - raw_cort)))

    oxy_delta = 0.10 if ("safety" in appraisal.fulfilled_needs or appraisal.goal_conduciveness > 0.3) else -0.05 * stress_impulse
    raw_oxy = neuro.oxytocin + oxy_delta
    oxytocin = min(1.0, max(0.0, raw_oxy + damping * (base.oxytocin - raw_oxy)))

    raw_dop = neuro.dopamine + 0.18 * reward_impulse - 0.12 * stress_impulse
    dopamine = min(1.0, max(0.0, raw_dop + damping * (base.dopamine - raw_dop)))

    raw_ser = neuro.serotonin + 0.09 * appraisal.norm_compatibility - 0.12 * stress_impulse
    serotonin = min(1.0, max(0.0, raw_ser + damping * (base.serotonin - raw_ser)))

    raw_nor = neuro.noradrenaline + 0.22 * abs(appraisal.novelty) + 0.15 * stress_impulse
    noradrenaline = min(1.0, max(0.0, raw_nor + 0.10 * (base.noradrenaline - raw_nor)))

    if drain_energy:
        # Kuras energi proporsional dengan intensitas emosi & stres (hanya 1x per turn).
        # v0.4.0 fase tes: koefisien dasar 0.012 -> 0.010 (lihat config.py);
        # skala noradrenaline/cortisol & lantai 0.05 tidak berubah.
        drain = config.ENERGY_BASE_DRAIN * (
            1.0 + config.ENERGY_NORADRENALINE_COEF * noradrenaline
            + config.ENERGY_CORTISOL_COEF * cortisol
        )
        if local_hour is not None and getattr(config, "ENABLE_CIRCADIAN_RHYTHM", True):
            if get_circadian_phase(local_hour) == "late_night":
                drain *= float(getattr(config, "CIRCADIAN_LATE_NIGHT_DRAIN_MULT", 1.30))
        energy = min(1.0, max(config.ENERGY_FLOOR, neuro.energy - drain))
    else:
        energy = neuro.energy

    return NeuroState(
        energy=round(energy, 4),
        cortisol=round(cortisol, 4),
        oxytocin=round(oxytocin, 4),
        dopamine=round(dopamine, 4),
        serotonin=round(serotonin, 4),
        noradrenaline=round(noradrenaline, 4),
    )
