from __future__ import annotations
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SerializableModel:
    def model_dump(self) -> Dict[str, Any]:
        def _conv(obj: Any) -> Any:
            if isinstance(obj, Enum):
                return obj.value
            if isinstance(obj, dict):
                return {k: _conv(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_conv(v) for v in obj]
            return obj
        return _conv(asdict(self))

    def model_dump_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=indent)


class AttachmentStyle(str, Enum):
    SECURE = "Secure"
    ANXIOUS = "Anxious"
    AVOIDANT = "Avoidant"


class DefenseMechanism(str, Enum):
    NONE = "None"
    HUMOR = "Humor"
    SUPPRESSION = "Suppression"
    DETACHED_PROTECTOR = "DetachedProtector"


@dataclass
class NeuroState(SerializableModel):
    energy: float = 0.85
    cortisol: float = 0.20
    oxytocin: float = 0.50
    dopamine: float = 0.50
    serotonin: float = 0.60
    noradrenaline: float = 0.30


@dataclass
class PrimaryAffectState(SerializableModel):
    SEEKING: float = 0.50
    CARE: float = 0.40
    PLAY: float = 0.30
    LUST: float = 0.10
    FEAR: float = 0.10
    RAGE: float = 0.05
    PANIC_GRIEF: float = 0.10


@dataclass
class PADVector(SerializableModel):
    P: float = 0.20
    A: float = 0.10
    D: float = 0.15

    def clamp(self) -> "PADVector":
        return PADVector(
            P=round(max(-1.0, min(1.0, float(self.P))), 4),
            A=round(max(-1.0, min(1.0, float(self.A))), 4),
            D=round(max(-1.0, min(1.0, float(self.D))), 4),
        )

    def octant_label(self) -> str:
        if self.P >= 0 and self.A >= 0 and self.D >= 0:
            return "Exuberant"
        if self.P >= 0 and self.A >= 0 and self.D < 0:
            return "Dependent"
        if self.P >= 0 and self.A < 0 and self.D >= 0:
            return "Relaxed"
        if self.P >= 0 and self.A < 0 and self.D < 0:
            return "Docile"
        if self.P < 0 and self.A >= 0 and self.D >= 0:
            return "Hostile"
        if self.P < 0 and self.A >= 0 and self.D < 0:
            return "Anxious"
        if self.P < 0 and self.A < 0 and self.D >= 0:
            return "Disdainful"
        return "Bored/Depressed"


@dataclass
class CoreNeedsState(SerializableModel):
    safety: float = 0.75
    autonomy: float = 0.75
    expression: float = 0.70
    playfulness: float = 0.65
    boundaries: float = 0.80
    coherence: float = 0.80
    fairness: float = 0.75


@dataclass
class ConscienceState(SerializableModel):
    guilt: float = 0.0
    shame: float = 0.0
    lubb_triggered: bool = False
    lubb_reason: Optional[str] = None


@dataclass
class StimulusAppraisal(SerializableModel):
    novelty: float = 0.0
    goal_conduciveness: float = 0.0
    coping_potential: float = 0.5
    norm_compatibility: float = 0.0
    causal_agency: str = "user"
    threatened_needs: List[str] = field(default_factory=list)
    fulfilled_needs: List[str] = field(default_factory=list)
    user_defense_detected: Optional[str] = None
    texting_style_detected: str = "normal"


@dataclass
class HeartState(SerializableModel):
    last_updated_utc: str = field(default_factory=utc_now_iso)
    is_resting: bool = False
    rest_started_utc: Optional[str] = None
    neuro: NeuroState = field(default_factory=NeuroState)
    primary_affects: PrimaryAffectState = field(default_factory=PrimaryAffectState)
    pad_current: PADVector = field(default_factory=lambda: PADVector(P=0.10, A=0.15, D=0.35))
    pad_baseline: PADVector = field(default_factory=lambda: PADVector(P=0.10, A=0.15, D=0.35))
    coactivated_affect: Optional[str] = None
    emotional_inertia_pi1: float = 0.45
    consecutive_negative_octant_turns: int = 0
    attachment_style: AttachmentStyle = AttachmentStyle.AVOIDANT
    core_needs: CoreNeedsState = field(
        default_factory=lambda: CoreNeedsState(
            safety=0.75,
            autonomy=0.85,
            expression=0.65,
            playfulness=0.60,
            boundaries=0.85,
            coherence=0.85,
            fairness=0.80,
        )
    )
    conscience: ConscienceState = field(default_factory=ConscienceState)
    active_defense: DefenseMechanism = DefenseMechanism.NONE

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HeartState":
        return cls(
            last_updated_utc=data.get("last_updated_utc", utc_now_iso()),
            is_resting=bool(data.get("is_resting", False)),
            rest_started_utc=data.get("rest_started_utc"),
            neuro=NeuroState(**data.get("neuro", {})),
            primary_affects=PrimaryAffectState(**data.get("primary_affects", {})),
            pad_current=PADVector(**data.get("pad_current", {"P": 0.10, "A": 0.15, "D": 0.35})),
            pad_baseline=PADVector(**data.get("pad_baseline", {"P": 0.10, "A": 0.15, "D": 0.35})),
            coactivated_affect=data.get("coactivated_affect"),
            emotional_inertia_pi1=float(data.get("emotional_inertia_pi1", 0.45)),
            consecutive_negative_octant_turns=int(data.get("consecutive_negative_octant_turns", 0)),
            attachment_style=AttachmentStyle(data.get("attachment_style", "Avoidant")),
            core_needs=CoreNeedsState(**data.get("core_needs", {})),
            conscience=ConscienceState(**data.get("conscience", {})),
            active_defense=DefenseMechanism(data.get("active_defense", "None")),
        )


@dataclass
class EmotionalDirective(SerializableModel):
    mood_octant: str
    pad_vector: PADVector
    dominant_affect: str
    secondary_coactivated_affect: Optional[str] = None
    active_defense: DefenseMechanism = DefenseMechanism.NONE
    psi_resolution_level: str = "medium_balanced"
    bubble_style: str = "normal_1_to_2_bubbles"
    recommended_bubbles: int = 2
    max_words_per_bubble: int = 25
    conscience_override: Optional[str] = None
    tone_instruction: str = ""


@dataclass
class CoalitionCandidate(SerializableModel):
    chunk_id: str
    source: str
    content: str
    base_salience: float
    affective_boost: float = 0.0

    @property
    def total_salience(self) -> float:
        return min(1.0, self.base_salience + 0.4 * self.affective_boost)


@dataclass
class ConsciousBroadcast(SerializableModel):
    broadcast_id: str
    timestamp_utc: str = field(default_factory=utc_now_iso)
    network_mode: str = "CEN"
    winning_chunks: List[CoalitionCandidate] = field(default_factory=list)
    inner_monologue: str = ""
    metacognitive_precision_v: float = 1.0
    inertia_interrupted: bool = False


@dataclass
class SomaticTag(SerializableModel):
    pad_at_encoding: PADVector
    arousal_weight: float = 0.5


@dataclass
class WorkingChunk(SerializableModel):
    chunk_id: str
    role: str
    content: str
    timestamp_utc: str = field(default_factory=utc_now_iso)
    access_count: int = 1


@dataclass
class EpisodicNode(SerializableModel):
    node_id: str
    summary: str
    somatic_tag: SomaticTag
    timestamp_utc: str = field(default_factory=utc_now_iso)
    entities: List[str] = field(default_factory=list)
    stability_status: str = "STABLE"
    importance_score: float = 0.5
    access_count: int = 1
    next_node_id: Optional[str] = None


@dataclass
class SemanticFact(SerializableModel):
    fact_id: str
    category: str
    subject: str
    predicate: str
    object_val: str
    confidence: float = 0.8
    updated_utc: str = field(default_factory=utc_now_iso)


@dataclass
class ProceduralHabit(SerializableModel):
    habit_id: str
    trigger_pattern: str
    action_template: str
    success_count: int = 1
