from __future__ import annotations

from dataclasses import dataclass
from math import acos, degrees, hypot, isclose
from typing import List, Tuple

from svgpathtools import Path, parse_path

from .models import Point


@dataclass
class PolylineApproximation:
    points: List[Point]
    closed: bool = False


def path_to_polylines(path_data: str, max_segment_length: float = 0.5, min_samples: int = 8) -> Tuple[List[PolylineApproximation], List[str]]:
    """
    Approximate an SVG path into polylines.

    Args:
        path_data: SVG path `d` attribute.
        max_segment_length: maximum segment length in SVG units for sampling.
        min_samples: lower bound for sampling resolution per subpath.

    Returns:
        Tuple of (polylines, warnings).
    """

    try:
        svg_path: Path = parse_path(path_data)
    except Exception as exc:  # pragma: no cover - defensive
        return [], [f"경고: path 해석 실패 - {exc}"]

    polylines: List[PolylineApproximation] = []
    warnings: List[str] = []

    for subpath in svg_path.continuous_subpaths():
        if isclose(subpath.length(), 0.0, rel_tol=1e-9):
            continue
        points = _sample_subpath(subpath, max_segment_length, min_samples)
        closed = bool(subpath.isclosed())
        simplified = simplify_polyline(points, closed=closed)
        polylines.append(PolylineApproximation(points=simplified, closed=closed))

    if not polylines:
        warnings.append("경고: path가 비어있거나 지원되지 않는 형식입니다.")

    return polylines, warnings


def _sample_subpath(subpath: Path, max_segment_length: float, min_samples: int) -> List[Point]:
    points: List[Point] = []
    current_point = subpath[0].start if len(subpath) else complex(0, 0)
    points.append((float(current_point.real), float(current_point.imag)))

    for segment in subpath:
        seg_length = float(segment.length())
        if seg_length == 0:
            continue
        if segment.__class__.__name__ == "Line":
            complex_point = segment.end
            points.append((float(complex_point.real), float(complex_point.imag)))
            continue
        steps = max(int(seg_length / max_segment_length) + 1, 1)
        if seg_length > max_segment_length:
            steps = max(steps, min_samples)
        for step in range(1, steps + 1):
            t = min(1.0, step / steps)
            complex_point = segment.point(t)
            points.append((float(complex_point.real), float(complex_point.imag)))
    return points


def simplify_polyline(points: List[Point], *, closed: bool = False, angle_tol: float = 0.5, min_segment: float = 0.05) -> List[Point]:
    if len(points) < 3:
        return points

    simplified: List[Point] = []
    total = len(points)

    def segment_length(p1: Point, p2: Point) -> float:
        return hypot(p2[0] - p1[0], p2[1] - p1[1])

    def angle(p_prev: Point, p_curr: Point, p_next: Point) -> float:
        v1 = (p_curr[0] - p_prev[0], p_curr[1] - p_prev[1])
        v2 = (p_next[0] - p_curr[0], p_next[1] - p_curr[1])
        len1 = hypot(*v1)
        len2 = hypot(*v2)
        if len1 < min_segment or len2 < min_segment or len1 == 0 or len2 == 0:
            return 180.0
        cos_val = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (len1 * len2)))
        return degrees(acos(cos_val))

    indices = range(total)
    if closed:
        # Avoid duplicating the last point for closed shapes; treat wrap-around angles.
        core_points = points[:-1] if points[0] == points[-1] else points
        total = len(core_points)
        simplified.append(core_points[0])
        for i in range(1, total):
            prev_pt = core_points[i - 1]
            curr_pt = core_points[i]
            next_pt = core_points[(i + 1) % total]
            if angle(prev_pt, curr_pt, next_pt) > angle_tol:
                simplified.append(curr_pt)
        if simplified[0] != simplified[-1]:
            simplified.append(simplified[0])
    else:
        simplified.append(points[0])
        for i in range(1, len(points) - 1):
            prev_pt = points[i - 1]
            curr_pt = points[i]
            next_pt = points[i + 1]
            if angle(prev_pt, curr_pt, next_pt) > angle_tol:
                simplified.append(curr_pt)
        simplified.append(points[-1])
    return simplified
