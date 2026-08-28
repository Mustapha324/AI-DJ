from __future__ import annotations

import re
from pathlib import Path

from app.models.track import TrackAnalysis

try:
    from mutagen import File as MutagenFile
except ImportError:  # The app still runs when optional metadata support is unavailable.
    MutagenFile = None


GENRE_ALIASES = {
    "dnb": "Drum & Bass",
    "drum n bass": "Drum & Bass",
    "drum and bass": "Drum & Bass",
    "hip hop": "Hip-Hop / Rap",
    "hip-hop": "Hip-Hop / Rap",
    "rap": "Hip-Hop / Rap",
    "rnb": "R&B / Soul",
    "r&b": "R&B / Soul",
    "rhythm and blues": "R&B / Soul",
    "edm": "Electronic / Dance",
    "electronic": "Electronic / Dance",
    "dance": "Electronic / Dance",
    "afrobeats": "Afrobeats",
    "afrobeat": "Afrobeats",
}

FILENAME_GENRES = (
    (("drum and bass", "drum n bass", "dnb"), "Drum & Bass"),
    (("tech house", "deep house", "afro house", "house"), "House"),
    (("techno",), "Techno"),
    (("trance",), "Trance"),
    (("dubstep",), "Dubstep"),
    (("hip hop", "hip-hop", "rap", "trap"), "Hip-Hop / Rap"),
    (("r&b", "rnb", "soul"), "R&B / Soul"),
    (("reggaeton", "salsa", "bachata", "latin"), "Latin"),
    (("dancehall", "reggae"), "Reggae / Dancehall"),
    (("afrobeats", "afrobeat", "amapiano"), "Afrobeats / Amapiano"),
    (("rock", "metal", "punk"), "Rock"),
    (("jazz",), "Jazz"),
    (("country",), "Country"),
    (("pop",), "Pop"),
    (("edm", "electronic", "dance", "club"), "Electronic / Dance"),
)


def classify_track_genre(analysis: TrackAnalysis, audio_path: Path | None = None) -> TrackAnalysis:
    embedded = _embedded_genre(audio_path) if audio_path else None
    if embedded:
        analysis.genre = embedded
        analysis.genre_source = "embedded"
        analysis.genre_confidence = 0.98
        return analysis

    filename_genre = _filename_genre(f"{analysis.title} {analysis.file_name}")
    if filename_genre:
        analysis.genre = filename_genre
        analysis.genre_source = "filename"
        analysis.genre_confidence = 0.84
        return analysis

    analysis.genre, analysis.genre_confidence = _audio_profile_genre(analysis)
    analysis.genre_source = "audio_profile" if analysis.genre != "Open Format" else "fallback"
    return analysis


def _embedded_genre(audio_path: Path | None) -> str | None:
    if not audio_path or MutagenFile is None:
        return None
    try:
        audio = MutagenFile(audio_path, easy=True)
        if not audio or not audio.tags:
            return None
        values = audio.tags.get("genre") or audio.tags.get("GENRE") or []
        if isinstance(values, str):
            values = [values]
        for value in values:
            cleaned = re.split(r"[;,]", str(value), maxsplit=1)[0].strip()
            if cleaned:
                return _canonical_genre(cleaned)
    except Exception:
        return None
    return None


def _filename_genre(text: str) -> str | None:
    normalized = re.sub(r"[_\-.]+", " ", text.lower())
    normalized = " ".join(normalized.split())
    for keywords, genre in FILENAME_GENRES:
        if any(re.search(rf"\b{re.escape(keyword)}\b", normalized) for keyword in keywords):
            return genre
    return None


def _audio_profile_genre(track: TrackAnalysis) -> tuple[str, float]:
    bpm = track.estimated_bpm or 0.0
    energy = min(1.0, track.overall_rms_energy / 0.24) if track.overall_rms_energy > 0 else 0.0
    brightness = track.spectral_centroid
    crossing = track.zero_crossing_rate

    if 165 <= bpm <= 180 and (brightness >= 1700 or crossing >= 0.08):
        return "Drum & Bass", 0.66
    if 128 <= bpm <= 150 and energy >= 0.42:
        return "Techno / Trance", 0.6
    if 118 <= bpm < 132:
        return "House", 0.62
    if 100 <= bpm < 118 and brightness >= 1400:
        return "Pop / Dance", 0.54
    if 70 <= bpm < 105 and brightness < 2200:
        return "Hip-Hop / R&B", 0.5
    if 132 <= bpm < 165 and crossing >= 0.1:
        return "Electronic / Dance", 0.48
    return "Open Format", 0.3


def _canonical_genre(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    alias = GENRE_ALIASES.get(cleaned.lower())
    if alias:
        return alias
    return cleaned[:64]
