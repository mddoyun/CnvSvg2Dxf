from __future__ import annotations

import math
import re
from typing import Iterable, List, Tuple

import numpy as np

from .models import Point

TRANSFORM_RE = re.compile(r"(?P<name>[a-zA-Z]+)\((?P<args>[^)]+)\)")


def identity_matrix() -> np.ndarray:
    return np.identity(3)


def multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return a @ b


def translation_matrix(tx: float, ty: float) -> np.ndarray:
    return np.array([[1.0, 0.0, tx], [0.0, 1.0, ty], [0.0, 0.0, 1.0]], dtype=float)


def scale_matrix(sx: float, sy: float) -> np.ndarray:
    return np.array([[sx, 0.0, 0.0], [0.0, sy, 0.0], [0.0, 0.0, 1.0]], dtype=float)


def parse_transform(transform: str | None) -> np.ndarray:
    if not transform:
        return identity_matrix()
    transform = transform.strip()
    matrix = identity_matrix()
    for match in TRANSFORM_RE.finditer(transform):
        name = match.group("name").lower()
        args = [float(x) for x in re.split(r"[ ,]+", match.group("args").strip()) if x]
        matrix = multiply(matrix, _matrix_for_command(name, args))
    return matrix


def _matrix_for_command(name: str, args: List[float]) -> np.ndarray:
    if name == "matrix" and len(args) == 6:
        a, b, c, d, e, f = args
        return np.array([[a, c, e], [b, d, f], [0, 0, 1]], dtype=float)
    if name == "translate":
        tx = args[0]
        ty = args[1] if len(args) > 1 else 0.0
        return np.array([[1, 0, tx], [0, 1, ty], [0, 0, 1]], dtype=float)
    if name == "scale":
        sx = args[0]
        sy = args[1] if len(args) > 1 else sx
        return np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], dtype=float)
    if name == "rotate":
        angle = math.radians(args[0])
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        if len(args) == 3:
            cx, cy = args[1], args[2]
            translate_to_origin = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1]], dtype=float)
            rotation = np.array([[cos_a, -sin_a, 0], [sin_a, cos_a, 0], [0, 0, 1]], dtype=float)
            translate_back = np.array([[1, 0, cx], [0, 1, cy], [0, 0, 1]], dtype=float)
            return translate_back @ rotation @ translate_to_origin
        return np.array([[cos_a, -sin_a, 0], [sin_a, cos_a, 0], [0, 0, 1]], dtype=float)
    if name == "skewx":
        angle = math.radians(args[0])
        return np.array([[1, math.tan(angle), 0], [0, 1, 0], [0, 0, 1]], dtype=float)
    if name == "skewy":
        angle = math.radians(args[0])
        return np.array([[1, 0, 0], [math.tan(angle), 1, 0], [0, 0, 1]], dtype=float)
    return identity_matrix()


def apply_transform(matrix: np.ndarray, points: Iterable[Point]) -> List[Point]:
    result: List[Point] = []
    for x, y in points:
        vec = np.array([x, y, 1.0])
        res = matrix @ vec
        result.append((float(res[0]), float(res[1])))
    return result


def transform_point(matrix: np.ndarray, point: Point) -> Point:
    (x, y) = apply_transform(matrix, [point])[0]
    return x, y
