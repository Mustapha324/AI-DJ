from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.api.sources import get_music_source_client
from app.api.tracks import get_track_service
from app.config import settings
from app.models.track import SpotifyMatch, SpotifyPlaylist, SpotifyStatus
from app.services.music_sources import MusicSourceClient
from app.services.spotify_service import (
    SpotifyError,
    SpotifyLibrary,
    SpotifySession,
    match_songs,
    spotify_client_id,
    spotify_redirect_uri,
)
from app.services.track_service import TrackService

router = APIRouter(prefix="/api/spotify", tags=["spotify"])


def get_spotify_session() -> SpotifySession:
    return SpotifySession(settings.jobs_dir)


@router.get("/status", response_model=SpotifyStatus)
def spotify_status(session: SpotifySession = Depends(get_spotify_session)) -> SpotifyStatus:
    configured = spotify_client_id() is not None
    return SpotifyStatus(
        configured=configured,
        connected=configured and session.connected(),
        redirect_uri=spotify_redirect_uri(),
        note=(
            "Spotify picks songs from your playlists; the DJ mixes matching copies from your library or Audius."
            if configured
            else "Set AI_DJ_SPOTIFY_CLIENT_ID to your Spotify app's Client ID and add the redirect URI shown here."
        ),
    )


@router.get("/login", include_in_schema=False)
def spotify_login(session: SpotifySession = Depends(get_spotify_session)) -> RedirectResponse:
    try:
        return RedirectResponse(session.login_url())
    except SpotifyError as exc:
        return RedirectResponse(f"/?spotify_error={_quote(str(exc))}")


@router.get("/callback", include_in_schema=False)
async def spotify_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: SpotifySession = Depends(get_spotify_session),
) -> RedirectResponse:
    if error or not code or not state:
        return RedirectResponse(f"/?spotify_error={_quote(error or 'Spotify login was cancelled.')}")
    try:
        await session.finish_login(code, state)
    except SpotifyError as exc:
        return RedirectResponse(f"/?spotify_error={_quote(str(exc))}")
    return RedirectResponse("/?spotify=connected")


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def spotify_disconnect(session: SpotifySession = Depends(get_spotify_session)) -> None:
    session.disconnect()


@router.get("/playlists", response_model=list[SpotifyPlaylist])
async def spotify_playlists(session: SpotifySession = Depends(get_spotify_session)) -> list[SpotifyPlaylist]:
    try:
        return await SpotifyLibrary(session).playlists()
    except SpotifyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/playlists/{playlist_id}/matches", response_model=list[SpotifyMatch])
async def spotify_playlist_matches(
    playlist_id: str,
    source: str = Query(default="audius", pattern="^(audius|jamendo)$"),
    session: SpotifySession = Depends(get_spotify_session),
    track_service: TrackService = Depends(get_track_service),
    sources: MusicSourceClient = Depends(get_music_source_client),
) -> list[SpotifyMatch]:
    """Each playlist song with the mixable copy found for it (Spotify audio is never used)."""
    try:
        songs = await SpotifyLibrary(session).playlist_songs(playlist_id)
    except SpotifyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await match_songs(songs, track_service.list_analyses(), sources, source)


def _quote(text: str) -> str:
    from urllib.parse import quote

    return quote(text[:200])
