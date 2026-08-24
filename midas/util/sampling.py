"""Point-series thinning, shared by every writer that ships a curve to the UI."""

from __future__ import annotations


def downsample(points: list, max_points: int) -> list:
    """Evenly thin `points` to at most `max_points`, always keeping the last one.

    Used for equity curves: the browser cannot draw 200k points usefully and
    the JSON file should not carry them.
    """
    if max_points <= 0 or len(points) <= max_points:
        return points
    step = len(points) / max_points
    keep = sorted({int(i * step) for i in range(max_points)} | {len(points) - 1})
    return [points[i] for i in keep]
