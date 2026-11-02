"""Piecewise-linear mapping from a metric to a 0..100 sub-score."""

from __future__ import annotations

from collections.abc import Sequence


def scale(value: float, points: Sequence[tuple[float, float]]) -> float:
    """Interpolate ``value`` over ``points`` [(x, score), ...] sorted by x; clamps at the ends."""
    pts = sorted(points)
    if value <= pts[0][0]:
        return float(pts[0][1])
    if value >= pts[-1][0]:
        return float(pts[-1][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if x0 <= value <= x1:
            if x1 == x0:
                return float(y1)
            return float(y0 + (y1 - y0) * (value - x0) / (x1 - x0))
    return float(pts[-1][1])  # pragma: no cover
