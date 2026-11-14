from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import butter, fftconvolve, sosfilt

from app.config import Settings
from app.models.mix import MixPlan, MixTransition
from app.services.automation_engine import render_automated_transition
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

    if transition and transition.automation:
        return _append_automated(current, incoming, fade, sample_rate, transition)

    outgoing = current[-fade:].copy()
    if transition:
        outgoing = _prepare_outgoing_transition(outgoing, sample_rate, transition)
    overlap = _dj_blend_overlap(outgoing, incoming[:fade], sample_rate, transition)
    after = incoming[fade:].copy()
    slams_in = bool(transition and transition.incoming_entry_position >= 0.99)
    if transition and transition.sfx:
        outgoing_only = {"echo_tail", "echo_freeze", "loop_roll", "brake_cut"}
        if transition.technique == "filter_blend":
            outgoing_only.add("filter_sweep")
        if slams_in:
            # The hit belongs on the new song's first downbeat, not before it.
            outgoing_only.add("impact")
            if "impact" in transition.sfx:
                after = _add_impact_at_start(after, sample_rate)
        overlap = _add_transition_sfx(
            overlap,
            sample_rate,
            [name for name in transition.sfx if name not in outgoing_only],
        )
    return np.concatenate([current[:-fade], overlap, after])


def _append_automated(
    current: np.ndarray,
    incoming: np.ndarray,
    fade: int,
    sample_rate: int,
    transition: MixTransition,
) -> np.ndarray:
    overlap, spill = render_automated_transition(current[-fade:], incoming[:fade], sample_rate, transition)
    after = incoming[fade:].copy()
    count = min(len(spill), len(after))
    after[:count] += spill[:count]
    if transition.sfx:
        slams_in = transition.incoming_entry_position >= 0.99
        names = [name for name in transition.sfx if not (slams_in and name == "impact")]
        overlap = _add_transition_sfx(overlap, sample_rate, names)
        if slams_in and "impact" in transition.sfx:
            after = _add_impact_at_start(after, sample_rate)
    return np.concatenate([current[:-fade], overlap, _prevent_clipping(after)])


def _prepare_outgoing_transition(
    outgoing: np.ndarray,
    sample_rate: int,
    transition: MixTransition,
) -> np.ndarray:
    prepared = outgoing.copy()
    if abs(transition.source_tempo_adjustment_percent) > 0.01:
        prepared = _tempo_ramp_outgoing(prepared, transition.source_tempo_adjustment_percent)
    if transition.technique == "filter_blend":
        prepared = _filter_outgoing_transition(prepared, sample_rate)
    special = _OUTGOING_MOVES.get(transition.technique)
    if special:
        prepared = special(prepared, sample_rate, transition.beat_seconds)
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

    edge = min(max(8, int(sample_rate * 0.035)), len(snippet) // 5)
    repeated = _repeat_with_crossfade(snippet, tail_samples, edge)
    progress = np.linspace(0.0, 1.0, tail_samples, dtype=np.float32)
    amount = 0.28 + (0.5 * np.sin(np.pi * progress))
    layered = audio.copy()
    layered[tail_start:] = (audio[tail_start:] * (1.0 - amount)) + (repeated * amount)
    return layered.astype(np.float32)


def _repeat_with_crossfade(snippet: np.ndarray, output_samples: int, overlap_samples: int) -> np.ndarray:
    if snippet.size == 0 or output_samples <= 0:
        return np.zeros(max(0, output_samples), dtype=np.float32)
    overlap = min(max(1, overlap_samples), max(1, len(snippet) // 3))
    repeated = np.zeros(output_samples, dtype=np.float32)
    written = min(len(snippet), output_samples)
    repeated[:written] = snippet[:written]
    position = written
    while position < output_samples:
        blend_start = max(0, position - overlap)
        blend_width = min(overlap, position, output_samples - blend_start, len(snippet))
        if blend_width > 0:
            fade = np.linspace(0.0, 1.0, blend_width, dtype=np.float32)
            repeated[blend_start : blend_start + blend_width] = (
                repeated[blend_start : blend_start + blend_width] * (1.0 - fade)
            ) + (snippet[:blend_width] * fade)
        copy_start = blend_width
        copy_width = min(len(snippet) - copy_start, output_samples - position)
        if copy_width <= 0:
            break
        repeated[position : position + copy_width] = snippet[copy_start : copy_start + copy_width]
        position += copy_width
    return repeated


def _dj_blend_overlap(
    outgoing: np.ndarray,
    incoming: np.ndarray,
    sample_rate: int,
    transition: MixTransition | None = None,
) -> np.ndarray:
    fade = min(len(outgoing), len(incoming))
    if fade == 0:
        return np.asarray([], dtype=np.float32)

    technique = transition.technique if transition else "phrase_blend"
    progress = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    entry = transition.incoming_entry_position if transition else 0.0
    if entry > 0.0:
        # Outgoing move already shaped its own exit; the next song comes in on the "1".
        # A few milliseconds of ramp right before the downbeat avoids a click.
        ramp = min(0.05, 0.006 / max(fade / sample_rate, 1e-3))
        fade_in = _smoothstep(progress, max(0.0, entry - ramp), entry)
        mixed = outgoing[:fade] + incoming[:fade] * fade_in
        return _prevent_clipping(mixed.astype(np.float32))
    if technique == "eq_blend":
        return _three_band_blend(outgoing[:fade], incoming[:fade], sample_rate, progress)
    if technique == "quick_cut":
        shifted = np.clip((progress - 0.08) / 0.84, 0.0, 1.0)
        eased = shifted * shifted * (3.0 - (2.0 * shifted))
        fade_out = 1.0 - eased
        fade_in = eased
    else:
        intro = _smoothstep(progress, 0.0, 0.3)
        handoff = _smoothstep(progress, 0.3, 1.0)
        fade_in = (0.1 * intro) + (0.9 * handoff)
        fade_start = 0.2 if technique in {"phrase_blend", "tempo_handoff", "loop_echo_out"} else 0.16
        fade_out = 1.0 - _smoothstep(progress, fade_start, 0.95)

    out_low, out_high = _split_low_high(outgoing[:fade], sample_rate)
    in_low, in_high = _split_low_high(incoming[:fade], sample_rate)

    swap = transition.bass_swap_position if transition else 0.5
    handoff_start = max(0.0, swap - 0.13)
    handoff_end = min(1.0, swap + 0.13)
    bass_handoff = _smoothstep(progress, handoff_start, handoff_end)
    outgoing_bass = 1.0 - bass_handoff
    incoming_bass = bass_handoff
    mids_out = fade_out * (1.0 - (0.04 * progress))
    mids_in = fade_in * (0.9 + (0.1 * progress))

    overlap = (out_high * mids_out) + (in_high * mids_in) + (out_low * outgoing_bass) + (in_low * incoming_bass)
    return _micro_duck(_prevent_clipping(overlap.astype(np.float32)))


def _three_band_blend(
    outgoing: np.ndarray,
    incoming: np.ndarray,
    sample_rate: int,
    progress: np.ndarray,
) -> np.ndarray:
    """Long EQ blend the way a club DJ rides it on a three-band mixer.

    Incoming highs come in first, then mids; the bass lines swap quickly in the
    middle on a phrase line (never both basses at once); the outgoing mids and
    highs leave last.
    """
    out_low, out_mid, out_high = _split_three_bands(outgoing, sample_rate)
    in_low, in_mid, in_high = _split_three_bands(incoming, sample_rate)
    in_high_gain = _smoothstep(progress, 0.0, 0.25)
    in_mid_gain = _smoothstep(progress, 0.15, 0.48)
    bass_swap = _smoothstep(progress, 0.48, 0.53)
    out_mid_gain = 1.0 - _smoothstep(progress, 0.5, 0.82)
    out_high_gain = 1.0 - _smoothstep(progress, 0.62, 0.97)
    mixed = (
        out_low * (1.0 - bass_swap)
        + in_low * bass_swap
        + out_mid * out_mid_gain
        + in_mid * in_mid_gain
        + out_high * out_high_gain
        + in_high * in_high_gain
    )
    return _micro_duck(_prevent_clipping(mixed.astype(np.float32)))


def _split_three_bands(audio: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    low, rest = _split_low_high(audio, sample_rate)
    if rest.size < 32:
        return low, rest * 0.5, rest * 0.5
    cutoff = min(2500.0, (sample_rate / 2.0) - 200.0)
    sos = butter(2, cutoff, btype="lowpass", fs=sample_rate, output="sos")
    mid = sosfilt(sos, rest).astype(np.float32)
    return low, mid, (rest - mid).astype(np.float32)


def _kill_cut_outgoing(audio: np.ndarray, sample_rate: int, beat_seconds: float) -> np.ndarray:
    """Pull the bass out across the last bar so the room feels the gap, then hard stop on the 1."""
    if audio.size < 64:
        return audio
    low, high = _split_low_high(audio, sample_rate)
    progress = np.linspace(0.0, 1.0, len(audio), dtype=np.float32)
    bass = 1.0 - _smoothstep(progress, 0.0, 0.25)
    out = low * bass + high * (1.0 + 0.12 * progress)
    return (out * _tail_fade(len(audio), sample_rate, 0.012)).astype(np.float32)


def _spinback_outgoing(audio: np.ndarray, sample_rate: int, beat_seconds: float) -> np.ndarray:
    """Play to the last beat of the bar, then throw the record backwards."""
    if audio.size < sample_rate * 0.2:
        return audio
    spin_samples = min(len(audio) // 2, max(int(sample_rate * 0.25), int(beat_seconds * sample_rate)))
    spin_start = len(audio) - spin_samples
    # Backwards from the spin point: the record moves fast, then slows to a stop.
    progress = np.linspace(0.0, 1.0, spin_samples, dtype=np.float64)
    speed = 3.2 * (1.0 - progress) ** 1.6 + 0.05
    positions = spin_start - np.cumsum(speed)
    spun = np.interp(positions, np.arange(len(audio), dtype=np.float64), audio.astype(np.float64), left=0.0)
    envelope = (1.0 - progress) ** 0.8
    result = audio.copy()
    result[spin_start:] = (spun * envelope).astype(np.float32)
    return result.astype(np.float32)


def _power_down_outgoing(audio: np.ndarray, sample_rate: int, beat_seconds: float) -> np.ndarray:
    """Turntable stop: the outgoing song slows to a halt over the last beat and a half."""
    if audio.size < sample_rate * 0.2:
        return audio
    stop_samples = min(len(audio) * 2 // 3, max(int(sample_rate * 0.35), int(beat_seconds * 1.5 * sample_rate)))
    stop_start = len(audio) - stop_samples
    progress = np.linspace(0.0, 1.0, stop_samples, dtype=np.float64)
    rate = (1.0 - progress) ** 1.4
    positions = stop_start + np.cumsum(rate)
    slowed = np.interp(positions, np.arange(len(audio), dtype=np.float64), audio.astype(np.float64), right=0.0)
    result = audio.copy()
    result[stop_start:] = (slowed * (1.0 - progress**3)).astype(np.float32)
    return result.astype(np.float32)


def _roll_build_outgoing(audio: np.ndarray, sample_rate: int, beat_seconds: float) -> np.ndarray:
    """Loop roll that halves every quarter (1 beat, 1/2, 1/4, 1/8) while the bass filters out."""
    beat = max(32, int(beat_seconds * sample_rate))
    if audio.size < beat * 2:
        return audio
    quarters = np.array_split(np.arange(len(audio)), 4)
    rolled = np.zeros(len(audio), dtype=np.float32)
    snippet_source = audio[: beat].copy()
    for index, part in enumerate(quarters):
        loop = max(32, beat // (2**index))
        edge = max(4, min(loop // 6, int(sample_rate * 0.004)))
        rolled[part] = _repeat_with_crossfade(snippet_source[:loop], len(part), edge)
    low, high = _split_low_high(rolled, sample_rate)
    progress = np.linspace(0.0, 1.0, len(audio), dtype=np.float32)
    build = (low * (1.0 - _smoothstep(progress, 0.2, 0.9))) + high * (0.85 + 0.3 * progress)
    return (build * _tail_fade(len(audio), sample_rate, 0.008)).astype(np.float32)


def _reverb_wash_outgoing(audio: np.ndarray, sample_rate: int, beat_seconds: float) -> np.ndarray:
    """Send the outgoing song into a big reverb and let the dry signal go, leaving a wash."""
    if audio.size < 256:
        return audio
    _, high = _split_low_high(audio, sample_rate)
    impulse_length = int(sample_rate * 1.6)
    rng = np.random.default_rng(1234)
    t = np.arange(impulse_length, dtype=np.float32) / sample_rate
    impulse = rng.normal(0.0, 1.0, impulse_length).astype(np.float32) * np.exp(-3.2 * t)
    impulse /= max(float(np.sqrt(np.sum(impulse**2))), 1e-9)
    send_progress = np.linspace(0.0, 1.0, len(audio), dtype=np.float32)
    send = high * _smoothstep(send_progress, 0.0, 0.35)
    wet = fftconvolve(send, impulse)[: len(audio)].astype(np.float32)
    dry_gain = 1.0 - _smoothstep(send_progress, 0.1, 0.5)
    wet_gain = 0.9 * _smoothstep(send_progress, 0.05, 0.4) * (1.0 - _smoothstep(send_progress, 0.55, 1.0) * 0.85)
    return ((audio * dry_gain) + (wet * wet_gain)).astype(np.float32)


def _tail_fade(length: int, sample_rate: int, seconds: float) -> np.ndarray:
    envelope = np.ones(length, dtype=np.float32)
    count = min(length, max(1, int(sample_rate * seconds)))
    envelope[-count:] = np.linspace(1.0, 0.0, count, dtype=np.float32)
    return envelope


def _add_impact_at_start(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    length = min(len(audio), int(sample_rate * 0.65))
    if length <= 0:
        return audio
    t = np.arange(length, dtype=np.float32) / sample_rate
    decay = np.exp(-6.0 * t).astype(np.float32)
    hit = np.sin(2.0 * np.pi * 58.0 * t).astype(np.float32) * decay * 0.1
    result = audio.copy()
    result[:length] += hit
    return result


_OUTGOING_MOVES = {
    "kill_cut": _kill_cut_outgoing,
    "spinback": _spinback_outgoing,
    "power_down": _power_down_outgoing,
    "roll_build": _roll_build_outgoing,
    "reverb_wash": _reverb_wash_outgoing,
}


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


def _filter_outgoing_transition(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if audio.size < 32:
        return audio
    low, high = _split_low_high(audio, sample_rate)
    progress = np.linspace(0.0, 1.0, len(audio), dtype=np.float32)
    high_reduction = _smoothstep(progress, 0.08, 0.94)
    low_curve = 1.0 - (0.18 * progress)
    high_curve = 1.0 - (0.78 * high_reduction)
    return ((low * low_curve) + (high * high_curve)).astype(np.float32)


def _tempo_ramp_outgoing(audio: np.ndarray, adjustment_percent: float) -> np.ndarray:
    if audio.size < 64 or abs(adjustment_percent) <= 0.01:
        return audio
    target_rate = 1.0 + (adjustment_percent / 100.0)
    if target_rate < 0.94 or target_rate > 1.06:
        return audio

    progress = np.linspace(0.0, 1.0, len(audio), dtype=np.float64)
    eased = progress * progress * (3.0 - (2.0 * progress))
    rates = 1.0 + ((target_rate - 1.0) * eased)
    source_positions = np.cumsum(rates, dtype=np.float64) - rates[0]
    ramped = np.interp(
        source_positions,
        np.arange(len(audio), dtype=np.float64),
        audio.astype(np.float64),
        left=0.0,
        right=0.0,
    )
    return ramped.astype(np.float32)


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
