from dataclasses import dataclass, field
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    uploads_dir: Path = BACKEND_DIR / "uploads"
    analysis_output_dir: Path = BACKEND_DIR / "analysis_output"
    allowed_audio_extensions: tuple[str, ...] = (".wav", ".mp3")
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


settings = Settings()


def ensure_storage_dirs(current_settings: Settings = settings) -> None:
    current_settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    current_settings.analysis_output_dir.mkdir(parents=True, exist_ok=True)
