from __future__ import annotations

import numpy as np

from app.models.track import EnergyPoint, TrackSection


def calculate_energy_curve(
    audio: np.ndarray,
    sample_rate: int,
    window_seconds: float = 2.0,
    hop_seconds: float = 1.0,
) -> list[EnergyPoint]:
    window_size = max(1, int(window_seconds * sample_rate))
    hop_size = max(1, int(hop_seconds * sample_rate))

    rms_values: list[float] = []
    times: list[float] = []
    for start in range(0, len(audio), hop_size):
        end = min(start + window_size, len(audio))
        window = audio[start:end]
        if len(window) == 0:
            continue
        rms_values.append(float(np.sqrt(np.mean(np.square(window)))))
        times.append((start + (len(window) / 2)) / sample_rate)
        if end == len(audio):
            break

    normalized = normalize_energy_values(rms_values)
    return [
        EnergyPoint(time=round(time, 3), energy=round(energy, 4))
        for time, energy in zip(times, normalized, strict=True)
    ]


def normalize_energy_values(values: list[float]) -> list[float]:
    if not values:
        return []

    value_array = np.asarray(values, dtype=float)
    max_value = float(np.max(value_array))
    min_value = float(np.min(value_array))

    if max_value <= 0:
        return [0.0 for _ in values]
    if np.isclose(max_value, min_value):
        return [1.0 for _ in values]

    normalized = (value_array - min_value) / (max_value - min_value)
    return [float(np.clip(value, 0.0, 1.0)) for value in normalized]


def identify_energy_sections(
    energy_curve: list[EnergyPoint],
    beat_timestamps: list[float],
    duration_seconds: float,
    section_type: str,
    threshold: float,
    above_threshold: bool,
    window_seconds: float = 2.0,
    merge_gap_seconds: float = 2.0,
    min_section_seconds: float = 4.0,
) -> list[TrackSection]:
    if not energy_curve or duration_seconds <= 0:
        return []

    raw_regions: list[tuple[float, float, list[EnergyPoint]]] = []
    active_points: list[EnergyPoint] = []

    for point in energy_curve:
        matches = point.energy >= threshold if above_threshold else point.energy <= threshold
        if matches:
            active_points.append(point)
        elif active_points:
            raw_regions.append(_points_to_region(active_points, duration_seconds, window_seconds))
            active_points = []

    if active_points:
        raw_regions.append(_points_to_region(active_points, duration_seconds, window_seconds))

    merged_regions = _merge_regions(raw_regions, merge_gap_seconds)
    minimum_duration = min(min_section_seconds, max(1.0, duration_seconds / 2))

    sections: list[TrackSection] = []
    for start_time, end_time, points in merged_regions:
        if end_time - start_time < minimum_duration and duration_seconds >= min_section_seconds:
            continue
        average_energy = float(np.mean([point.energy for point in points]))
        confidence = average_energy if above_threshold else 1.0 - average_energy
        sections.append(
            TrackSection(
                section_type=section_type,
                start_time=round(start_time, 3),
                end_time=round(end_time, 3),
                start_beat=_time_to_beat_number(start_time, beat_timestamps, prefer_next=True),
                end_beat=_time_to_beat_number(end_time, beat_timestamps, prefer_next=False),
                energy=round(average_energy, 4),
                confidence=round(float(np.clip(confidence, 0.0, 1.0)), 4),
                manually_labeled=False,
            )
        )

    return sections


def build_unknown_section(duration_seconds: float, beat_timestamps: list[float], energy: float) -> TrackSection:
    return TrackSection(
        section_type="unknown",
        start_time=0.0,
        end_time=round(duration_seconds, 3),
        start_beat=1 if beat_timestamps else None,
        end_beat=len(beat_timestamps) if beat_timestamps else None,
        energy=round(float(np.clip(energy, 0.0, 1.0)), 4),
        confidence=0.25,
        manually_labeled=False,
    )


def _points_to_region(
    points: list[EnergyPoint],
    duration_seconds: float,
    window_seconds: float,
) -> tuple[float, float, list[EnergyPoint]]:
    half_window = window_seconds / 2
    start_time = max(0.0, points[0].time - half_window)
    end_time = min(duration_seconds, points[-1].time + half_window)
    return start_time, end_time, points


def _merge_regions(
    regions: list[tuple[float, float, list[EnergyPoint]]],
    merge_gap_seconds: float,
) -> list[tuple[float, float, list[EnergyPoint]]]:
    if not regions:
        return []

    merged: list[tuple[float, float, list[EnergyPoint]]] = [regions[0]]
    for start_time, end_time, points in regions[1:]:
        last_start, last_end, last_points = merged[-1]
        if start_time - last_end <= merge_gap_seconds:
            merged[-1] = (last_start, max(last_end, end_time), last_points + points)
        else:
            merged.append((start_time, end_time, points))
    return merged


def _time_to_beat_number(time_seconds: float, beat_timestamps: list[float], prefer_next: bool) -> int | None:
    if not beat_timestamps:
        return None

    beat_array = np.asarray(beat_timestamps)
    if prefer_next:
        index = int(np.searchsorted(beat_array, time_seconds, side="left"))
        return min(index + 1, len(beat_timestamps))

    index = int(np.searchsorted(beat_array, time_seconds, side="right")) - 1
    return max(index + 1, 1)
