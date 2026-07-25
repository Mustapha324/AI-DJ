from __future__ import annotations

import logging

from fastapi import UploadFile

from app.analyzer.track_analyzer import AudioAnalysisError, TrackAnalyzer
from app.models.track import BatchAnalyzeResponse, BatchTrackError, BatchTrackResult
from app.services.job_service import JobService
from app.services.track_service import InvalidAudioFileError, TrackService


logger = logging.getLogger(__name__)


class BatchLimitError(Exception):
    """Raised when a batch request exceeds configured limits."""


class BatchAnalyzer:
    def __init__(
        self,
        track_service: TrackService,
        track_analyzer: TrackAnalyzer,
        job_service: JobService | None = None,
    ) -> None:
        self.track_service = track_service
        self.track_analyzer = track_analyzer
        self.job_service = job_service

    async def analyze_files(self, files: list[UploadFile], job_id: str | None = None) -> BatchAnalyzeResponse:
        if len(files) > self.track_service.settings.max_batch_files:
            raise BatchLimitError(
                f"Batch contains {len(files)} files; the configured limit is "
                f"{self.track_service.settings.max_batch_files}."
            )

        tracks: list[BatchTrackResult] = []
        errors: list[BatchTrackError] = []

        total_files = len(files)
        for index, upload in enumerate(files, start=1):
            file_name = upload.filename or "unnamed"
            if job_id and self.job_service:
                self.job_service.update_job(
                    job_id,
                    status="analyzing",
                    progress=int(((index - 1) / max(total_files, 1)) * 100),
                    message=f"Analyzing {index} of {total_files}: {file_name}",
                )

            track_id = self.track_service.generate_track_id()
            saved_upload = None
            try:
                saved_upload = await self.track_service.save_upload_for_analysis(
                    upload,
                    track_id,
                    allowed_extensions=self.track_service.settings.batch_audio_extensions,
                )
                duplicate = self.track_service.find_duplicate_by_hash(saved_upload.content_hash)
                if duplicate:
                    saved_upload.path.unlink(missing_ok=True)
                    tracks.append(
                        BatchTrackResult(
                            track_id=duplicate.track_id,
                            file_name=duplicate.file_name,
                            status="duplicate",
                        )
                    )
                    continue

                analysis = self.track_analyzer.analyze(
                    saved_upload.path,
                    track_id=track_id,
                    original_file_name=saved_upload.safe_file_name,
                )
                analysis.content_hash = saved_upload.content_hash
                analysis.file_size_bytes = saved_upload.size_bytes
                duplicate = self.track_service.find_duplicate_by_analysis(analysis)
                if duplicate:
                    saved_upload.path.unlink(missing_ok=True)
                    tracks.append(
                        BatchTrackResult(
                            track_id=duplicate.track_id,
                            file_name=duplicate.file_name,
                            status="duplicate",
                        )
                    )
                    continue

                self.track_service.save_analysis(analysis)
                tracks.append(
                    BatchTrackResult(
                        track_id=analysis.track_id,
                        file_name=analysis.file_name,
                        status="analyzed",
                    )
                )
            except InvalidAudioFileError as exc:
                if saved_upload:
                    saved_upload.path.unlink(missing_ok=True)
                errors.append(BatchTrackError(file_name=file_name, error=str(exc)))
            except AudioAnalysisError as exc:
                if saved_upload:
                    saved_upload.path.unlink(missing_ok=True)
                logger.warning("Audio analysis failed for batch upload %s: %s", file_name, exc)
                errors.append(BatchTrackError(file_name=file_name, error=str(exc)))
            except Exception as exc:  # Keep one bad file from ending the whole batch.
                if saved_upload:
                    saved_upload.path.unlink(missing_ok=True)
                logger.exception("Unexpected batch analysis error for %s", file_name)
                errors.append(BatchTrackError(file_name=file_name, error="Unexpected analysis failure."))

        successful = sum(1 for result in tracks if result.status == "analyzed")
        duplicates = sum(1 for result in tracks if result.status == "duplicate")
        if job_id and self.job_service:
            self.job_service.update_job(
                job_id,
                status="completed" if not errors else "failed" if not successful and not duplicates else "completed",
                progress=100,
                message=f"Analyzed {successful} file(s), found {duplicates} duplicate(s), failed {len(errors)}.",
            )

        return BatchAnalyzeResponse(
            total_files=total_files,
            successful=successful,
            failed=len(errors),
            duplicates=duplicates,
            tracks=tracks,
            errors=errors,
            job_id=job_id,
        )
