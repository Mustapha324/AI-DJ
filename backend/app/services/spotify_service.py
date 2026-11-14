"""Spotify playlists as a *song picker* for the DJ.

Spotify's Developer Policy forbids mixing, overlapping or segueing Spotify audio, and
its audio is DRM-protected, so the DJ never plays it. Instead we read the user's
playlists (titles/artists only) and find mixable copies of each song in the local
library or on legal streaming sources (Audius/Jamendo).

Setup: create an app at developer.spotify.com/dashboard, add the redirect URI
``http://127.0.0.1:8000/api/spotify/callback`` and set ``AI_DJ_SPOTIFY_CLIENT_ID``.
Login uses Authorization Code with PKCE, so no client secret is stored.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import time
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app.models.track import OnlineTrack, SpotifyMatch, SpotifyPlaylist, SpotifySong, TrackAnalysis
from app.services.music_sources import MusicSourceClient, MusicSourceError

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
SCOPES = "playlist-read-private playlist-read-collaborative"
DEFAULT_REDIRECT = "http://127.0.0.1:8000/api/spotify/callback"
MATCH_THRESHOLD = 0.62
MAX_PLAYLIST_SONGS = 60


class SpotifyError(Exception):
    """Raised when Spotify is not configured, not connected, or returns an error."""


def spotify_client_id() -> str | None:
    value = os.getenv("AI_DJ_SPOTIFY_CLIENT_ID", "").strip()
    return value or None


def spotify_redirect_uri() -> str:
    return os.getenv("AI_DJ_SPOTIFY_REDIRECT_URI", "").strip() or DEFAULT_REDIRECT


class SpotifySession:
    """PKCE login state and tokens, kept in a small local file next to the app's job records."""

    def __init__(self, storage_dir: Path) -> None:
        self.path = storage_dir / "spotify_session.json"
        self._pending: dict[str, str] = {}

    def login_url(self) -> str:
        client_id = spotify_client_id()
        if not client_id:
            raise SpotifyError("Set AI_DJ_SPOTIFY_CLIENT_ID to your Spotify app's Client ID first.")
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(16)
        self._pending = {"state": state, "verifier": verifier}
        self._write({**self._read(), "pending": self._pending})
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": spotify_redirect_uri(),
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
            "scope": SCOPES,
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    async def finish_login(self, code: str, state: str, http: httpx.AsyncClient | None = None) -> None:
        stored = self._read()
        pending = stored.get("pending") or self._pending
        if not pending or not secrets.compare_digest(state, pending.get("state", "")):
            raise SpotifyError("Spotify login expired or did not match. Please try Connect Spotify again.")
        tokens = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": spotify_redirect_uri(),
                "client_id": spotify_client_id() or "",
                "code_verifier": pending["verifier"],
            },
            http,
        )
        self._save_tokens(tokens)

    def connected(self) -> bool:
        return bool(self._read().get("refresh_token") or self._read().get("access_token"))

    def disconnect(self) -> None:
        self.path.unlink(missing_ok=True)

    async def access_token(self, http: httpx.AsyncClient | None = None) -> str:
        stored = self._read()
        if not stored.get("access_token"):
            raise SpotifyError("Spotify is not connected yet.")
        if stored.get("expires_at", 0) > time.time() + 30:
            return stored["access_token"]
        if not stored.get("refresh_token"):
            raise SpotifyError("Spotify login expired. Please connect again.")
        tokens = await self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": stored["refresh_token"],
                "client_id": spotify_client_id() or "",
            },
            http,
        )
        tokens.setdefault("refresh_token", stored["refresh_token"])
        self._save_tokens(tokens)
        return tokens["access_token"]

    async def _token_request(self, form: dict[str, str], http: httpx.AsyncClient | None) -> dict:
        try:
            if http is not None:
                response = await http.post(TOKEN_URL, data=form)
            else:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.post(TOKEN_URL, data=form)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise SpotifyError(f"Spotify login failed (HTTP {exc.response.status_code}).") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise SpotifyError("Could not reach Spotify.") from exc

    def _save_tokens(self, tokens: dict) -> None:
        self._write(
            {
                "access_token": tokens["access_token"],
                "refresh_token": tokens.get("refresh_token"),
                "expires_at": time.time() + float(tokens.get("expires_in", 3600)),
            }
        )

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


class SpotifyLibrary:
    def __init__(self, session: SpotifySession, http: httpx.AsyncClient | None = None) -> None:
        self.session = session
        self.http = http

    async def playlists(self) -> list[SpotifyPlaylist]:
        data = await self._get(f"{API_URL}/me/playlists", {"limit": "50"})
        playlists = []
        for item in data.get("items") or []:
            if not item:
                continue
            total = (item.get("tracks") or item.get("items") or {}).get("total", 0)
            images = item.get("images") or []
            playlists.append(
                SpotifyPlaylist(
                    id=item["id"],
                    name=item.get("name") or "Untitled playlist",
                    song_count=int(total or 0),
                    image_url=images[0].get("url") if images else None,
                )
            )
        return playlists

    async def playlist_songs(self, playlist_id: str) -> list[SpotifySong]:
        songs: list[SpotifySong] = []
        # Spotify moved playlist contents to /items in 2026; fall back to /tracks for older apps.
        for path in ("items", "tracks"):
            try:
                data = await self._get(f"{API_URL}/playlists/{playlist_id}/{path}", {"limit": "100"})
            except SpotifyError:
                if path == "tracks":
                    raise
                continue
            for entry in data.get("items") or []:
                track = (entry or {}).get("track") or (entry or {}).get("item")
                if not track or track.get("type", "track") != "track" or not track.get("name"):
                    continue
                artists = [artist.get("name") for artist in track.get("artists") or [] if artist.get("name")]
                songs.append(
                    SpotifySong(
                        title=track["name"],
                        artist=", ".join(artists) or "Unknown artist",
                        duration_seconds=(track.get("duration_ms") or 0) / 1000.0,
                    )
                )
            break
        return songs[:MAX_PLAYLIST_SONGS]

    async def _get(self, url: str, params: dict[str, str]) -> dict:
        token = await self.session.access_token(self.http)
        headers = {"Authorization": f"Bearer {token}"}
        try:
            if self.http is not None:
                response = await self.http.get(url, params=params, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise SpotifyError(f"Spotify returned HTTP {exc.response.status_code}.") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise SpotifyError("Could not reach Spotify.") from exc


async def match_songs(
    songs: list[SpotifySong],
    library: list[TrackAnalysis],
    sources: MusicSourceClient,
    source: str = "audius",
) -> list[SpotifyMatch]:
    """Find a mixable copy of each Spotify song: local library first, then online."""
    semaphore = asyncio.Semaphore(4)

    async def match_one(song: SpotifySong) -> SpotifyMatch:
        local = _best_library_match(song, library)
        if local:
            return SpotifyMatch(song=song, library_track_id=local[0].track_id, confidence=round(local[1], 3))
        async with semaphore:
            try:
                candidates = await sources.search(source, f"{song.artist} {song.title}", 8)
            except MusicSourceError:
                candidates = []
        best = _best_online_match(song, candidates)
        if best:
            return SpotifyMatch(song=song, online=best[0], confidence=round(best[1], 3))
        return SpotifyMatch(song=song, confidence=0.0)

    return list(await asyncio.gather(*(match_one(song) for song in songs)))


def _best_library_match(song: SpotifySong, library: list[TrackAnalysis]) -> tuple[TrackAnalysis, float] | None:
    scored = [(track, _similarity(song, track.title, track.artist or "", track.duration_seconds)) for track in library]
    scored = [item for item in scored if item[1] >= 0.75]
    return max(scored, key=lambda item: item[1]) if scored else None


def _best_online_match(song: SpotifySong, candidates: list[OnlineTrack]) -> tuple[OnlineTrack, float] | None:
    scored = [(track, _similarity(song, track.title, track.artist, track.duration_seconds)) for track in candidates]
    scored = [item for item in scored if item[1] >= MATCH_THRESHOLD]
    return max(scored, key=lambda item: item[1]) if scored else None


def _similarity(song: SpotifySong, title: str, artist: str, duration: float) -> float:
    wanted_title = _normalize(song.title)
    found = _normalize(title)
    title_score = max(
        SequenceMatcher(None, wanted_title, found).ratio(),
        1.0 if wanted_title and wanted_title in found else 0.0,
    )
    first_artist = _normalize(song.artist.split(",")[0])
    artist_text = _normalize(f"{artist} {title}")
    artist_score = 1.0 if first_artist and first_artist in artist_text else SequenceMatcher(None, first_artist, _normalize(artist)).ratio()
    score = title_score * 0.65 + artist_score * 0.35
    if song.duration_seconds and duration:
        gap = abs(song.duration_seconds - duration)
        if gap > 45:
            score -= 0.1  # probably a remix, extended mix or a different song
    return max(0.0, min(1.0, score))


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\((feat|ft)\.?[^)]*\)|\[(feat|ft)\.?[^\]]*\]", " ", text)
    text = re.sub(r"\b(feat|ft)\.?\s.*$", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())
