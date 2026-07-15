from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReferenceMixFeature(BaseModel):
    file_name: str
    duration_seconds: float = Field(..., ge=0)
    estimated_bpm: float | None = Field(default=None, ge=0)
    beat_count: int = Field(..., ge=0)
    phrase_seconds: float = Field(..., ge=0)
    average_energy: float = Field(..., ge=0)
    energy_change_rate: float = Field(..., ge=0)
    spectral_motion_rate: float = Field(default=0.0, ge=0)
    dynamic_range: float = Field(default=0.0, ge=0)
    phrase_boundary_strength: float = Field(default=0.0, ge=0, le=1)
    likely_transition_count: int = Field(..., ge=0)
    average_transition_spacing_seconds: float | None = Field(default=None, ge=0)


class DJStyleProfile(BaseModel):
    profile_id: str
    name: str
    reference_count: int = Field(..., ge=0)
    reference_files: list[str]
    default_transition_bars: int = Field(..., ge=1, le=32)
    phrase_bars: int = Field(..., ge=1, le=16)
    max_play_seconds_per_track: float = Field(..., ge=15, le=1800)
    transition_duration_seconds: float = Field(..., ge=2, le=60)
    sfx_density: float = Field(..., ge=0, le=1)
    effect_intensity: float = Field(default=0.5, ge=0, le=1)
    transition_effects: list[str] = Field(default_factory=lambda: ["filter_sweep", "echo_tail", "impact"])
    transition_start_strategy: str = "phrase_boundary_low_energy"
    cue_point_sensitivity: float = Field(default=0.6, ge=0, le=1)
    energy_smoothing: float = Field(..., ge=0, le=1)
    beat_alignment_strength: float = Field(..., ge=0, le=1)
    features: list[ReferenceMixFeature]
    created_at: datetime
    updated_at: datetime


class StyleProfileSummary(BaseModel):
    profile_id: str
    name: str
    reference_count: int
    default_transition_bars: int
    max_play_seconds_per_track: float
    transition_duration_seconds: float
    sfx_density: float
    effect_intensity: float = 0.5
    transition_effects: list[str] = Field(default_factory=list)
    transition_start_strategy: str = "phrase_boundary_low_energy"
    updated_at: datetime
