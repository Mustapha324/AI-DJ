from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from fastapi import UploadFile

from app.config import Settings, ensure_storage_dirs
from app.models.track import TrackAnalysis, TrackSummary


class InvalidAudioFileError(Exception):
    """Raised when an upload fails basic file validation."""


class TrackNotFoundError(Exception):
    """Raised when no saved analysis exists for a track ID."""


@dataclass(frozen=True)
class SavedUpload:
    path: Path
    safe_file_name: str
    content_hash: str
    size_bytes: int


class TrackService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        ensure_storage_dirs(settings)

    def generate_track_id(self) -> str:
        return uuid.uuid4().hex

    async def save_upload(self, upload: UploadFile, track_id: str) -> Path:
        return (await self.save_upload_for_analysis(upload, track_id)).path

    async def save_upload_for_analysis(
        self,
        upload: UploadFile,
        track_id: str,
        allowed_extensions: tuple[str, ...] | None = None,
    ) -> SavedUpload:
        safe_name = self.validate_and_sanitize_upload(upload, allowed_extensions=allowed_extensions)
        destination = self.settings.uploads_dir / f"{track_id}_{safe_name}"

        if destination.exists():
            raise InvalidAudioFileError("A file with this generated name already exists. Please try again.")

        digest = sha256()
        bytes_written = 0
        try:
            with destination.open("wb") as output_file:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    bytes_written += len(chunk)
                    if bytes_written > self.settings.max_upload_size_bytes:
                        raise InvalidAudioFileError("The uploaded file is larger than the configured limit.")
                    digest.update(chunk)
                    output_file.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

        if bytes_written == 0:
            destination.unlink(missing_ok=True)
            raise InvalidAudioFileError("The uploaded file is empty.")

        return SavedUpload(
            path=destination,
            safe_file_name=safe_name,
            content_hash=digest.hexdigest(),
            size_bytes=bytes_written,
        )

    async def save_remote_audio_for_analysis(
        self,
        url: str,
        track_id: str,
        file_name: str | None = None,
    ) -> SavedUpload:
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise InvalidAudioFileError("Paste a valid HTTP or HTTPS audio link.")
        if _is_youtube_host(parsed.netloc):
            raise InvalidAudioFileError(
                "YouTube links cannot be imported as MP3s here. Use audio you own, have permission to download, "
                "or paste a direct MP3/WAV link from an authorized source."
            )
        if _is_blocked_host(parsed.hostname):
            raise InvalidAudioFileError("Local or private network links are not supported for import.")

        safe_name = _safe_remote_file_name(file_name, parsed.path)
        destination = self.settings.uploads_dir / f"{track_id}_{safe_name}"
        digest = sha256()
        bytes_written = 0

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    final_host = urlparse(str(response.url)).netloc
                    if _is_youtube_host(final_host):
                        raise InvalidAudioFileError("YouTube redirects are not supported for audio import.")
                    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    safe_name = _safe_remote_file_name(file_name or _name_from_response(response, parsed.path), parsed.path)
                    if not _remote_audio_allowed(safe_name, content_type, self.settings.allowed_content_types):
                        raise InvalidAudioFileError("Direct audio links must point to an MP3 or WAV file.")
                    destination = self.settings.uploads_dir / f"{track_id}_{safe_name}"
                    with destination.open("wb") as output_file:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            if not chunk:
                                continue
                            bytes_written += len(chunk)
                            if bytes_written > self.settings.max_upload_size_bytes:
                                raise InvalidAudioFileError("The linked audio is larger than the configured upload limit.")
                            digest.update(chunk)
                            output_file.write(chunk)
        except InvalidAudioFileError:
            destination.unlink(missing_ok=True)
            raise
        except httpx.HTTPStatusError as exc:
            destination.unlink(missing_ok=True)
            raise InvalidAudioFileError(f"The audio link returned HTTP {exc.response.status_code}.") from exc
        except httpx.HTTPError as exc:
            destination.unlink(missing_ok=True)
            raise InvalidAudioFileError("Could not download the linked audio.") from exc
        except Exception:
            destination.unlink(missing_ok=True)
            raise

        if bytes_written == 0:
            destination.unlink(missing_ok=True)
            raise InvalidAudioFileError("The linked audio was empty.")

        return SavedUpload(
            path=destination,
            safe_file_name=safe_name,
            content_hash=digest.hexdigest(),
            size_bytes=bytes_written,
        )

    def validate_and_sanitize_upload(
        self,
        upload: UploadFile,
        allowed_extensions: tuple[str, ...] | None = None,
    ) -> str:
        if not upload.filename:
            raise InvalidAudioFileError("Upload must include a file name.")

        allowed = allowed_extensions or self.settings.allowed_audio_extensions
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in allowed:
            allowed_display = ", ".join(allowed)
            raise InvalidAudioFileError(f"Unsupported file type. Please upload one of: {allowed_display}.")

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
                    beat_count=analysis.beats.beat_count,
                    approximate_bar_count=len(analysis.beats.approximate_bars),
                    overall_rms_energy=analysis.overall_rms_energy,
                )
            )
        return tracks

    def search_tracks(self, query: str | None = None) -> list[TrackSummary]:
        tracks = self.list_tracks()
        cleaned_query = " ".join((query or "").lower().split())
        if not cleaned_query:
            return tracks

        terms = cleaned_query.split()

        def matches(track: TrackSummary) -> bool:
            searchable = " ".join(
                [
                    track.title,
                    track.file_name,
                    track.key.root,
                    track.key.mode,
                    track.key.display_name,
                    str(round(track.estimated_bpm or 0)),
                ]
            ).lower()
            return all(term in searchable for term in terms)

        return [track for track in tracks if matches(track)]

    def list_analyses(self) -> list[TrackAnalysis]:
        tracks: list[TrackAnalysis] = []
        for analysis_file in sorted(self.settings.analysis_output_dir.glob("*.json")):
            try:
                tracks.append(self._load_analysis_file(analysis_file))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
        return tracks

    def find_duplicate_by_hash(self, content_hash: str) -> TrackAnalysis | None:
        for analysis in self.list_analyses():
            if analysis.content_hash and analysis.content_hash == content_hash:
                return analysis
        return None

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

    def get_uploaded_audio_path(self, track_id: str) -> Path:
        if not _is_valid_track_id(track_id):
            raise TrackNotFoundError(f"Track '{track_id}' was not found.")

        matches = sorted(self.settings.uploads_dir.glob(f"{track_id}_*"))
        if not matches:
            raise TrackNotFoundError(f"Track '{track_id}' audio file was not found.")
        return matches[0]

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


def _safe_remote_file_name(file_name: str | None, url_path: str) -> str:
    raw_name = file_name or Path(unquote(url_path)).name or "linked-audio.mp3"
    safe_name = sanitize_file_name(raw_name)
    suffix = Path(safe_name).suffix.lower()
    if not suffix:
        return f"{safe_name}.mp3"
    return safe_name


def _name_from_response(response: httpx.Response, fallback_path: str) -> str:
    content_disposition = response.headers.get("content-disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', content_disposition, flags=re.IGNORECASE)
    if match:
        return unquote(match.group(1))
    return Path(unquote(fallback_path)).name or "linked-audio.mp3"


def _remote_audio_allowed(file_name: str, content_type: str, allowed_content_types: set[str]) -> bool:
    suffix = Path(file_name).suffix.lower()
    if suffix in {".mp3", ".wav"}:
        return True
    return content_type in allowed_content_types


def _is_youtube_host(host: str | None) -> bool:
    cleaned = (host or "").split(":")[0].lower()
    return cleaned in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"} or cleaned.endswith(
        ".youtube.com"
    )


def _is_blocked_host(host: str | None) -> bool:
    cleaned = (host or "").lower()
    return cleaned in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _is_valid_track_id(track_id: str) -> bool:
    return bool(re.fullmatch(r"[a-fA-F0-9]{32}", track_id))
