from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.track import ApproximateBar, EnergyPoint, KeyEstimate


TransitionType = Literal["crossfade"]
CrossfadeCurve = Literal["equal_power", "linear"]
TransitionTechnique = Literal[
    "phrase_blend",
    "echo_fade",
    "filter_blend",
    "tempo_handoff",
    "bass_swap",
    "loop_echo_out",
    "drop_swap",
    "quick_cut",
]
MixStatus = Literal["planned", "queued", "rendering", "completed", "failed"]
OutputFormat = Literal["wav"]


class MixableTrack(BaseModel):
    track_id: str
    file_name: str
    title: str
    genre: str = "Open Format"
    duration_seconds: float = Field(..., ge=0)
    bpm: float | None = Field(default=None, ge=0)
    key: KeyEstimate
    overall_energy: float = Field(..., ge=0)
    beat_timestamps: list[float]
    approximate_bars: list[ApproximateBar]
    energy_curve: list[EnergyPoint]


class MixPlanRequest(BaseModel):
    track_ids: list[str] = Field(..., min_length=2)
    mix_name: str = Field(default="AI DJ Mix", min_length=1, max_length=120)
    transition_bars: int = Field(default=4, ge=1, le=32)
    target_duration_minutes: float | None = Field(default=None, gt=0, le=180)
    max_play_seconds_per_track: float | None = Field(default=None, ge=15, le=1800)
    auto_order: bool = True
    mix_direction: str | None = Field(default=None, max_length=240)
    use_transition_sfx: bool = True
    use_trained_style: bool = True

    @field_validator("mix_direction")
    @classmethod
    def clean_mix_direction(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class MixTrackPlacement(BaseModel):
    track_id: str
    file_name: str
    title: str
    genre: str = "Open Format"
    source_start_time: float = Field(..., ge=0)
    source_end_time: float = Field(..., ge=0)
    timeline_start_time: float = Field(..., ge=0)
    timeline_end_time: float = Field(..., ge=0)
    bpm: float | None = Field(default=None, ge=0)
    key: str


class MixTransition(BaseModel):
    source_track_id: str
    target_track_id: str
    source_transition_start: float = Field(..., ge=0)
    source_transition_end: float = Field(..., ge=0)
    target_transition_start: float = Field(..., ge=0)
    target_transition_end: float = Field(..., ge=0)
    timeline_start_time: float = Field(..., ge=0)
    timeline_end_time: float = Field(..., ge=0)
    duration_seconds: float = Field(..., ge=0)
    bpm_adjustment_percent: float
    source_tempo_adjustment_percent: float = 0.0
    gain_adjustment_db: float
    crossfade_curve: CrossfadeCurve
    transition_type: TransitionType
    technique: TransitionTechnique = "phrase_blend"
    phrase_aligned: bool = True
    outgoing_loop_beats: int = Field(default=0, ge=0, le=16)
    outgoing_loop_seconds: float = Field(default=0.0, ge=0, le=16)
    background_tail_seconds: float = Field(default=0.0, ge=0, le=20)
    bass_swap_position: float = Field(default=0.5, ge=0.15, le=0.85)
    compatibility_score: float = Field(..., ge=0, le=1)
    sfx: list[str] = Field(default_factory=list)


class MixPlan(BaseModel):
    mix_id: str
    mix_name: str
    mix_direction: str | None = None
    use_transition_sfx: bool = True
    max_play_seconds_per_track: float | None = None
    track_order: list[str]
    placements: list[MixTrackPlacement]
    transitions: list[MixTransition]
    estimated_duration_seconds: float = Field(..., ge=0)
    created_at: datetime


class RenderMixRequest(BaseModel):
    mix_id: str | None = None
    plan: MixPlan | None = None
    output_format: OutputFormat = "wav"

    @model_validator(mode="after")
    def require_mix_id_or_plan(self) -> "RenderMixRequest":
        if not self.mix_id and not self.plan:
            raise ValueError("Provide either mix_id or plan.")
        return self


class MixRecord(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    mix_id: str
    mix_name: str
    status: MixStatus
    track_order: list[str]
    transitions: list[MixTransition]
    plan: MixPlan
    output_filename: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    errors: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    job_id: str | None = None


class MixSummary(BaseModel):
    mix_id: str
    mix_name: str
    status: MixStatus
    track_order: list[str]
    output_filename: str | None = None
    duration_seconds: float | None = None
    created_at: datetime
    updated_at: datetime
