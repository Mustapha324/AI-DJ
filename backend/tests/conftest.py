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
        mixes_dir=tmp_path / "mixes",
        jobs_dir=tmp_path / "jobs",
        style_profiles_dir=tmp_path / "style_profiles",
        song_research_dir=tmp_path / "song_research",
        max_upload_size_bytes=10 * 1024 * 1024,
    )


@pytest.fixture()
def client(test_settings):
    from app.api.jobs import get_job_service
    from app.api.mixes import get_mix_storage
    from app.api.tracks import get_song_research_service
    from app.api.style_profiles import get_style_profile_service

    def override_track_service() -> TrackService:
        return TrackService(test_settings)

    def override_job_service():
        from app.services.job_service import JobService

        return JobService(test_settings)

    def override_mix_storage():
        from app.services.mix_storage import MixStorage

        return MixStorage(test_settings)

    def override_style_profile_service():
        from app.services.style_profile_service import StyleProfileService

        return StyleProfileService(test_settings)

    def override_song_research_service():
        from app.services.song_research_service import SongResearchService

        return SongResearchService(test_settings)

    app.dependency_overrides[get_track_service] = override_track_service
    app.dependency_overrides[get_job_service] = override_job_service
    app.dependency_overrides[get_mix_storage] = override_mix_storage
    app.dependency_overrides[get_style_profile_service] = override_style_profile_service
    app.dependency_overrides[get_song_research_service] = override_song_research_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def make_synthetic_wav_bytes():
    def build_audio(
        frequency: float = 440.0,
        duration_seconds: float = 4.0,
        pulse_period: float = 0.5,
    ) -> bytes:
        sample_rate = 22_050
        time = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)

        tone = 0.35 * np.sin(2 * np.pi * frequency * time)
        pulse = ((time % pulse_period) < 0.04).astype(float) * 0.35
        audio = np.clip(tone + pulse, -1.0, 1.0)

        buffer = BytesIO()
        sf.write(buffer, audio, sample_rate, format="WAV")
        return buffer.getvalue()

    return build_audio


@pytest.fixture()
def synthetic_wav_bytes(make_synthetic_wav_bytes) -> bytes:
    return make_synthetic_wav_bytes()


@pytest.fixture()
def synthetic_mp3_named_uploads(make_synthetic_wav_bytes) -> list[tuple[str, bytes, str]]:
    return [
        ("alpha.mp3", make_synthetic_wav_bytes(330.0), "audio/mpeg"),
        ("bravo.mp3", make_synthetic_wav_bytes(440.0), "audio/mpeg"),
        ("charlie.mp3", make_synthetic_wav_bytes(550.0), "audio/mpeg"),
    ]


@pytest.fixture()
def synthetic_reference_mix_bytes(make_synthetic_wav_bytes) -> bytes:
    return make_synthetic_wav_bytes(440.0, duration_seconds=18.0, pulse_period=0.48)
