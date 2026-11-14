"""Read a free-text mix direction ("smooth house warm-up, then club energy") into
signals the planner and recommender can share."""

from __future__ import annotations

_LIFT_WORDS = ("build", "hype", "peak", "pump", "turn up", "more energy", "club energy", "banger", "go hard", "warm-up", "warm up")
_DROP_WORDS = ("chill", "wind down", "cool down", "cooldown", "lounge", "ambient", "slow down", "mellow", "after hours", "relax")

# hint -> (words a DJ might type in the direction, words found in matching genre tags)
_GENRE_HINTS = {
    "club": (("club", "edm", "dance floor", "rave"), ("house", "techno", "trance", "electronic", "dance")),
    "house": (("house",), ("house",)),
    "techno": (("techno",), ("techno",)),
    "trance": (("trance",), ("trance",)),
    "drum & bass": (("drum and bass", "drum & bass", "dnb", "d&b"), ("drum & bass", "drum and bass")),
    "dubstep": (("dubstep",), ("dubstep",)),
    "hip-hop": (("hip hop", "hip-hop", "rap", "trap"), ("hip-hop", "hip hop", "rap")),
    "r&b": (("r&b", "rnb", "soul"), ("r&b", "soul")),
    "afrobeats": (("afro", "amapiano"), ("afrobeats", "amapiano")),
    "latin": (("latin", "reggaeton"), ("latin",)),
    "reggae": (("reggae", "dancehall"), ("reggae", "dancehall")),
    "pop": (("pop",), ("pop",)),
    "rock": (("rock",), ("rock",)),
    "jazz": (("jazz",), ("jazz",)),
    "country": (("country",), ("country",)),
}


def energy_goal(mix_direction: str | None) -> int:
    """+1 to lift energy, -1 to bring it down, 0 for a gentle default flow."""
    direction = (mix_direction or "").lower()
    lift = any(word in direction for word in _LIFT_WORDS)
    drop = any(word in direction for word in _DROP_WORDS)
    if lift and not drop:
        return 1
    if drop and not lift:
        return -1
    return 0


def direction_genres(mix_direction: str | None) -> list[str]:
    direction = (mix_direction or "").lower()
    return [hint for hint, (typed, _) in _GENRE_HINTS.items() if any(word in direction for word in typed)]


def genre_matches_direction(genre: str | None, mix_direction: str | None) -> bool:
    text = (genre or "").lower()
    wanted = direction_genres(mix_direction)
    if not wanted or not text:
        return False
    return any(any(word in text for word in _GENRE_HINTS[hint][1]) for hint in wanted)


def energy_arc_target(position: float, mix_direction: str | None) -> float:
    """Target relative energy (0 = calmest song, 1 = biggest) at a point in the set.

    Default shape is a DJ-style arc: warm up, peak around three quarters in,
    then release a little so the set lands instead of stopping at full blast.
    """
    position = min(1.0, max(0.0, position))
    goal = energy_goal(mix_direction)
    if goal > 0:
        return position
    if goal < 0:
        return 1.0 - position
    if position <= 0.75:
        return 0.15 + 0.85 * (position / 0.75)
    return 1.0 - (position - 0.75) * 1.2


def energy_flow_fit(source_energy: float, target_energy: float, mix_direction: str | None) -> float:
    """How well a step from one song's energy to the next fits the requested vibe (0..1)."""
    change = (target_energy - source_energy) / max(source_energy, target_energy, 1e-9)
    goal = energy_goal(mix_direction)
    if goal > 0:
        ideal = 0.15
    elif goal < 0:
        ideal = -0.15
    else:
        ideal = 0.04
    return max(0.0, 1.0 - abs(change - ideal) * 2.2)
