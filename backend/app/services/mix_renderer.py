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

    outgoing = current[-fade:].copy()
    if transition:
        outgoing = _prepare_outgoing_transition(outgoing, sample_rate, transition)
    overlap = _dj_blend_overlap(outgoing, incoming[:fade], sample_rate, transition)
    if transition and transition.sfx:
        overlap = _add_transition_sfx(
            overlap,
            sample_rate,
            [name for name in transition.sfx if name not in {"echo_tail", "echo_freeze", "loop_roll", "brake_cut"}],
        )
    return np.concatenate([current[:-fade], overlap, incoming[fade:]])


def _prepare_outgoing_transition(
    outgoing: np.ndarray,
    sample_rate: int,
    transition: MixTransition,
) -> np.ndarray:
    prepared = outgoing.copy()
    if transition.outgoing_loop_seconds > 0 and transition.background_tail_seconds > 0:
        prepared = _layer_outgoing_loop(
            prepared,
            sample_rate,
            transition.outgoing_loop_seconds,
            transition.background_tail_seconds,
        )
    if "loop_roll" in transition.sfx and transition.outgoing_loop_seconds <= 0:
        prepared = _add_loop_roll(prepared, sample_rate)
    if "echo_tail" in transition.sfx:
        prepared = _add_echo_tail(prepared, sample_rate)
    if "echo_freeze" in transition.sfx:
        prepared = _add_echo_freeze(prepared, sample_rate)
    if "brake_cut" in transition.sfx:
        prepared = _add_brake_cut(prepared, sample_rate)
    return prepared.astype(np.float32)


def _layer_outgoing_loop(
    audio: np.ndarray,
    sample_rate: int,
    loop_seconds: float,
    tail_seconds: float,
) -> np.ndarray:
    if audio.size < 64 or loop_seconds <= 0 or tail_seconds <= 0:
        return audio
    loop_samples = min(max(32, int(loop_seconds * sample_rate)), max(32, len(audio) // 3))
    tail_samples = min(max(loop_samples, int(tail_seconds * sample_rate)), len(audio))
    tail_start = len(audio) - tail_samples
    source_end = min(len(audio), tail_start + loop_samples)
    snippet = audio[max(0, source_end - loop_samples) : source_end].copy()
    if snippet.size < 32:
        return audio

    edge = min(max(4, int(sample_rate * 0.012)), len(snippet) // 4)
    if edge > 1:
        snippet[:edge] *= np.linspace(0.0, 1.0, edge, dtype=np.float32)
        snippet[-edge:] *= np.linspace(1.0, 0.0, edge, dtype=np.float32)
    repeated = np.resize(snippet, tail_samples).astype(np.float32)
    progress = np.linspace(0.0, 1.0, tail_samples, dtype=np.float32)
    amount = 0.18 + (0.42 * np.sin(np.pi * progress))
    layered = audio.copy()
    layered[tail_start:] = (audio[tail_start:] * (1.0 - amount)) + (repeated * amount)
    return layered.astype(np.float32)


def _dj_blend_overlap(
    outgoing: np.ndarray,
    incoming: np.ndarray,
    sample_rate: int,
    transition: MixTransition | None = None,
) -> np.ndarray:
    fade = min(len(outgoing), len(incoming))
    if fade == 0:
        return np.asarray([], dtype=np.float32)

    theta = np.linspace(0.0, np.pi / 2.0, fade, dtype=np.float32)
    technique = transition.technique if transition else "phrase_blend"
    fade_out = np.cos(theta)
    fade_in = np.sin(theta)
    if technique in {"phrase_blend", "loop_echo_out"}:
        fade_out = np.clip(fade_out, 0.0, 1.0) ** 0.72
        fade_in = fade_in**1.08
    elif technique == "quick_cut":
        progress = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        fade_out = np.clip(1.0 - (progress / 0.52), 0.0, 1.0)
        fade_in = np.clip((progress - 0.16) / 0.48, 0.0, 1.0) ** 0.8

    out_low, out_high = _split_low_high(outgoing[:fade], sample_rate)
    in_low, in_high = _split_low_high(incoming[:fade], sample_rate)

    progress = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    swap = transition.bass_swap_position if transition else 0.5
    outgoing_bass = 1.0 - _smoothstep(progress, max(0.0, swap - 0.16), swap)
    incoming_bass = _smoothstep(progress, swap, min(1.0, swap + 0.16))
    mids_out = fade_out * (1.0 - (0.12 * progress))
    mids_in = fade_in * (0.88 + (0.12 * progress))

    overlap = (out_high * mids_out) + (in_high * mids_in) + (out_low * outgoing_bass) + (in_low * incoming_bass)
    return _micro_duck(_prevent_clipping(overlap.astype(np.float32)))


def _smoothstep(values: np.ndarray, edge_start: float, edge_end: float) -> np.ndarray:
    width = max(edge_end - edge_start, 1e-6)
    scaled = np.clip((values - edge_start) / width, 0.0, 1.0)
    return (scaled * scaled * (3.0 - (2.0 * scaled))).astype(np.float32)


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
    if "filter_sweep" in sfx_names:
        effected = _add_filter_sweep(effected, sample_rate)
    if "echo_tail" in sfx_names:
        effected = _add_echo_tail(effected, sample_rate)
    if "reverb_riser" in sfx_names:
        effected += _reverb_riser(len(overlap), sample_rate, amplitude=0.022)
    if "reverse_swell" in sfx_names:
        effected += _reverse_swell(len(overlap), sample_rate, amplitude=0.024)
    if "loop_roll" in sfx_names:
        effected = _add_loop_roll(effected, sample_rate)
    if "echo_freeze" in sfx_names:
        effected = _add_echo_freeze(effected, sample_rate)
    if "brake_cut" in sfx_names:
        effected = _add_brake_cut(effected, sample_rate)
    if "noise_sweep" in sfx_names or "filter_sweep" in sfx_names:
        effected += _noise_sweep(len(overlap), sample_rate, amplitude=0.016)
    if "soft_sweep" in sfx_names:
        effected += _noise_sweep(len(overlap), sample_rate, amplitude=0.011)
    if "impact" in sfx_names:
        effected = _add_downbeat_impact(effected, sample_rate)
    return _prevent_clipping(effected.astype(np.float32))


def _add_filter_sweep(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if audio.size == 0:
        return audio
    low, high = _split_low_high(audio, sample_rate)
    progress = np.linspace(0.0, 1.0, len(audio), dtype=np.float32)
    low_curve = np.clip(1.0 - (0.2 * progress), 0.78, 1.0)
    high_curve = 0.9 + (0.18 * np.sin(np.pi * progress))
    swept = (low * low_curve) + (high * high_curve)
    return ((audio * 0.65) + (swept * 0.35)).astype(np.float32)


def _add_echo_tail(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if audio.size == 0:
        return audio
    delay = max(1, int(sample_rate * 0.18))
    wet = np.zeros_like(audio, dtype=np.float32)
    for tap in range(1, 5):
        offset = delay * tap
        if offset >= len(audio):
            break
        wet[offset:] += audio[:-offset] * (0.42 ** tap)
    envelope = np.linspace(0.0, 1.0, len(audio), dtype=np.float32) ** 1.7
    return (audio + (wet * envelope * 0.22)).astype(np.float32)


def _reverb_riser(length: int, sample_rate: int, amplitude: float) -> np.ndarray:
    if length <= 0:
        return np.asarray([], dtype=np.float32)
    progress = np.linspace(0.0, 1.0, length, dtype=np.float32)
    t = np.arange(length, dtype=np.float32) / sample_rate
    frequency = 520.0 + (3100.0 * (progress**1.4))
    phase = 2.0 * np.pi * np.cumsum(frequency) / sample_rate
    tone = np.sin(phase).astype(np.float32)
    texture = np.random.default_rng(24680).normal(0.0, 1.0, length).astype(np.float32)
    envelope = np.clip(progress**1.8, 0.0, 1.0) * np.sin(np.pi * progress)
    return ((tone * 0.35 + texture * 0.65) * envelope * amplitude).astype(np.float32)


def _reverse_swell(length: int, sample_rate: int, amplitude: float) -> np.ndarray:
    if length <= 0:
        return np.asarray([], dtype=np.float32)
    progress = np.linspace(0.0, 1.0, length, dtype=np.float32)
    t = np.arange(length, dtype=np.float32) / sample_rate
    tone = np.sin(2.0 * np.pi * (360.0 + 900.0 * progress) * t).astype(np.float32)
    noise = np.random.default_rng(97531).normal(0.0, 1.0, length).astype(np.float32)
    envelope = np.clip(progress**2.2, 0.0, 1.0)
    return ((tone * 0.18 + noise * 0.82) * envelope * amplitude).astype(np.float32)


def _add_loop_roll(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if audio.size < sample_rate * 0.3:
        return audio
    rolled = audio.copy()
    step = max(1, int(sample_rate * 0.125))
    start = int(len(audio) * 0.68)
    source_start = max(0, start - step)
    snippet = audio[source_start : source_start + step]
    if snippet.size == 0:
        return audio
    for position in range(start, len(audio), step):
        width = min(step, len(audio) - position, len(snippet))
        if width <= 0:
            break
        local_progress = (position - start) / max(len(audio) - start, 1)
        amount = min(0.42, 0.18 + (local_progress * 0.28))
        rolled[position : position + width] = (rolled[position : position + width] * (1.0 - amount)) + (
            snippet[:width] * amount
        )
    return rolled.astype(np.float32)


def _add_echo_freeze(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if audio.size < sample_rate * 0.35:
        return audio
    frozen = audio.copy()
    snippet_length = max(1, int(sample_rate * 0.16))
    start = max(0, int(len(audio) * 0.74) - snippet_length)
    snippet = audio[start : start + snippet_length]
    if snippet.size == 0:
        return audio
    tail_start = int(len(audio) * 0.74)
    for position in range(tail_start, len(audio), snippet_length):
        width = min(snippet_length, len(audio) - position, len(snippet))
        if width <= 0:
            break
        progress = (position - tail_start) / max(len(audio) - tail_start, 1)
        amount = 0.16 + (0.24 * progress)
        frozen[position : position + width] = (frozen[position : position + width] * (1.0 - amount)) + (
            snippet[:width] * amount
        )
    return frozen.astype(np.float32)


def _add_brake_cut(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if audio.size < sample_rate * 0.25:
        return audio
    braked = audio.copy()
    start = int(len(audio) * 0.86)
    tail = braked[start:]
    if tail.size == 0:
        return audio
    progress = np.linspace(0.0, 1.0, len(tail), dtype=np.float32)
    braked[start:] = tail * (1.0 - progress) ** 1.8
    return braked.astype(np.float32)


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
