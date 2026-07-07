from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SectionType = Literal[
    "intro",
    "verse",
    "pre_chorus",
    "chorus",
    "bridge",
    "drop",
    "outro",
    "instrumental",
    "unknown",
    "high_energy",
    "low_energy",
]


class EnergyPoint(BaseModel):
    time: float = Field(..., ge=0)
    energy: float = Field(..., ge=0, le=1)


class TrackSection(BaseModel):
    section_type: SectionType
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., ge=0)
    start_beat: int | None = Field(default=None, ge=1)
    end_beat: int | None = Field(default=None, ge=1)
    energy: float = Field(..., ge=0, le=1)
    confidence: float = Field(..., ge=0, le=1)
    manually_labeled: bool = False


class ApproximateBar(BaseModel):
    bar_number: int = Field(..., ge=1)
    start_beat: int = Field(..., ge=1)
    end_beat: int = Field(..., ge=1)
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., ge=0)


class BeatInfo(BaseModel):
    tempo_bpm: float | None = Field(default=None, ge=0)
    beat_timestamps: list[float]
    beat_count: int = Field(..., ge=0)
    approximate_bars: list[ApproximateBar] = Field(default_factory=list)


class KeyEstimate(BaseModel):
    root: str
    mode: Literal["major", "minor"]
    display_name: str
    confidence: float = Field(..., ge=0, le=1)


class TrackAnalysis(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    track_id: str
    file_name: str
    title: str
    duration_seconds: float = Field(..., ge=0)
    sample_rate: int = Field(..., gt=0)
    estimated_bpm: float | None = Field(default=None, ge=0)
    beats: BeatInfo
    key: KeyEstimate
    overall_rms_energy: float = Field(..., ge=0)
    energy_curve: list[EnergyPoint]
    estimated_loudness_db: float
    zero_crossing_rate: float = Field(..., ge=0)
    spectral_centroid: float = Field(..., ge=0)
    chroma_features: dict[str, float]
    sections: list[TrackSection] = Field(default_factory=list)
    possible_high_energy_sections: list[TrackSection] = Field(default_factory=list)
    possible_low_energy_sections: list[TrackSection] = Field(default_factory=list)


class TrackSummary(BaseModel):
    track_id: str
    title: str
    file_name: str
    duration_seconds: float
    estimated_bpm: float | None
    key: KeyEstimate
