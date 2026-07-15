from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np

from app.analyzer.energy_analyzer import normalize_energy_values
from app.analyzer.key_detector import PITCH_CLASSES, estimate_key
from app.analyzer.track_analyzer import TrackAnalyzer
from app.config import Settings
from app.models.track import BeatInfo, KeyEstimate, TrackAnalysis
from app.services.track_service import TrackService


def test_analysis_json_serialization(tmp_path):
    service = TrackService(
        Settings(
            uploads_dir=tmp_path / "uploads",
            analysis_output_dir=tmp_path / "analysis_output",
        )
    )
    analysis = TrackAnalysis(
        track_id="a" * 32,
        file_name="example.wav",
        title="example",
        duration_seconds=1.0,
        sample_rate=22_050,
        estimated_bpm=120.0,
        beats=BeatInfo(tempo_bpm=120.0, beat_timestamps=[0.1, 0.6], beat_count=2),
        key=KeyEstimate(root="A", mode="minor", display_name="A minor", confidence=0.72),
        overall_rms_energy=0.2,
        energy_curve=[],
        estimated_loudness_db=-13.9,
        zero_crossing_rate=0.04,
        spectral_centroid=1200.0,
        chroma_features={"A": 1.0},
    )

    saved_path = service.save_analysis(analysis)
    saved_data = json.loads(saved_path.read_text(encoding="utf-8"))

    assert saved_data["track_id"] == "a" * 32
    assert TrackAnalysis.model_validate(saved_data).title == "example"


def test_energy_normalization():
    assert normalize_energy_values([2.0, 4.0, 6.0]) == [0.0, 0.5, 1.0]
    assert normalize_energy_values([3.0, 3.0]) == [1.0, 1.0]
    assert normalize_energy_values([0.0, 0.0]) == [0.0, 0.0]


def test_key_estimation_output_format():
    sample_rate = 22_050
    duration_seconds = 2.0
    time = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    audio = 0.5 * np.sin(2 * np.pi * 440 * time)

    key, chroma_features = estimate_key(audio, sample_rate)

    assert key.root in PITCH_CLASSES
    assert key.mode in {"major", "minor"}
    assert key.display_name == f"{key.root} {key.mode}"
    assert 0 <= key.confidence <= 1
    assert set(chroma_features) == set(PITCH_CLASSES)


def test_optional_decoder_metadata_warning_is_nonfatal(monkeypatch):
    sample_rate = 22_050
    duration_seconds = 2.0
    time = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    audio = 0.5 * np.sin(2 * np.pi * 440 * time)

    def fake_load(path, sr=None, mono=True):
        warnings.warn("No comment text / valid description?", UserWarning)
        return audio, sample_rate

    monkeypatch.setattr("app.analyzer.track_analyzer.librosa.load", fake_load)

    analysis = TrackAnalyzer().analyze(Path("metadata-warning.mp3"), "b" * 32, "metadata-warning.mp3")

    assert analysis.track_id == "b" * 32
    assert analysis.title == "metadata warning"
