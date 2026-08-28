from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

import librosa
import numpy as np
from fastapi import UploadFile

from app.config import Settings, ensure_storage_dirs
from app.models.style_profile import DJStyleProfile, ReferenceMixFeature, StyleProfileSummary
from app.services.track_service import InvalidAudioFileError, sanitize_file_name


class StyleProfileNotFoundError(Exception):
    """Raised when a requested DJ style profile does not exist."""


class ReferenceMixAnalysisError(Exception):
    """Raised when a reference DJ mix cannot be analyzed."""


class StyleProfileService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        ensure_storage_dirs(settings)

    async def train_from_uploads(
        self,
        uploads: list[UploadFile],
        *,
        name: str = "Default DJ Style",
        profile_id: str = "default",
    ) -> DJStyleProfile:
        if not uploads:
            raise InvalidAudioFileError("Upload at least one reference DJ mix.")

        features: list[ReferenceMixFeature] = []
        temp_paths: list[Path] = []
        try:
            for upload in uploads:
                path = await self._save_reference_temp(upload)
                temp_paths.append(path)
                features.append(_analyze_reference_mix(path, upload.filename or path.name))
        finally:
            for path in temp_paths:
                path.unlink(missing_ok=True)

        profile = _build_profile(features, name=name, profile_id=profile_id)
        self.save_profile(profile)
        return profile

    def save_profile(self, profile: DJStyleProfile) -> Path:
        path = self._profile_path(profile.profile_id)
        with path.open("w", encoding="utf-8") as output_file:
            json.dump(profile.model_dump(mode="json"), output_file, indent=2)
        return path

    def get_profile(self, profile_id: str = "default") -> DJStyleProfile:
        path = self._profile_path(profile_id)
        if not path.exists():
            raise StyleProfileNotFoundError(f"Style profile '{profile_id}' was not found.")
        with path.open("r", encoding="utf-8") as input_file:
            return DJStyleProfile.model_validate(json.load(input_file))

    def get_default_profile(self) -> DJStyleProfile | None:
        try:
            return self.get_profile("default")
        except StyleProfileNotFoundError:
            return None

    def list_profiles(self) -> list[StyleProfileSummary]:
        profiles: list[StyleProfileSummary] = []
        for profile_path in sorted(self.settings.style_profiles_dir.glob("*.json")):
            try:
                with profile_path.open("r", encoding="utf-8") as input_file:
                    profile = DJStyleProfile.model_validate(json.load(input_file))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            profiles.append(
                StyleProfileSummary(
                    profile_id=profile.profile_id,
                    name=profile.name,
                    reference_count=profile.reference_count,
                    default_transition_bars=profile.default_transition_bars,
                    max_play_seconds_per_track=profile.max_play_seconds_per_track,
                    transition_duration_seconds=profile.transition_duration_seconds,
                    sfx_density=profile.sfx_density,
                    effect_intensity=profile.effect_intensity,
                    transition_effects=profile.transition_effects,
                    transition_start_strategy=profile.transition_start_strategy,
                    updated_at=profile.updated_at,
                )
            )
        return profiles

    async def _save_reference_temp(self, upload: UploadFile) -> Path:
        if not upload.filename:
            raise InvalidAudioFileError("Reference mix must include a file name.")

        suffix = Path(upload.filename).suffix.lower()
        if suffix not in self.settings.allowed_audio_extensions:
            raise InvalidAudioFileError("Reference mixes must be WAV or MP3 files.")

        safe_name = sanitize_file_name(upload.filename)
        destination = self.settings.style_profiles_dir / f"reference_{uuid.uuid4().hex}_{safe_name}"
        bytes_written = 0
        try:
            with destination.open("wb") as output_file:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    bytes_written += len(chunk)
                    if bytes_written > self.settings.max_upload_size_bytes:
                        raise InvalidAudioFileError("Reference mix is larger than the configured upload limit.")
                    output_file.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

        if bytes_written == 0:
            destination.unlink(missing_ok=True)
            raise InvalidAudioFileError("Reference mix is empty.")
        return destination

    def _profile_path(self, profile_id: str) -> Path:
        safe_profile_id = sanitize_file_name(profile_id).lower()
        return self.settings.style_profiles_dir / f"{safe_profile_id}.json"


def _analyze_reference_mix(path: Path, original_name: str) -> ReferenceMixFeature:
    try:
        audio, sample_rate = librosa.load(path, sr=22_050, mono=True, duration=900)
    except Exception as exc:
        raise ReferenceMixAnalysisError(f"Could not decode reference mix '{original_name}'.") from exc

    if audio.size == 0:
        raise ReferenceMixAnalysisError(f"Reference mix '{original_name}' did not contain usable audio.")

    duration_seconds = float(librosa.get_duration(y=audio, sr=sample_rate))
    tempo, beat_frames = librosa.beat.beat_track(y=audio, sr=sample_rate, units="frames")
    bpm = float(np.asarray(tempo).reshape(-1)[0]) if np.size(tempo) else 0.0
    beat_times = librosa.frames_to_time(beat_frames, sr=sample_rate)
    beat_intervals = np.diff(beat_times) if len(beat_times) > 1 else np.asarray([])
    median_beat = float(np.median(beat_intervals)) if beat_intervals.size else (60.0 / bpm if bpm else 0.5)
    phrase_seconds = float(np.clip(median_beat * 16.0, 6.0, 45.0))

    rms = librosa.feature.rms(y=audio, frame_length=4096, hop_length=2048).reshape(-1)
    spectral_centroid = librosa.feature.spectral_centroid(y=audio, sr=sample_rate, hop_length=2048).reshape(-1)
    energy = _normalize(rms)
    energy_change = np.abs(np.diff(energy)) if energy.size > 1 else np.asarray([])
    raw_high_motion = np.abs(np.diff(_normalize(spectral_centroid))) if spectral_centroid.size > 1 else np.asarray([])
    high_motion = _normalize(raw_high_motion) if raw_high_motion.size else np.asarray([])
    combined_change = _combined_change(energy_change, high_motion)
    transition_times = _likely_transition_times(combined_change, sample_rate, hop_length=2048)
    spacings = np.diff(transition_times) if len(transition_times) > 1 else np.asarray([])
    dynamic_range = float(np.percentile(energy, 95) - np.percentile(energy, 20)) if energy.size else 0.0
    phrase_boundary_strength = _phrase_boundary_strength(transition_times, beat_times)

    return ReferenceMixFeature(
        file_name=sanitize_file_name(original_name),
        duration_seconds=round(duration_seconds, 3),
        estimated_bpm=round(bpm, 2) if bpm > 0 else None,
        beat_count=len(beat_times),
        phrase_seconds=round(phrase_seconds, 3),
        average_energy=round(float(np.mean(energy)) if energy.size else 0.0, 4),
        energy_change_rate=round(float(np.mean(combined_change)) if combined_change.size else 0.0, 4),
        spectral_motion_rate=round(float(np.mean(raw_high_motion)) if raw_high_motion.size else 0.0, 4),
        dynamic_range=round(dynamic_range, 4),
        phrase_boundary_strength=round(phrase_boundary_strength, 4),
        likely_transition_count=len(transition_times),
        average_transition_spacing_seconds=round(float(np.median(spacings)), 3) if spacings.size else None,
    )


def _build_profile(features: list[ReferenceMixFeature], name: str, profile_id: str) -> DJStyleProfile:
    now = datetime.now(timezone.utc)
    spacing_values = [feature.average_transition_spacing_seconds for feature in features if feature.average_transition_spacing_seconds]
    phrase_values = [feature.phrase_seconds for feature in features if feature.phrase_seconds > 0]
    change_values = [feature.energy_change_rate for feature in features]
    spectral_motion_values = [feature.spectral_motion_rate for feature in features]
    dynamic_range_values = [feature.dynamic_range for feature in features]
    phrase_strength_values = [feature.phrase_boundary_strength for feature in features]
    transition_density_values = [
        feature.likely_transition_count / max(feature.duration_seconds / 60.0, 1.0)
        for feature in features
        if feature.duration_seconds > 0
    ]
    beat_strength_values = [
        min(1.0, feature.beat_count / max(feature.duration_seconds / 0.6, 1.0))
        for feature in features
        if feature.duration_seconds > 0
    ]

    median_spacing = _median_or(spacing_values, 75.0)
    median_phrase = _median_or(phrase_values, 16.0)
    median_change = _median_or(change_values, 0.08)
    median_spectral_motion = _median_or(spectral_motion_values, 0.05)
    median_dynamic_range = _median_or(dynamic_range_values, 0.55)
    median_phrase_strength = _median_or(phrase_strength_values, 0.6)
    median_transition_density = _median_or(transition_density_values, 1.0)
    beat_strength = _median_or(beat_strength_values, 0.7)

    transition_seconds = float(np.clip(median_phrase * 0.42, 4.0, 8.0))
    default_transition_bars = _bars_from_seconds(transition_seconds, features)
    max_play_seconds = float(np.clip(median_spacing * 0.86, 35.0, 135.0))
    sfx_density = float(np.clip((median_change * 3.0) + 0.2, 0.15, 0.95))
    effect_intensity = float(
        np.clip(
            (median_change * 2.5)
            + (median_spectral_motion * 1.6)
            + (median_dynamic_range * 0.35)
            + (median_transition_density * 0.04),
            0.18,
            0.92,
        )
    )
    energy_smoothing = float(np.clip(1.0 - (median_change * 2.0), 0.25, 0.9))

    return DJStyleProfile(
        profile_id=profile_id,
        name=name,
        reference_count=len(features),
        reference_files=[feature.file_name for feature in features],
        default_transition_bars=default_transition_bars,
        phrase_bars=4 if median_phrase < 18 else 8,
        max_play_seconds_per_track=round(max_play_seconds, 3),
        transition_duration_seconds=round(transition_seconds, 3),
        sfx_density=round(sfx_density, 3),
        effect_intensity=round(effect_intensity, 3),
        transition_effects=_effect_palette(
            effect_intensity,
            median_change,
            median_spectral_motion,
            median_transition_density,
            beat_strength,
        ),
        transition_start_strategy="phrase_boundary_low_energy" if median_phrase_strength >= 0.45 else "energy_change_cue",
        cue_point_sensitivity=round(float(np.clip((median_phrase_strength * 0.55) + (median_change * 1.8), 0.25, 0.95)), 3),
        energy_smoothing=round(energy_smoothing, 3),
        beat_alignment_strength=round(float(np.clip(beat_strength, 0.3, 1.0)), 3),
        features=features,
        created_at=now,
        updated_at=now,
    )


def _normalize(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values.astype(float)
    minimum = float(np.min(values))
    maximum = float(np.max(values))
    if math.isclose(maximum, minimum):
        return np.zeros_like(values, dtype=float)
    return np.clip((values - minimum) / (maximum - minimum), 0.0, 1.0)


def _combined_change(energy_change: np.ndarray, high_motion: np.ndarray) -> np.ndarray:
    if energy_change.size == 0:
        return np.asarray([], dtype=float)
    length = min(energy_change.size, high_motion.size) if high_motion.size else energy_change.size
    if length == 0:
        return np.asarray([], dtype=float)
    high = high_motion[:length] if high_motion.size else np.zeros(length)
    return (energy_change[:length] * 0.7) + (high * 0.3)


def _likely_transition_times(changes: np.ndarray, sample_rate: int, hop_length: int) -> list[float]:
    if changes.size < 4:
        return []
    threshold = float(np.percentile(changes, 88))
    min_gap_seconds = 28.0
    min_gap_frames = max(1, int(min_gap_seconds / (hop_length / sample_rate)))
    transition_indices: list[int] = []
    last_index = -min_gap_frames
    for index, value in enumerate(changes):
        if value >= threshold and index - last_index >= min_gap_frames:
            transition_indices.append(index)
            last_index = index
    return [round(float(librosa.frames_to_time(index, sr=sample_rate, hop_length=hop_length)), 3) for index in transition_indices]


def _bars_from_seconds(seconds: float, features: list[ReferenceMixFeature]) -> int:
    bpm_values = [feature.estimated_bpm for feature in features if feature.estimated_bpm]
    median_bpm = _median_or(bpm_values, 100.0)
    seconds_per_bar = 4.0 * (60.0 / median_bpm)
    bars = round(seconds / seconds_per_bar) if seconds_per_bar > 0 else 8
    if bars <= 4:
        return 4
    if bars <= 8:
        return 8
    if bars <= 12:
        return 12
    return 16


def _phrase_boundary_strength(transition_times: list[float], beat_times: np.ndarray) -> float:
    if not transition_times or len(beat_times) < 8:
        return 0.0
    beat_indices = [int(np.argmin(np.abs(beat_times - transition_time))) for transition_time in transition_times]
    boundary_hits = sum(1 for beat_index in beat_indices if beat_index % 16 <= 1 or beat_index % 16 >= 15)
    return boundary_hits / max(len(beat_indices), 1)


def _effect_palette(
    effect_intensity: float,
    change_rate: float,
    spectral_motion: float,
    transition_density: float,
    beat_strength: float,
) -> list[str]:
    effects = ["filter_sweep", "bass_swap"]
    if effect_intensity >= 0.32:
        effects.append("echo_tail")
    if effect_intensity >= 0.45 or spectral_motion >= 0.08:
        effects.append("reverb_riser")
    if beat_strength >= 0.72 and transition_density >= 0.8:
        effects.append("loop_roll")
    if effect_intensity >= 0.58 or spectral_motion >= 0.09:
        effects.append("reverse_swell")
    if effect_intensity >= 0.6 and beat_strength >= 0.72:
        effects.append("echo_freeze")
    if effect_intensity >= 0.7 and transition_density >= 1.2:
        effects.append("brake_cut")
    if effect_intensity >= 0.5 or change_rate >= 0.1:
        effects.append("impact")
    return effects


def _median_or(values: list[float | int | None], fallback: float) -> float:
    cleaned = [float(value) for value in values if value is not None]
    if not cleaned:
        return fallback
    return float(np.median(cleaned))
