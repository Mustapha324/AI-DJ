from __future__ import annotations

import asyncio
import hashlib
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.models.track import OnlineTrack, SpotifySong
from app.services.music_sources import MusicSourceClient, _from_audius, display_title, import_file_name
from app.services.spotify_service import SpotifyLibrary, SpotifySession, match_songs


def _audius_item(track_id: str, title: str, duration: int, **extra) -> dict:
    item = {
        "id": track_id,
        "title": title,
        "genre": "Deep House",
        "duration": duration,
        "is_streamable": True,
        "permalink": f"/artist/{track_id}",
        "user": {"name": "DJ Test"},
        "artwork": {"480x480": "https://img/480.jpg"},
        "license": "All rights reserved",
    }
    item.update(extra)
    return item


def test_audius_results_skip_long_sets_and_gated_tracks():
    assert _from_audius(_audius_item("a", "Song", 240)).genre == "House"
    assert _from_audius(_audius_item("b", "3 hour set", 3 * 3600)) is None
    assert _from_audius(_audius_item("c", "Gated", 200, stream_conditions={"usdc_purchase": {}})) is None
    assert _from_audius(_audius_item("d", "Clip", 20)) is None


def test_display_title_does_not_double_the_artist():
    track = OnlineTrack(source="audius", source_id="x", title="DJ Test - Song", artist="DJ Test", duration_seconds=200, stream_url="u")
    assert display_title(track) == "DJ Test - Song"
    assert import_file_name(track).endswith(".mp3")


def test_audius_search_uses_public_api():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"data": [_audius_item("a1", "Groove", 300), _audius_item("a2", "Long", 5000)]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await MusicSourceClient(http).search("audius", "groove", 5)

    results = asyncio.run(run())
    assert [track.source_id for track in results] == ["a1"]
    assert "api.audius.co/v1/tracks/search" in seen["url"]
    assert results[0].stream_url.endswith("/tracks/a1/stream?app_name=AI-DJ")


def test_import_online_song_keeps_credit_and_dedupes(client, make_synthetic_wav_bytes, monkeypatch):
    from app.api.sources import get_music_source_client
    from app.main import app
    from app.services.track_service import SavedUpload, TrackService

    online = OnlineTrack(
        source="audius",
        source_id="abc",
        title="Night Drive",
        artist="Test Artist",
        genre="House",
        duration_seconds=120,
        page_url="https://audius.co/test/night-drive",
        license="All rights reserved",
        stream_url="https://api.audius.co/v1/tracks/abc/stream",
    )

    class FakeSources:
        async def get(self, source, source_id):
            return online

    audio = make_synthetic_wav_bytes(440.0, duration_seconds=6.0)

    async def fake_download(self, url, track_id, file_name=None):
        path = self.settings.uploads_dir / f"{track_id}_night-drive.wav"
        path.write_bytes(audio)
        return SavedUpload(path=path, safe_file_name="night-drive.wav", content_hash=hashlib.sha256(audio).hexdigest(), size_bytes=len(audio))

    monkeypatch.setattr(TrackService, "save_remote_audio_for_analysis", fake_download)
    app.dependency_overrides[get_music_source_client] = lambda: FakeSources()

    first = client.post("/api/sources/import", json={"source": "audius", "source_id": "abc"})
    second = client.post("/api/sources/import", json={"source": "audius", "source_id": "abc"})

    assert first.status_code == 201
    track = first.json()
    assert track["title"] == "Test Artist - Night Drive"
    assert track["source"] == "audius" and track["source_url"].startswith("https://audius.co/")
    assert track["genre"] == "House" and track["genre_source"] == "online"
    assert second.json()["track_id"] == track["track_id"]
    library = client.get("/api/tracks").json()
    assert library[0]["artist"] == "Test Artist"


def test_sources_endpoint_lists_audius_and_jamendo(client, monkeypatch):
    monkeypatch.delenv("AI_DJ_JAMENDO_CLIENT_ID", raising=False)
    sources = {item["name"]: item for item in client.get("/api/sources").json()}
    assert sources["audius"]["available"] is True
    assert sources["jamendo"]["available"] is False


def test_spotify_login_uses_pkce_and_stores_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DJ_SPOTIFY_CLIENT_ID", "client-123")
    session = SpotifySession(tmp_path)
    url = urlparse(session.login_url())
    query = parse_qs(url.query)
    assert url.netloc == "accounts.spotify.com"
    assert query["code_challenge_method"] == ["S256"] and query["client_id"] == ["client-123"]
    assert "client_secret" not in query

    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["authorization_code"] and form["code_verifier"][0]
        return httpx.Response(200, json={"access_token": "tok", "refresh_token": "ref", "expires_in": 3600})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await SpotifySession(tmp_path).finish_login("code", query["state"][0], http)

    asyncio.run(run())
    assert SpotifySession(tmp_path).connected()

    with pytest.raises(Exception):
        asyncio.run(SpotifySession(tmp_path).finish_login("code", "wrong-state"))


def test_spotify_playlist_is_matched_to_mixable_copies(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DJ_SPOTIFY_CLIENT_ID", "client-123")
    session = SpotifySession(tmp_path)
    session._save_tokens({"access_token": "tok", "refresh_token": "ref", "expires_in": 3600})

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        if request.url.path.endswith("/items"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"track": {"type": "track", "name": "Night Drive (feat. Someone)", "artists": [{"name": "Test Artist"}], "duration_ms": 200000}},
                        {"track": {"type": "track", "name": "Totally Unknown", "artists": [{"name": "Nobody"}], "duration_ms": 180000}},
                        {"track": {"type": "episode", "name": "A podcast"}},
                    ]
                },
            )
        return httpx.Response(200, json={"items": [{"id": "pl1", "name": "Party", "tracks": {"total": 3}, "images": []}]})

    class FakeSources:
        async def search(self, source, query, limit):
            if "Night Drive" in query:
                return [
                    OnlineTrack(source="audius", source_id="x1", title="Something Else", artist="Other", duration_seconds=200, stream_url="u1"),
                    OnlineTrack(source="audius", source_id="x2", title="Night Drive", artist="Test Artist", duration_seconds=205, stream_url="u2"),
                ]
            return [OnlineTrack(source="audius", source_id="z", title="Random", artist="Z", duration_seconds=100, stream_url="u")]

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            library = SpotifyLibrary(session, http)
            playlists = await library.playlists()
            songs = await library.playlist_songs("pl1")
            return playlists, await match_songs(songs, [], FakeSources())

    playlists, matches = asyncio.run(run())
    assert playlists[0].name == "Party" and playlists[0].song_count == 3
    assert [match.song.title for match in matches] == ["Night Drive (feat. Someone)", "Totally Unknown"]
    assert matches[0].online and matches[0].online.source_id == "x2"
    assert matches[1].online is None


def test_spotify_status_explains_setup(client, monkeypatch):
    monkeypatch.delenv("AI_DJ_SPOTIFY_CLIENT_ID", raising=False)
    status = client.get("/api/spotify/status").json()
    assert status["configured"] is False
    assert status["redirect_uri"].endswith("/api/spotify/callback")
    assert client.get("/api/spotify/login", follow_redirects=False).headers["location"].startswith("/?spotify_error=")
