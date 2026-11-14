"""Legal online music sources that allow full-track streaming into the mixer.

- Audius (no key needed): https://api.audius.co/v1 - full tracks via /tracks/{id}/stream.
- Jamendo (free client_id from devportal.jamendo.com, set AI_DJ_JAMENDO_CLIENT_ID):
  Creative Commons tracks with an ``audio`` stream URL.

Spotify and YouTube are deliberately not audio sources: their terms (and DRM) forbid
mixing or extracting their audio. Spotify is used only to read playlists, which are
then matched to these sources (see spotify_service.py).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import httpx

from app.models.track import OnlineTrack

AUDIUS_API = "https://api.audius.co/v1"
JAMENDO_API = "https://api.jamendo.com/v3.0"
APP_NAME = "AI-DJ"
# Skip hour-long DJ sets and tiny clips: single songs mix best.
MIN_SECONDS = 60
MAX_SECONDS = 15 * 60


class MusicSourceError(Exception):
    """Raised when an online source cannot be searched or streamed."""


@dataclass(frozen=True)
class SourceStatus:
    name: str
    available: bool
    note: str


def jamendo_client_id() -> str | None:
    value = os.getenv("AI_DJ_JAMENDO_CLIENT_ID", "").strip()
    return value or None


def source_statuses() -> list[SourceStatus]:
    return [
        SourceStatus("audius", True, "Free full-track streaming, no key needed."),
        SourceStatus(
            "jamendo",
            jamendo_client_id() is not None,
            "Creative Commons music. Set AI_DJ_JAMENDO_CLIENT_ID (free at devportal.jamendo.com) to enable.",
        ),
    ]


class MusicSourceClient:
    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http

    async def search(self, source: str, query: str, limit: int = 20) -> list[OnlineTrack]:
        if source == "audius":
            return await self._audius_search(query, limit)
        if source == "jamendo":
            return await self._jamendo_search(query, limit)
        raise MusicSourceError(f"Unknown music source '{source}'.")

    async def trending(self, source: str, genre: str | None, limit: int = 20) -> list[OnlineTrack]:
        if source != "audius":
            return await self.search(source, genre or "", limit)
        params = {"time": "week", "limit": str(min(100, limit * 2)), "app_name": APP_NAME}
        if genre:
            params["genre"] = audius_genre(genre)
        data = await self._get_json(f"{AUDIUS_API}/tracks/trending", params)
        return _limit([_from_audius(item) for item in data.get("data", [])], limit)

    async def get(self, source: str, source_id: str) -> OnlineTrack:
        if source == "audius":
            data = await self._get_json(f"{AUDIUS_API}/tracks/{source_id}", {"app_name": APP_NAME})
            track = _from_audius(data.get("data") or {})
            if not track:
                raise MusicSourceError("That Audius track is not available.")
            return track
        if source == "jamendo":
            results = await self._jamendo_tracks({"id": source_id})
            if not results:
                raise MusicSourceError("That Jamendo track is not available.")
            return results[0]
        raise MusicSourceError(f"Unknown music source '{source}'.")

    async def _audius_search(self, query: str, limit: int) -> list[OnlineTrack]:
        params = {"query": query, "limit": str(min(100, limit * 3)), "app_name": APP_NAME}
        data = await self._get_json(f"{AUDIUS_API}/tracks/search", params)
        return _limit([_from_audius(item) for item in data.get("data", [])], limit)

    async def _jamendo_search(self, query: str, limit: int) -> list[OnlineTrack]:
        params = {"search": query, "limit": str(min(200, limit * 2)), "order": "popularity_total"}
        return _limit(await self._jamendo_tracks(params), limit)

    async def _jamendo_tracks(self, extra: dict[str, str]) -> list[OnlineTrack]:
        client_id = jamendo_client_id()
        if not client_id:
            raise MusicSourceError("Jamendo needs AI_DJ_JAMENDO_CLIENT_ID (a free key from devportal.jamendo.com).")
        params = {"client_id": client_id, "format": "json", "audioformat": "mp32", "include": "musicinfo+licenses"}
        params.update(extra)
        data = await self._get_json(f"{JAMENDO_API}/tracks/", params)
        return [track for track in (_from_jamendo(item) for item in data.get("results", [])) if track]

    async def _get_json(self, url: str, params: dict[str, str]) -> dict:
        try:
            if self._http is not None:
                response = await self._http.get(url, params=params)
            else:
                async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                    response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise MusicSourceError(f"The music service returned HTTP {exc.response.status_code}.") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise MusicSourceError("Could not reach the music service. Check your internet connection.") from exc


def _limit(tracks: list[OnlineTrack | None], limit: int) -> list[OnlineTrack]:
    return [track for track in tracks if track][:limit]


def _from_audius(item: dict) -> OnlineTrack | None:
    if not item or not item.get("id"):
        return None
    duration = float(item.get("duration") or 0)
    gated = bool(item.get("stream_conditions")) or (item.get("access") or {}).get("stream") is False
    if not item.get("is_streamable", True) or gated or item.get("is_unlisted"):
        return None
    if not MIN_SECONDS <= duration <= MAX_SECONDS:
        return None
    artist = (item.get("user") or {}).get("name") or "Unknown artist"
    artwork = item.get("artwork") or {}
    permalink = item.get("permalink") or ""
    return OnlineTrack(
        source="audius",
        source_id=str(item["id"]),
        title=str(item.get("title") or "Untitled").strip(),
        artist=artist,
        genre=_clean_genre(item.get("genre")),
        duration_seconds=duration,
        artwork_url=artwork.get("480x480") or artwork.get("150x150"),
        page_url=f"https://audius.co{permalink}" if permalink else None,
        license=item.get("license") or "Audius: stream with credit to the artist",
        stream_url=f"{AUDIUS_API}/tracks/{item['id']}/stream?app_name={APP_NAME}",
    )


def _from_jamendo(item: dict) -> OnlineTrack | None:
    audio = item.get("audio")
    duration = float(item.get("duration") or 0)
    if not audio or not MIN_SECONDS <= duration <= MAX_SECONDS:
        return None
    tags = ((item.get("musicinfo") or {}).get("tags") or {}).get("genres") or []
    return OnlineTrack(
        source="jamendo",
        source_id=str(item.get("id")),
        title=str(item.get("name") or "Untitled").strip(),
        artist=item.get("artist_name") or "Unknown artist",
        genre=_clean_genre(tags[0] if tags else None),
        duration_seconds=duration,
        artwork_url=item.get("album_image") or item.get("image"),
        page_url=item.get("shareurl"),
        license=item.get("license_ccurl") or "Creative Commons (see track page)",
        stream_url=audio,
    )


_GENRE_MAP = {
    "house": "House",
    "deep house": "House",
    "tech house": "House",
    "progressive house": "House",
    "techno": "Techno",
    "trance": "Trance",
    "drum & bass": "Drum & Bass",
    "drumnbass": "Drum & Bass",
    "dubstep": "Dubstep",
    "electronic": "Electronic / Dance",
    "electro": "Electronic / Dance",
    "dance": "Electronic / Dance",
    "edm": "Electronic / Dance",
    "hip-hop/rap": "Hip-Hop / Rap",
    "hiphop": "Hip-Hop / Rap",
    "hip-hop": "Hip-Hop / Rap",
    "rap": "Hip-Hop / Rap",
    "trap": "Hip-Hop / Rap",
    "r&b/soul": "R&B / Soul",
    "rnb": "R&B / Soul",
    "soul": "R&B / Soul",
    "pop": "Pop",
    "latin": "Latin",
    "reggae": "Reggae / Dancehall",
    "dancehall": "Reggae / Dancehall",
    "afrobeats": "Afrobeats / Amapiano",
    "rock": "Rock",
    "jazz": "Jazz",
    "country": "Country",
}

# App genre -> Audius genre name for trending lookups.
_AUDIUS_GENRES = {
    "House": "House",
    "Techno": "Techno",
    "Trance": "Trance",
    "Drum & Bass": "Drum & Bass",
    "Dubstep": "Dubstep",
    "Electronic / Dance": "Electronic",
    "Hip-Hop / Rap": "Hip-Hop/Rap",
    "R&B / Soul": "R&B/Soul",
    "Pop": "Pop",
    "Latin": "Latin",
    "Reggae / Dancehall": "Reggae",
    "Afrobeats / Amapiano": "World",
    "Rock": "Rock",
    "Jazz": "Jazz",
    "Country": "Country",
}


def _clean_genre(raw: str | None) -> str:
    text = re.sub(r"\s+", " ", (raw or "").strip())
    if not text:
        return "Open Format"
    return _GENRE_MAP.get(text.lower(), text)


def audius_genre(app_genre: str) -> str:
    return _AUDIUS_GENRES.get(app_genre, app_genre)


def display_title(track: OnlineTrack) -> str:
    """'Artist - Title', without doubling an artist name that is already in the title."""
    if track.title.lower().startswith(track.artist.lower()):
        return track.title
    return f"{track.artist} - {track.title}"


def import_file_name(track: OnlineTrack) -> str:
    return f"{display_title(track)}.mp3"
