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

GenreSource = Literal["embedded", "filename", "audio_profile", "fallback", "manual", "unknown"]


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
    genre: str = "Open Format"
    genre_source: GenreSource = "unknown"
    genre_confidence: float = Field(default=0.0, ge=0, le=1)
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
    content_hash: str | None = None
    file_size_bytes: int | None = Field(default=None, ge=0)


class TrackSummary(BaseModel):
    track_id: str
    title: str
    file_name: str
    genre: str = "Open Format"
    genre_source: GenreSource = "unknown"
    genre_confidence: float = Field(default=0.0, ge=0, le=1)
    duration_seconds: float
    estimated_bpm: float | None
    key: KeyEstimate
    beat_count: int = 0
    approximate_bar_count: int = 0
    overall_rms_energy: float = 0.0


class TrackImportUrlRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    file_name: str | None = Field(default=None, max_length=160)


class TrackGenreUpdateRequest(BaseModel):
    genre: str = Field(..., min_length=1, max_length=64)


BatchTrackStatus = Literal["analyzed", "duplicate"]


class BatchTrackResult(BaseModel):
    track_id: str
    file_name: str
    status: BatchTrackStatus


class BatchTrackError(BaseModel):
    file_name: str
    error: str


class BatchAnalyzeResponse(BaseModel):
    total_files: int
    successful: int
    failed: int
    duplicates: int
    tracks: list[BatchTrackResult]
    errors: list[BatchTrackError]
    job_id: str | None = None


class CompatibilityBreakdown(BaseModel):
    tempo: float = Field(..., ge=0, le=1)
    key: float = Field(..., ge=0, le=1)
    energy: float = Field(..., ge=0, le=1)
    structure: float = Field(..., ge=0, le=1)


class TrackCompatibility(BaseModel):
    source_track_id: str
    target_track_id: str
    target_title: str
    target_file_name: str
    compatibility_score: float = Field(..., ge=0, le=1)
    score_breakdown: CompatibilityBreakdown
