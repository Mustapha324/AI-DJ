from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

from app.config import Settings
from app.models.mix import MixPlan, MixTransition
from app.services.job_service import JobService
from app.services.track_service import TrackNotFoundError, TrackService


class MixRenderError(Exception):
    """Raised when a playable mix file cannot be rendered."""


@dataclass(frozen=True)
class RenderedMix:
    output_path: Path
    duration_seconds: float


class MixRenderer:
    def __init__(
        self,
        settings: Settings,
        track_service: TrackService,
        job_service: JobService | None = None,
    ) -> None:
        self.settings = settings
        self.track_service = track_service
        self.job_service = job_service

    def render(self, plan: MixPlan, output_path: Path, job_id: str | None = None) -> RenderedMix:
        if len(plan.placements) < 2:
            raise MixRenderError("A rendered mix needs at least two tracks.")

        sample_rate = self.settings.render_sample_rate
        rendered: np.ndarray | None = None

        try:
            for index, placement in enumerate(plan.placements):
                if job_id and self.job_service:
                    self.job_service.update_job(
                        job_id,
                        status="rendering",
                        progress=int((index / len(plan.placements)) * 90),
                        message=f"Rendering track {index + 1} of {len(plan.placements)}.",
                    )

                source_path = self.track_service.get_uploaded_audio_path(placement.track_id)
                audio = _load_audio(source_path, sample_rate)
                segment = _slice_audio(audio, sample_rate, placement.source_start_time, placement.source_end_time)
                if segment.size == 0:
                    raise MixRenderError(f"Track '{placement.track_id}' has no usable audio in the planned segment.")

                segment = _normalize_rms(segment)
                transition = _incoming_transition(plan, placement.track_id)
                if transition and transition.bpm_adjustment_percent:
                    segment = _time_stretch_if_safe(segment, transition.bpm_adjustment_percent)

                if rendered is None:
                    rendered = segment
                else:
                    fade_seconds = transition.duration_seconds if transition else 0.0
                    rendered = _append_with_crossfade(
                        rendered,
                        segment,
                        int(fade_seconds * sample_rate),
                        sample_rate,
                        transition,
                    )

            if rendered is None or rendered.size == 0:
                raise MixRenderError("The rendered mix did not contain audio.")

            rendered = _fade_edges(rendered, sample_rate)
            rendered = _prevent_clipping(rendered)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(output_path, rendered.astype(np.float32), sample_rate)

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise MixRenderError("The mix file was not created.")

            duration = round(float(len(rendered) / sample_rate), 3)
            if job_id and self.job_service:
                self.job_service.update_job(
                    job_id,
                    status="completed",
                    progress=100,
                    message="Mix rendering completed.",
                )
            return RenderedMix(output_path=output_path, duration_seconds=duration)
        except (TrackNotFoundError, OSError, ValueError, RuntimeError) as exc:
            output_path.unlink(missing_ok=True)
            raise MixRenderError(str(exc)) from exc
        except Exception:
            output_path.unlink(missing_ok=True)
            raise


def _load_audio(path: Path, sample_rate: int) -> np.ndarray:
    try:
        audio, _ = librosa.load(path, sr=sample_rate, mono=True)
    except Exception as exc:
        raise MixRenderError("Unable to decode one of the source tracks for rendering.") from exc
    return np.asarray(audio, dtype=np.float32)


def _slice_audio(audio: np.ndarray, sample_rate: int, start_time: float, end_time: float) -> np.ndarray:
    start = max(0, int(start_time * sample_rate))
    end = min(len(audio), int(end_time * sample_rate))
    if end <= start:
        return np.asarray([], dtype=np.float32)
    return audio[start:end].copy()


def _normalize_rms(audio: np.ndarray, target_rms: float = 0.12) -> np.ndarray:
    rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
    if rms <= 1e-9:
        return audio
    gain = float(np.clip(target_rms / rms, 0.25, 4.0))
    return audio * gain


def _time_stretch_if_safe(audio: np.ndarray, bpm_adjustment_percent: float) -> np.ndarray:
    rate = 1.0 + (bpm_adjustment_percent / 100.0)
    if not 0.92 <= rate <= 1.08 or audio.size < 2048:
        return audio
    try:
        return librosa.effects.time_stretch(audio, rate=rate).astype(np.float32)
    except Exception:
        return audio


def _append_with_crossfade(
    current: np.ndarray,
    incoming: np.ndarray,
    fade_samples: int,
    sample_rate: int,
    transition: MixTransition | None,
) -> np.ndarray:
    fade = min(max(0, fade_samples), len(current), len(incoming))
    if fade == 0:
        return np.concatenate([current, incoming])

    overlap = _dj_blend_overlap(current[-fade:], incoming[:fade], sample_rate)
    if transition and transition.sfx:
        overlap = _add_transition_sfx(overlap, sample_rate, transition.sfx)
    return np.concatenate([current[:-fade], overlap, incoming[fade:]])


def _dj_blend_overlap(outgoing: np.ndarray, incoming: np.ndarray, sample_rate: int) -> np.ndarray:
    fade = min(len(outgoing), len(incoming))
    if fade == 0:
        return np.asarray([], dtype=np.float32)

    theta = np.linspace(0.0, np.pi / 2.0, fade, dtype=np.float32)
    fade_out = np.cos(theta)
    fade_in = np.sin(theta)

    out_low, out_high = _split_low_high(outgoing[:fade], sample_rate)
    in_low, in_high = _split_low_high(incoming[:fade], sample_rate)

    progress = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    outgoing_bass = np.clip(1.0 - (progress * 1.55), 0.0, 1.0)
    incoming_bass = np.clip((progress - 0.35) / 0.65, 0.0, 1.0)
    mids_out = fade_out * (1.0 - (0.12 * progress))
    mids_in = fade_in * (0.88 + (0.12 * progress))

    overlap = (out_high * mids_out) + (in_high * mids_in) + (out_low * outgoing_bass) + (in_low * incoming_bass)
    return _micro_duck(_prevent_clipping(overlap.astype(np.float32)))


def _split_low_high(audio: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    if audio.size < 32:
        return audio * 0.35, audio * 0.65
    cutoff = min(180.0, (sample_rate / 2.0) - 100.0)
    sos = butter(2, cutoff, btype="lowpass", fs=sample_rate, output="sos")
    low = sosfilt(sos, audio).astype(np.float32)
    high = (audio - low).astype(np.float32)
    return low, high


def _micro_duck(audio: np.ndarray) -> np.ndarray:
    if audio.size == 0:
        return audio
    progress = np.linspace(0.0, 1.0, len(audio), dtype=np.float32)
    duck = 1.0 - (0.08 * np.exp(-((progress - 0.86) ** 2) / 0.004))
    return (audio * duck).astype(np.float32)


def _add_transition_sfx(overlap: np.ndarray, sample_rate: int, sfx_names: list[str]) -> np.ndarray:
    if overlap.size == 0:
        return overlap

    effected = overlap.copy()
    if "noise_sweep" in sfx_names:
        effected += _noise_sweep(len(overlap), sample_rate, amplitude=0.035)
    if "soft_sweep" in sfx_names:
        effected += _noise_sweep(len(overlap), sample_rate, amplitude=0.018)
    if "impact" in sfx_names:
        effected = _add_downbeat_impact(effected, sample_rate)
    return effected.astype(np.float32)


def _noise_sweep(length: int, sample_rate: int, amplitude: float) -> np.ndarray:
    if length <= 0:
        return np.asarray([], dtype=np.float32)

    t = np.arange(length, dtype=np.float32) / sample_rate
    duration = max(length / sample_rate, 1e-6)
    progress = np.linspace(0.0, 1.0, length, dtype=np.float32)
    frequency = 700.0 + (5200.0 * progress)
    phase = 2.0 * np.pi * np.cumsum(frequency) / sample_rate
    tone = np.sin(phase).astype(np.float32)
    noise = np.random.default_rng(12345).normal(0.0, 1.0, length).astype(np.float32)
    envelope = np.maximum(np.sin(np.pi * progress), 0.0) ** 1.6
    shimmer = (tone * 0.65) + (noise * 0.35)
    return (shimmer * envelope * amplitude * min(1.0, duration / 2.0)).astype(np.float32)


def _add_downbeat_impact(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    impact_length = min(len(audio), int(sample_rate * 0.65))
    if impact_length <= 0:
        return audio

    start = len(audio) - impact_length
    t = np.arange(impact_length, dtype=np.float32) / sample_rate
    decay = np.exp(-6.0 * t).astype(np.float32)
    low_hit = np.sin(2.0 * np.pi * 58.0 * t).astype(np.float32) * decay * 0.08
    click = np.random.default_rng(54321).normal(0.0, 1.0, impact_length).astype(np.float32) * decay * 0.01
    audio[start:] += low_hit + click
    return audio


def _fade_edges(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if audio.size == 0:
        return audio
    faded = audio.copy()
    fade_samples = min(int(sample_rate * 2), len(faded) // 4)
    if fade_samples <= 1:
        return faded
    fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    faded[:fade_samples] *= fade_in
    faded[-fade_samples:] *= fade_out
    return faded


def _prevent_clipping(audio: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= 0.98:
        return audio
    return audio * (0.98 / peak)


def _incoming_transition(plan: MixPlan, track_id: str):
    for transition in plan.transitions:
        if transition.target_track_id == track_id:
            return transition
    return None
