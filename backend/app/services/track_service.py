from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import Settings, ensure_storage_dirs
from app.models.track import TrackAnalysis, TrackSummary


class InvalidAudioFileError(Exception):
    """Raised when an upload fails basic file validation."""


class TrackNotFoundError(Exception):
    """Raised when no saved analysis exists for a track ID."""


class TrackService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        ensure_storage_dirs(settings)

    def generate_track_id(self) -> str:
        return uuid.uuid4().hex

    async def save_upload(self, upload: UploadFile, track_id: str) -> Path:
        safe_name = self.validate_and_sanitize_upload(upload)
        destination = self.settings.uploads_dir / f"{track_id}_{safe_name}"

        if destination.exists():
            raise InvalidAudioFileError("A file with this generated name already exists. Please try again.")

        bytes_written = 0
        with destination.open("wb") as output_file:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                output_file.write(chunk)

        if bytes_written == 0:
            destination.unlink(missing_ok=True)
            raise InvalidAudioFileError("The uploaded file is empty.")

        return destination

    def validate_and_sanitize_upload(self, upload: UploadFile) -> str:
        if not upload.filename:
            raise InvalidAudioFileError("Upload must include a file name.")

        suffix = Path(upload.filename).suffix.lower()
        if suffix not in self.settings.allowed_audio_extensions:
            allowed = ", ".join(self.settings.allowed_audio_extensions)
            raise InvalidAudioFileError(f"Unsupported file type. Please upload one of: {allowed}.")

        if upload.content_type and upload.content_type not in self.settings.allowed_content_types:
            raise InvalidAudioFileError("Unsupported audio content type.")

        return sanitize_file_name(upload.filename)

    def save_analysis(self, analysis: TrackAnalysis) -> Path:
        destination = self._analysis_path(analysis.track_id)
        with destination.open("w", encoding="utf-8") as output_file:
            json.dump(analysis.model_dump(mode="json"), output_file, indent=2)
        return destination

    def list_tracks(self) -> list[TrackSummary]:
        tracks: list[TrackSummary] = []
        for analysis_file in sorted(self.settings.analysis_output_dir.glob("*.json")):
            try:
                analysis = self._load_analysis_file(analysis_file)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            tracks.append(
                TrackSummary(
                    track_id=analysis.track_id,
                    title=analysis.title,
                    file_name=analysis.file_name,
                    duration_seconds=analysis.duration_seconds,
                    estimated_bpm=analysis.estimated_bpm,
                    key=analysis.key,
                )
            )
        return tracks

    def get_analysis(self, track_id: str) -> TrackAnalysis:
        if not _is_valid_track_id(track_id):
            raise TrackNotFoundError(f"Track '{track_id}' was not found.")

        analysis_path = self._analysis_path(track_id)
        if not analysis_path.exists():
            raise TrackNotFoundError(f"Track '{track_id}' was not found.")

        try:
            return self._load_analysis_file(analysis_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise TrackNotFoundError(f"Track '{track_id}' could not be loaded.") from exc

    def _analysis_path(self, track_id: str) -> Path:
        return self.settings.analysis_output_dir / f"{track_id}.json"

    @staticmethod
    def _load_analysis_file(path: Path) -> TrackAnalysis:
        with path.open("r", encoding="utf-8") as input_file:
            data = json.load(input_file)
        return TrackAnalysis.model_validate(data)


def sanitize_file_name(file_name: str) -> str:
    base_name = Path(file_name).name.strip()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", base_name)
    safe_name = safe_name.strip("._")
    return safe_name or "track"


def _is_valid_track_id(track_id: str) -> bool:
    return bool(re.fullmatch(r"[a-fA-F0-9]{32}", track_id))
