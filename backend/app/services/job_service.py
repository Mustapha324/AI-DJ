from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app.config import Settings, ensure_storage_dirs
from app.models.job import JobRecord, JobState


class JobNotFoundError(Exception):
    """Raised when a job record does not exist."""


class JobService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        ensure_storage_dirs(settings)

    def create_job(self, status: JobState, message: str) -> JobRecord:
        now = _utc_now()
        job = JobRecord(
            job_id=uuid.uuid4().hex,
            status=status,
            progress=0,
            message=message,
            created_at=now,
            updated_at=now,
        )
        self.save_job(job)
        return job

    def update_job(
        self,
        job_id: str,
        *,
        status: JobState | None = None,
        progress: int | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> JobRecord:
        job = self.get_job(job_id)
        updated = job.model_copy(
            update={
                "status": status or job.status,
                "progress": min(100, max(0, progress if progress is not None else job.progress)),
                "message": message or job.message,
                "error": error,
                "updated_at": _utc_now(),
            }
        )
        self.save_job(updated)
        return updated

    def save_job(self, job: JobRecord) -> None:
        with self._job_path(job.job_id).open("w", encoding="utf-8") as output_file:
            json.dump(job.model_dump(mode="json"), output_file, indent=2)

    def get_job(self, job_id: str) -> JobRecord:
        path = self._job_path(job_id)
        if not path.exists():
            raise JobNotFoundError(f"Job '{job_id}' was not found.")
        with path.open("r", encoding="utf-8") as input_file:
            return JobRecord.model_validate(json.load(input_file))

    def _job_path(self, job_id: str):
        return self.settings.jobs_dir / f"{job_id}.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
