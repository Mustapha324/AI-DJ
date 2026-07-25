from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


CueType = Literal["mix_in", "mix_out", "drop", "breakdown"]
TransitionStyle = Literal["long_eq_blend", "bass_swap", "echo_cut", "drop_swap", "quick_cut"]


class SongCue(BaseModel):
    cue_type: CueType
    time_seconds: float = Field(..., ge=0)
    confidence: float = Field(..., ge=0, le=1)
    phrase_bar: int | None = Field(default=None, ge=1)
    energy: float = Field(..., ge=0, le=1)
    notes: str


class RecommendedTransition(BaseModel):
    target_track_id: str
    target_title: str
    target_file_name: str
    compatibility_score: float = Field(..., ge=0, le=1)
    suggested_style: TransitionStyle
    source_cue_seconds: float = Field(..., ge=0)
    target_cue_seconds: float = Field(..., ge=0)
    expected_sound: str
    reason: str


class ExternalResearchNote(BaseModel):
    source_name: str
    source_url: str
    note: str


class MusicSourceRecommendation(BaseModel):
    name: str
    url: str
    genres: list[str]
    license_note: str
    import_note: str


class SongPlayWindow(BaseModel):
    start_seconds: float = Field(..., ge=0)
    peak_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., ge=0)
    play_seconds: float = Field(..., ge=0)
    reason: str


class SongResearchRecord(BaseModel):
    track_id: str
    title: str
    file_name: str
    bpm: float | None = None
    key: str
    energy: float = Field(..., ge=0)
    likely_genres: list[str]
    play_window: SongPlayWindow
    mix_in_cues: list[SongCue]
    mix_out_cues: list[SongCue]
    recommended_transitions: list[RecommendedTransition]
    external_notes: list[ExternalResearchNote]
    created_at: datetime
    updated_at: datetime
