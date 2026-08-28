from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.analyzer.track_analyzer import AudioAnalysisError, TrackAnalyzer
from app.api.jobs import get_job_service
from app.config import settings
from app.models.track import (
    BatchAnalyzeResponse,
    TrackAnalysis,
    TrackCompatibility,
    TrackGenreUpdateRequest,
    TrackImportUrlRequest,
    TrackSummary,
)
from app.models.song_research import MusicSourceRecommendation, SongResearchRecord
from app.services.batch_analyzer import BatchAnalyzer, BatchLimitError
from app.services.compatibility import CompatibilityService
from app.services.genre_service import classify_track_genre
from app.services.job_service import JobService
from app.services.song_research_service import SongResearchService
from app.services.track_service import InvalidAudioFileError, TrackNotFoundError, TrackService


router = APIRouter(prefix="/api/tracks", tags=["tracks"])


def get_track_service() -> TrackService:
    return TrackService(settings)


def get_track_analyzer() -> TrackAnalyzer:
    return TrackAnalyzer()


def get_song_research_service() -> SongResearchService:
    return SongResearchService(settings)


@router.post("/analyze", response_model=TrackAnalysis, status_code=status.HTTP_201_CREATED)
async def analyze_track(
    file: UploadFile = File(...),
    track_service: TrackService = Depends(get_track_service),
    track_analyzer: TrackAnalyzer = Depends(get_track_analyzer),
    research_service: SongResearchService = Depends(get_song_research_service),
) -> TrackAnalysis:
    saved_upload = None
    try:
        track_id = track_service.generate_track_id()
        saved_upload = await track_service.save_upload_for_analysis(file, track_id)
        duplicate = track_service.find_duplicate_by_hash(saved_upload.content_hash)
        if duplicate:
            saved_upload.path.unlink(missing_ok=True)
            _research_tracks([duplicate.track_id], track_service, research_service)
            return duplicate

        analysis = track_analyzer.analyze(
            saved_upload.path,
            track_id=track_id,
            original_file_name=saved_upload.safe_file_name,
        )
        classify_track_genre(analysis, saved_upload.path)
        analysis.content_hash = saved_upload.content_hash
        analysis.file_size_bytes = saved_upload.size_bytes
        duplicate = track_service.find_duplicate_by_analysis(analysis)
        if duplicate:
            saved_upload.path.unlink(missing_ok=True)
            _research_tracks([duplicate.track_id], track_service, research_service)
            return duplicate

        track_service.save_analysis(analysis)
        _research_tracks([analysis.track_id], track_service, research_service)
        return analysis
    except InvalidAudioFileError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AudioAnalysisError as exc:
        if saved_upload:
            saved_upload.path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/analyze-batch", response_model=BatchAnalyzeResponse, status_code=status.HTTP_201_CREATED)
async def analyze_track_batch(
    files: list[UploadFile] = File(...),
    track_service: TrackService = Depends(get_track_service),
    track_analyzer: TrackAnalyzer = Depends(get_track_analyzer),
    job_service: JobService = Depends(get_job_service),
    research_service: SongResearchService = Depends(get_song_research_service),
) -> BatchAnalyzeResponse:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload at least one MP3 file.")

    job = job_service.create_job("queued", "Batch analysis queued.")
    batch_analyzer = BatchAnalyzer(track_service, track_analyzer, job_service)
    try:
        result = await batch_analyzer.analyze_files(files, job_id=job.job_id)
        _research_tracks(
            [track.track_id for track in result.tracks],
            track_service,
            research_service,
        )
        return result
    except BatchLimitError as exc:
        job_service.update_job(job.job_id, status="failed", progress=100, message="Batch analysis failed.", error=str(exc))
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc


@router.post("/import-url", response_model=TrackAnalysis, status_code=status.HTTP_201_CREATED)
async def import_track_from_url(
    request: TrackImportUrlRequest,
    track_service: TrackService = Depends(get_track_service),
    track_analyzer: TrackAnalyzer = Depends(get_track_analyzer),
    research_service: SongResearchService = Depends(get_song_research_service),
) -> TrackAnalysis:
    saved_upload = None
    try:
        track_id = track_service.generate_track_id()
        saved_upload = await track_service.save_remote_audio_for_analysis(
            request.url,
            track_id,
            file_name=request.file_name,
        )
        duplicate = track_service.find_duplicate_by_hash(saved_upload.content_hash)
        if duplicate:
            saved_upload.path.unlink(missing_ok=True)
            _research_tracks([duplicate.track_id], track_service, research_service)
            return duplicate

        analysis = track_analyzer.analyze(
            saved_upload.path,
            track_id=track_id,
            original_file_name=saved_upload.safe_file_name,
        )
        classify_track_genre(analysis, saved_upload.path)
        analysis.content_hash = saved_upload.content_hash
        analysis.file_size_bytes = saved_upload.size_bytes
        duplicate = track_service.find_duplicate_by_analysis(analysis)
        if duplicate:
            saved_upload.path.unlink(missing_ok=True)
            _research_tracks([duplicate.track_id], track_service, research_service)
            return duplicate

        track_service.save_analysis(analysis)
        _research_tracks([analysis.track_id], track_service, research_service)
        return analysis
    except InvalidAudioFileError as exc:
        if saved_upload:
            saved_upload.path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AudioAnalysisError as exc:
        if saved_upload:
            saved_upload.path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("", response_model=list[TrackSummary])
def list_tracks(track_service: TrackService = Depends(get_track_service)) -> list[TrackSummary]:
    return track_service.list_tracks()


@router.get("/research", response_model=list[SongResearchRecord])
def research_all_tracks(
    track_service: TrackService = Depends(get_track_service),
    research_service: SongResearchService = Depends(get_song_research_service),
) -> list[SongResearchRecord]:
    analyses = track_service.list_analyses()
    return [research_service.build_track_research(track, analyses) for track in analyses]


@router.get("/music-sources", response_model=list[MusicSourceRecommendation])
def legal_music_sources(
    research_service: SongResearchService = Depends(get_song_research_service),
) -> list[MusicSourceRecommendation]:
    return research_service.legal_music_sources()


@router.get("/search", response_model=list[TrackSummary])
def search_tracks(
    query: str | None = Query(default=None, max_length=120),
    genre: str | None = Query(default=None, max_length=64),
    track_service: TrackService = Depends(get_track_service),
) -> list[TrackSummary]:
    return track_service.search_tracks(query, genre=genre)


@router.patch("/{track_id}/genre", response_model=TrackAnalysis)
def update_track_genre(
    track_id: str,
    request: TrackGenreUpdateRequest,
    track_service: TrackService = Depends(get_track_service),
) -> TrackAnalysis:
    try:
        return track_service.update_genre(track_id, request.genre)
    except TrackNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{track_id}/compatible", response_model=list[TrackCompatibility])
def get_compatible_tracks(
    track_id: str,
    track_service: TrackService = Depends(get_track_service),
) -> list[TrackCompatibility]:
    try:
        source = track_service.get_analysis(track_id)
    except TrackNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    compatibility_service = CompatibilityService()
    matches = [
        compatibility_service.compare(source, candidate)
        for candidate in track_service.list_analyses()
        if candidate.track_id != source.track_id
    ]
    return sorted(matches, key=lambda item: item.compatibility_score, reverse=True)


@router.get("/{track_id}/research", response_model=SongResearchRecord)
def research_track(
    track_id: str,
    track_service: TrackService = Depends(get_track_service),
    research_service: SongResearchService = Depends(get_song_research_service),
) -> SongResearchRecord:
    try:
        source = track_service.get_analysis(track_id)
    except TrackNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    saved_research = research_service.get(track_id)
    if saved_research:
        return saved_research
    return research_service.build_track_research(source, track_service.list_analyses())


@router.get("/{track_id}/audio")
def get_track_audio(
    track_id: str,
    track_service: TrackService = Depends(get_track_service),
) -> FileResponse:
    try:
        audio_path = track_service.get_uploaded_audio_path(track_id)
    except TrackNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    media_type = "audio/mpeg" if audio_path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(audio_path, media_type=media_type, filename=audio_path.name)


@router.get("/{track_id}", response_model=TrackAnalysis)
def get_track(
    track_id: str,
    track_service: TrackService = Depends(get_track_service),
) -> TrackAnalysis:
    try:
        return track_service.get_analysis(track_id)
    except TrackNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _research_tracks(
    track_ids: list[str],
    track_service: TrackService,
    research_service: SongResearchService,
) -> None:
    library = track_service.list_analyses()
    analysis_by_id = {track.track_id: track for track in library}
    for track_id in dict.fromkeys(track_ids):
        track = analysis_by_id.get(track_id)
        if track:
            research_service.build_track_research(track, library)
