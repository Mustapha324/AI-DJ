import os
from dataclasses import dataclass, field
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


def _int_from_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _upload_bytes_from_env(default_megabytes: int = 100) -> int:
    megabytes = _int_from_env("AI_DJ_MAX_UPLOAD_MB", default_megabytes)
    return megabytes * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    uploads_dir: Path = field(default_factory=lambda: _path_from_env("AI_DJ_UPLOADS_DIR", BACKEND_DIR / "uploads"))
    analysis_output_dir: Path = field(
        default_factory=lambda: _path_from_env("AI_DJ_ANALYSIS_OUTPUT_DIR", BACKEND_DIR / "analysis_output")
    )
    mixes_dir: Path = field(default_factory=lambda: _path_from_env("AI_DJ_MIXES_DIR", BACKEND_DIR / "mixes"))
    jobs_dir: Path = field(default_factory=lambda: _path_from_env("AI_DJ_JOBS_DIR", BACKEND_DIR / "jobs"))
    allowed_audio_extensions: tuple[str, ...] = (".wav", ".mp3")
    batch_audio_extensions: tuple[str, ...] = (".mp3",)
    allowed_content_types: set[str] = field(
        default_factory=lambda: {
            "audio/wav",
            "audio/x-wav",
            "audio/wave",
            "audio/mpeg",
            "audio/mp3",
            "application/octet-stream",
        }
    )
    max_batch_files: int = field(default_factory=lambda: _int_from_env("AI_DJ_MAX_BATCH_FILES", 25))
    max_upload_size_bytes: int = field(default_factory=_upload_bytes_from_env)
    render_sample_rate: int = field(default_factory=lambda: _int_from_env("AI_DJ_RENDER_SAMPLE_RATE", 44_100))


settings = Settings()


def ensure_storage_dirs(current_settings: Settings = settings) -> None:
    current_settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    current_settings.analysis_output_dir.mkdir(parents=True, exist_ok=True)
    current_settings.mixes_dir.mkdir(parents=True, exist_ok=True)
    current_settings.jobs_dir.mkdir(parents=True, exist_ok=True)
