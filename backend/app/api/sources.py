from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.analyzer.track_analyzer import TrackAnalyzer
from app.api.tracks import get_song_research_service, get_track_analyzer, get_track_service, import_remote_track
from app.models.track import MusicSourceInfo, OnlineImportRequest, OnlineTrack, TrackAnalysis
from app.services.music_sources import (
    MusicSourceClient,
    MusicSourceError,
    display_title,
    import_file_name,
    source_statuses,
)
from app.services.song_research_service import SongResearchService
from app.services.track_service import TrackService

router = APIRouter(prefix="/api/sources", tags=["online music"])


def get_music_source_client() -> MusicSourceClient:
    return MusicSourceClient()


@router.get("", response_model=list[MusicSourceInfo])
def list_sources() -> list[MusicSourceInfo]:
    """Online sources whose audio may legally be streamed into the mixer."""
    return [MusicSourceInfo(name=item.name, available=item.available, note=item.note) for item in source_statuses()]


@router.get("/search", response_model=list[OnlineTrack])
async def search_online(
    query: str = Query(..., min_length=1, max_length=120),
    source: str = Query(default="audius", pattern="^(audius|jamendo)$"),
    limit: int = Query(default=20, ge=1, le=50),
    client: MusicSourceClient = Depends(get_music_source_client),
    track_service: TrackService = Depends(get_track_service),
) -> list[OnlineTrack]:
    try:
        results = await client.search(source, query, limit)
    except MusicSourceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return _mark_library(results, track_service)


@router.get("/trending", response_model=list[OnlineTrack])
async def trending_online(
    source: str = Query(default="audius", pattern="^(audius|jamendo)$"),
    genre: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
    client: MusicSourceClient = Depends(get_music_source_client),
    track_service: TrackService = Depends(get_track_service),
) -> list[OnlineTrack]:
    try:
        results = await client.trending(source, genre, limit)
    except MusicSourceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return _mark_library(results, track_service)


@router.post("/import", response_model=TrackAnalysis, status_code=status.HTTP_201_CREATED)
async def import_online(
    request: OnlineImportRequest,
    client: MusicSourceClient = Depends(get_music_source_client),
    track_service: TrackService = Depends(get_track_service),
    track_analyzer: TrackAnalyzer = Depends(get_track_analyzer),
    research_service: SongResearchService = Depends(get_song_research_service),
) -> TrackAnalysis:
    """Stream an online song into the library, analyze it, and keep its credit and license."""
    existing = track_service.find_by_source(request.source, request.source_id)
    if existing:
        return existing
    try:
        online = await client.get(request.source, request.source_id)
    except MusicSourceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    def attribute(analysis: TrackAnalysis) -> None:
        analysis.title = display_title(online)
        analysis.artist = online.artist
        analysis.source = online.source
        analysis.source_id = online.source_id
        analysis.source_url = online.page_url
        analysis.license = online.license
        if online.genre and online.genre != "Open Format":
            analysis.genre = online.genre
            analysis.genre_source = "online"
            analysis.genre_confidence = 0.9

    return await import_remote_track(
        online.stream_url,
        import_file_name(online),
        track_service,
        track_analyzer,
        research_service,
        apply_metadata=attribute,
    )


def _mark_library(results: list[OnlineTrack], track_service: TrackService) -> list[OnlineTrack]:
    owned = {
        (analysis.source, analysis.source_id): analysis.track_id
        for analysis in track_service.list_analyses()
        if analysis.source
    }
    for track in results:
        track.in_library_track_id = owned.get((track.source, track.source_id))
    return results
