from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app.api.tracks import get_track_service
from app.config import Settings
from app.main import app
from app.services.track_service import TrackService


@pytest.fixture()
def test_settings(tmp_path):
    return Settings(
        uploads_dir=tmp_path / "uploads",
        analysis_output_dir=tmp_path / "analysis_output",
    )


@pytest.fixture()
def client(test_settings):
    def override_track_service() -> TrackService:
        return TrackService(test_settings)

    app.dependency_overrides[get_track_service] = override_track_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def synthetic_wav_bytes() -> bytes:
    sample_rate = 22_050
    duration_seconds = 4.0
    time = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)

    tone = 0.35 * np.sin(2 * np.pi * 440 * time)
    pulse = ((time % 0.5) < 0.04).astype(float) * 0.35
    audio = np.clip(tone + pulse, -1.0, 1.0)

    buffer = BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV")
    return buffer.getvalue()
