from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.api.jobs import get_job_service
from app.api.style_profiles import get_style_profile_service
from app.api.tracks import get_track_service
from app.config import settings
from app.models.mix import MixPlan, MixPlanRequest, MixRecord, MixSummary, RenderMixRequest
from app.services.compatibility import CompatibilityService
from app.services.job_service import JobService
from app.services.mix_planner import MixPlanner, MixPlanningError
from app.services.mix_renderer import MixRenderer, MixRenderError
from app.services.mix_storage import MixNotFoundError, MixStorage
from app.services.style_profile_service import StyleProfileService
from app.services.track_service import TrackNotFoundError, TrackService


router = APIRouter(prefix="/api/mixes", tags=["mixes"])


def get_mix_storage() -> MixStorage:
    return MixStorage(settings)


def get_mix_planner(
    style_service: StyleProfileService = Depends(get_style_profile_service),
) -> MixPlanner:
    return MixPlanner(CompatibilityService(), style_service.get_default_profile())


@router.post("/plan", response_model=MixPlan, status_code=status.HTTP_201_CREATED)
def create_mix_plan(
    request: MixPlanRequest,
    track_service: TrackService = Depends(get_track_service),
    mix_storage: MixStorage = Depends(get_mix_storage),
    mix_planner: MixPlanner = Depends(get_mix_planner),
    job_service: JobService = Depends(get_job_service),
) -> MixPlan:
    job = job_service.create_job("planning", "Creating mix plan.")
    mix_id = mix_storage.generate_mix_id()

    try:
        analyses = [track_service.get_analysis(track_id) for track_id in request.track_ids]
        plan = mix_planner.create_plan(request, analyses, mix_id=mix_id)
        now = datetime.now(timezone.utc)
        record = MixRecord(
            mix_id=plan.mix_id,
            mix_name=plan.mix_name,
            status="planned",
            track_order=plan.track_order,
            transitions=plan.transitions,
            plan=plan,
            created_at=now,
            updated_at=now,
            job_id=job.job_id,
        )
        mix_storage.save_record(record)
        job_service.update_job(job.job_id, status="completed", progress=100, message="Mix plan created.")
        return plan
    except TrackNotFoundError as exc:
        job_service.update_job(job.job_id, status="failed", progress=100, message="Mix planning failed.", error=str(exc))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MixPlanningError as exc:
        job_service.update_job(job.job_id, status="failed", progress=100, message="Mix planning failed.", error=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/render", response_model=MixRecord, status_code=status.HTTP_201_CREATED)
def render_mix(
    request: RenderMixRequest,
    track_service: TrackService = Depends(get_track_service),
    mix_storage: MixStorage = Depends(get_mix_storage),
    job_service: JobService = Depends(get_job_service),
) -> MixRecord:
    job = job_service.create_job("queued", "Preparing to render mix.")
    record: MixRecord | None = None

    try:
        if request.mix_id:
            record = mix_storage.get_record(request.mix_id)
            plan = record.plan
        elif request.plan:
            plan = request.plan
            now = datetime.now(timezone.utc)
            record = MixRecord(
                mix_id=plan.mix_id,
                mix_name=plan.mix_name,
                status="queued",
                track_order=plan.track_order,
                transitions=plan.transitions,
                plan=plan,
                created_at=now,
                updated_at=now,
                job_id=job.job_id,
            )
        else:
            raise MixRenderError("Provide either mix_id or plan.")

        now = datetime.now(timezone.utc)
        record = record.model_copy(update={"status": "rendering", "updated_at": now, "job_id": job.job_id})
        mix_storage.save_record(record)
        job_service.update_job(job.job_id, status="rendering", progress=5, message="Rendering mix audio.")

        output_path = mix_storage.output_path(plan.mix_id, request.output_format)
        renderer = MixRenderer(track_service.settings, track_service, job_service)
        rendered = renderer.render(plan, output_path, job_id=job.job_id)

        completed = record.model_copy(
            update={
                "status": "completed",
                "output_filename": rendered.output_path.name,
                "duration_seconds": rendered.duration_seconds,
                "errors": [],
                "updated_at": datetime.now(timezone.utc),
            }
        )
        mix_storage.save_record(completed)
        return completed
    except MixNotFoundError as exc:
        job_service.update_job(job.job_id, status="failed", progress=100, message="Mix render failed.", error=str(exc))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MixRenderError as exc:
        if record:
            failed = record.model_copy(
                update={
                    "status": "failed",
                    "errors": [str(exc)],
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            mix_storage.save_record(failed)
        job_service.update_job(job.job_id, status="failed", progress=100, message="Mix render failed.", error=str(exc))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("", response_model=list[MixSummary])
def list_mixes(mix_storage: MixStorage = Depends(get_mix_storage)) -> list[MixSummary]:
    return mix_storage.list_records()


@router.get("/{mix_id}", response_model=MixRecord)
def get_mix(
    mix_id: str,
    mix_storage: MixStorage = Depends(get_mix_storage),
) -> MixRecord:
    try:
        return mix_storage.get_record(mix_id)
    except MixNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{mix_id}/audio")
def get_mix_audio(
    mix_id: str,
    mix_storage: MixStorage = Depends(get_mix_storage),
) -> FileResponse:
    try:
        record = mix_storage.get_record(mix_id)
    except MixNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if record.status != "completed" or not record.output_filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mix audio is not available yet.")

    output_path = mix_storage.settings.mixes_dir / record.output_filename
    if not output_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mix audio file was not found.")

    return FileResponse(output_path, media_type="audio/wav", filename=record.output_filename)
