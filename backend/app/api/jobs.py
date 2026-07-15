from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.models.job import JobRecord
from app.services.job_service import JobNotFoundError, JobService


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def get_job_service() -> JobService:
    return JobService(settings)


@router.get("/{job_id}", response_model=JobRecord)
def get_job(
    job_id: str,
    job_service: JobService = Depends(get_job_service),
) -> JobRecord:
    try:
        return job_service.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
