from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.analyzer.track_analyzer import AudioAnalysisError, TrackAnalyzer
from app.config import settings
from app.models.track import TrackAnalysis, TrackSummary
from app.services.track_service import InvalidAudioFileError, TrackNotFoundError, TrackService


router = APIRouter(prefix="/api/tracks", tags=["tracks"])


def get_track_service() -> TrackService:
    return TrackService(settings)


def get_track_analyzer() -> TrackAnalyzer:
    return TrackAnalyzer()


@router.post("/analyze", response_model=TrackAnalysis, status_code=status.HTTP_201_CREATED)
async def analyze_track(
    file: UploadFile = File(...),
    track_service: TrackService = Depends(get_track_service),
    track_analyzer: TrackAnalyzer = Depends(get_track_analyzer),
) -> TrackAnalysis:
    try:
        track_id = track_service.generate_track_id()
        saved_file = await track_service.save_upload(file, track_id)
        safe_file_name = saved_file.name.removeprefix(f"{track_id}_")
        analysis = track_analyzer.analyze(
            saved_file,
            track_id=track_id,
            original_file_name=safe_file_name,
        )
        track_service.save_analysis(analysis)
        return analysis
    except InvalidAudioFileError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AudioAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("", response_model=list[TrackSummary])
def list_tracks(track_service: TrackService = Depends(get_track_service)) -> list[TrackSummary]:
    return track_service.list_tracks()


@router.get("/{track_id}", response_model=TrackAnalysis)
def get_track(
    track_id: str,
    track_service: TrackService = Depends(get_track_service),
) -> TrackAnalysis:
    try:
        return track_service.get_analysis(track_id)
    except TrackNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
