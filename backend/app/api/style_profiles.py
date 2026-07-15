from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.config import settings
from app.models.style_profile import DJStyleProfile, StyleProfileSummary
from app.services.style_profile_service import (
    ReferenceMixAnalysisError,
    StyleProfileNotFoundError,
    StyleProfileService,
)
from app.services.track_service import InvalidAudioFileError


router = APIRouter(prefix="/api/style-profiles", tags=["style profiles"])


def get_style_profile_service() -> StyleProfileService:
    return StyleProfileService(settings)


@router.post("/train", response_model=DJStyleProfile, status_code=status.HTTP_201_CREATED)
async def train_style_profile(
    files: list[UploadFile] = File(...),
    name: str = Form(default="Default DJ Style"),
    style_service: StyleProfileService = Depends(get_style_profile_service),
) -> DJStyleProfile:
    try:
        return await style_service.train_from_uploads(files, name=name, profile_id="default")
    except InvalidAudioFileError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ReferenceMixAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("", response_model=list[StyleProfileSummary])
def list_style_profiles(
    style_service: StyleProfileService = Depends(get_style_profile_service),
) -> list[StyleProfileSummary]:
    return style_service.list_profiles()


@router.get("/default", response_model=DJStyleProfile)
def get_default_style_profile(
    style_service: StyleProfileService = Depends(get_style_profile_service),
) -> DJStyleProfile:
    try:
        return style_service.get_profile("default")
    except StyleProfileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
