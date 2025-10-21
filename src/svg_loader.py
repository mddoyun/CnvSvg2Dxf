from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple
from urllib.parse import unquote, urlparse

import numpy as np
from lxml import etree

from .models import Point, SvgDocument, SvgPrimitive
from .path_parser import path_to_polylines, simplify_polyline
from .style_resolver import StyleResolver
from .transform_utils import (
    apply_transform,
    identity_matrix,
    multiply,
    parse_transform,
    transform_point,
    translation_matrix,
    scale_matrix,
)

LengthUnit = Tuple[float, str]

UNIT_CONVERSIONS = {
    "mm": 1.0,
    "cm": 10.0,
    "in": 25.4,
    "pt": 25.4 / 72.0,
    "pc": 25.4 / 6.0,
    "px": 25.4 / 96.0,
}


class SvgLoader:
    """Parse SVG into normalized primitives ready for conversion."""

    def __init__(self, css_files: Iterable[Path] | None = None):
        self.css_files = list(css_files or [])

    def load(self, path: Path) -> SvgDocument:
        visited: Set[Path] = set()
        return self._load_internal(path, visited)

    def _load_internal(self, path: Path, visited: Set[Path]) -> SvgDocument:
        absolute_path = path.resolve()
        if absolute_path in visited:
            raise RuntimeError(f"순환 참조가 감지되어 SVG를 불러올 수 없습니다: {absolute_path}")
        visited.add(absolute_path)

        try:
            tree = etree.parse(str(absolute_path))
        except OSError as exc:  # pragma: no cover - IO 오류 방지
            visited.remove(absolute_path)
            raise exc

        root = tree.getroot()

        width_mm = parse_length(root.get("width", "0"))
        height_mm = parse_length(root.get("height", "0"))

        viewbox = parse_viewbox(root.get("viewBox"))
        if viewbox is None:
            viewbox = (0.0, 0.0, width_mm or 1.0, height_mm or 1.0)

        min_x, min_y, viewbox_width, viewbox_height = viewbox
        scale_x = width_mm / viewbox_width if viewbox_width else 1.0
        scale_y = height_mm / viewbox_height if viewbox_height else 1.0

        style_resolver = StyleResolver(self.css_files)
        for node in root.iter():
            if etree.QName(node.tag).localname.lower() == "style" and node.text:
                style_resolver.add_css_text(node.text)

        root_matrix = np.array(
            [
                [scale_x, 0.0, -min_x * scale_x],
                [0.0, -scale_y, (min_y + viewbox_height) * scale_y],
                [0.0, 0.0, 1.0],
            ],
            dtype=float,
        )

        document = SvgDocument(
            path=absolute_path,
            width_mm=width_mm,
            height_mm=height_mm,
            viewbox=viewbox,
            scale_x=scale_x,
            scale_y=scale_y,
            primitives=[],
            css_files=self.css_files,
            warnings=[],
        )

        stack = deque([(root, root_matrix, {}, tuple())])
        while stack:
            element, transform, inherited_style, inherited_classes = stack.pop()
            local_name = etree.QName(element.tag).localname.lower()

            if local_name in {"defs", "metadata"}:
                continue

            element_transform = parse_transform(element.get("transform"))
            current_transform = multiply(transform, element_transform)

            element_style = style_resolver.resolve(element)
            combined_style = dict(inherited_style)
            combined_style.update(element_style)

            element_classes = style_resolver.extract_classes(element)
            combined_classes = merge_classes(inherited_classes, element_classes)

            if local_name in {"g", "svg", "a"}:
                for child in reversed(list(element)):
                    stack.append((child, current_transform, combined_style, combined_classes))
                continue

            if local_name == "image":
                primitives, warnings = self._create_image(
                    element=element,
                    transform=current_transform,
                    classes=combined_classes,
                    document=document,
                    visited=visited,
                )
            else:
                primitive_creators = {
                    "line": self._create_line,
                    "polyline": self._create_polyline,
                    "polygon": self._create_polygon,
                    "rect": self._create_rect,
                    "circle": self._create_circle,
                    "ellipse": self._create_ellipse,
                    "path": self._create_path,
                    "text": self._create_text,
                }

                creator = primitive_creators.get(local_name)
                if not creator:
                    continue

                primitives, warnings = creator(
                    element=element,
                    transform=current_transform,
                    style=combined_style,
                    classes=combined_classes,
                )
            if primitives:
                document.primitives.extend(primitives)
            document.warnings.extend(warnings)

        visited.remove(absolute_path)
        return document

    def _create_line(
        self,
        *,
        element: etree._Element,
        transform: np.ndarray,
        style: Dict[str, str],
        classes: Tuple[str, ...],
    ) -> Tuple[List[SvgPrimitive], List[str]]:
        try:
            x1 = float(element.get("x1", "0"))
            y1 = float(element.get("y1", "0"))
            x2 = float(element.get("x2", "0"))
            y2 = float(element.get("y2", "0"))
        except ValueError:
            return [], [f"경고: line 좌표 파싱 실패 (id={element.get('id')})"]

        points = apply_transform(transform, [(x1, y1), (x2, y2)])
        primitive = SvgPrimitive(
            kind="line",
            points=points,
            style=dict(style),
            classes=classes,
            element_id=element.get("id"),
            attributes=dict(element.attrib),
        )
        return [primitive], []

    def _create_image(
        self,
        *,
        element: etree._Element,
        transform: np.ndarray,
        classes: Tuple[str, ...],
        document: SvgDocument,
        visited: Set[Path],
    ) -> Tuple[List[SvgPrimitive], List[str]]:
        href = (
            element.get("{http://www.w3.org/1999/xlink}href")
            or element.get("href")
            or element.get("xlink:href")
        )
        if not href:
            return [], []
        href = href.strip()
        if href.startswith("data:"):
            return [], []

        decoded = unquote(href)
        parsed = urlparse(decoded)
        if parsed.scheme and parsed.scheme != "file":
            return [], []

        path_str = parsed.path or decoded
        if ".svg" not in path_str.lower():
            return [], []

        candidate = resolve_reference_path(document.path.parent, path_str)
        if not candidate.exists():
            return [], [f"경고: 참조한 SVG 파일을 찾을 수 없습니다 ({href})"]

        try:
            embedded_document = self._load_internal(candidate, visited)
        except RuntimeError as exc:
            return [], [f"경고: SVG 이미지 참조를 불러오지 못했습니다 ({candidate}): {exc}"]

        width_attr = parse_length(element.get("width"))
        height_attr = parse_length(element.get("height"))
        x_attr = parse_length(element.get("x"))
        y_attr = parse_length(element.get("y"))

        base_width = embedded_document.width_mm or embedded_document.viewbox[2] or 1.0
        base_height = embedded_document.height_mm or embedded_document.viewbox[3] or 1.0
        target_width = width_attr or embedded_document.width_mm or base_width
        target_height = height_attr or embedded_document.height_mm or base_height

        sx = target_width / base_width if base_width else 1.0
        sy = target_height / base_height if base_height else 1.0

        image_transform = multiply(
            translation_matrix(x_attr, y_attr),
            scale_matrix(sx, sy),
        )
        combined_transform = multiply(transform, image_transform)

        primitives: List[SvgPrimitive] = []
        for prim in embedded_document.primitives:
            transformed_points = apply_transform(combined_transform, prim.points)
            extra = prim.extra.copy() if isinstance(prim.extra, dict) else prim.extra
            merged_classes = merge_classes(classes, prim.classes)
            primitives.append(
                SvgPrimitive(
                    kind=prim.kind,
                    points=transformed_points,
                    style=dict(prim.style),
                    classes=merged_classes,
                    element_id=prim.element_id,
                    attributes=dict(prim.attributes),
                    extra=extra,
                )
            )

        warnings = [f"참고: 임베디드 SVG '{candidate.name}'에서 {len(primitives)}개 요소 로드"]
        warnings.extend(f"{candidate.name}: {msg}" for msg in embedded_document.warnings)
        return primitives, warnings

    def _create_polyline(
        self,
        *,
        element: etree._Element,
        transform: np.ndarray,
        style: Dict[str, str],
        classes: Tuple[str, ...],
    ) -> Tuple[List[SvgPrimitive], List[str]]:
        points = parse_points_attribute(element.get("points", ""))
        if not points:
            return [], []
        transformed = apply_transform(transform, points)
        simplified = simplify_polyline(transformed, closed=False)
        primitive = SvgPrimitive(
            kind="polyline",
            points=simplified,
            style=dict(style),
            classes=classes,
            element_id=element.get("id"),
            attributes=dict(element.attrib),
            extra={"closed": False, "origin": "polyline"},
        )
        return [primitive], []

    def _create_polygon(
        self,
        *,
        element: etree._Element,
        transform: np.ndarray,
        style: Dict[str, str],
        classes: Tuple[str, ...],
    ) -> Tuple[List[SvgPrimitive], List[str]]:
        points = parse_points_attribute(element.get("points", ""))
        if not points:
            return [], []
        if points[0] != points[-1]:
            points.append(points[0])
        transformed = apply_transform(transform, points)
        simplified = simplify_polyline(transformed, closed=True)
        primitive = SvgPrimitive(
            kind="polyline",
            points=simplified,
            style=dict(style),
            classes=classes,
            element_id=element.get("id"),
            attributes=dict(element.attrib),
            extra={"closed": True, "origin": "polygon"},
        )
        return [primitive], []

    def _create_rect(
        self,
        *,
        element: etree._Element,
        transform: np.ndarray,
        style: Dict[str, str],
        classes: Tuple[str, ...],
    ) -> Tuple[List[SvgPrimitive], List[str]]:
        try:
            x = float(element.get("x", "0"))
            y = float(element.get("y", "0"))
            width = float(element.get("width", "0"))
            height = float(element.get("height", "0"))
        except ValueError:
            return [], [f"경고: rect 치수 파싱 실패 (id={element.get('id')})"]

        points = [
            (x, y),
            (x + width, y),
            (x + width, y + height),
            (x, y + height),
            (x, y),
        ]
        transformed = apply_transform(transform, points)
        primitive = SvgPrimitive(
            kind="polyline",
            points=transformed,
            style=dict(style),
            classes=classes,
            element_id=element.get("id"),
            attributes=dict(element.attrib),
            extra={
                "closed": True,
                "origin": "rect",
                "rx": element.get("rx"),
                "ry": element.get("ry"),
            },
        )
        return [primitive], []

    def _create_circle(
        self,
        *,
        element: etree._Element,
        transform: np.ndarray,
        style: Dict[str, str],
        classes: Tuple[str, ...],
    ) -> Tuple[List[SvgPrimitive], List[str]]:
        try:
            cx = float(element.get("cx", "0"))
            cy = float(element.get("cy", "0"))
            radius = float(element.get("r", "0"))
        except ValueError:
            return [], [f"경고: circle 치수 파싱 실패 (id={element.get('id')})"]

        center = transform_point(transform, (cx, cy))
        point_x = transform_point(transform, (cx + radius, cy))
        point_y = transform_point(transform, (cx, cy + radius))
        radius_x = distance(center, point_x)
        radius_y = distance(center, point_y)
        primitive = SvgPrimitive(
            kind="circle",
            points=[center],
            style=dict(style),
            classes=classes,
            element_id=element.get("id"),
            attributes=dict(element.attrib),
            extra={"radius_x": radius_x, "radius_y": radius_y},
        )
        return [primitive], []

    def _create_ellipse(
        self,
        *,
        element: etree._Element,
        transform: np.ndarray,
        style: Dict[str, str],
        classes: Tuple[str, ...],
    ) -> Tuple[List[SvgPrimitive], List[str]]:
        try:
            cx = float(element.get("cx", "0"))
            cy = float(element.get("cy", "0"))
            rx = float(element.get("rx", "0"))
            ry = float(element.get("ry", "0"))
        except ValueError:
            return [], [f"경고: ellipse 치수 파싱 실패 (id={element.get('id')})"]

        center = transform_point(transform, (cx, cy))
        point_x = transform_point(transform, (cx + rx, cy))
        point_y = transform_point(transform, (cx, cy + ry))
        radius_x = distance(center, point_x)
        radius_y = distance(center, point_y)

        primitive = SvgPrimitive(
            kind="ellipse",
            points=[center],
            style=dict(style),
            classes=classes,
            element_id=element.get("id"),
            attributes=dict(element.attrib),
            extra={"radius_x": radius_x, "radius_y": radius_y},
        )
        return [primitive], []

    def _create_path(
        self,
        *,
        element: etree._Element,
        transform: np.ndarray,
        style: Dict[str, str],
        classes: Tuple[str, ...],
    ) -> Tuple[List[SvgPrimitive], List[str]]:
        data = element.get("d")
        if not data:
            return [], []

        polylines, warnings = path_to_polylines(data)
        primitives: List[SvgPrimitive] = []
        for poly in polylines:
            transformed = apply_transform(transform, poly.points)
            simplified = simplify_polyline(transformed, closed=poly.closed)
            primitive = SvgPrimitive(
                kind="polyline",
                points=simplified,
                style=dict(style),
                classes=classes,
                element_id=element.get("id"),
                attributes=dict(element.attrib),
                extra={"closed": poly.closed, "origin": "path"},
            )
            primitives.append(primitive)

        if primitives:
            if len(primitives) > 1:
                warnings.append(f"참고: path(id={element.get('id')})가 {len(primitives)}개의 폴리라인으로 분해되었습니다.")
            return primitives, warnings
        return [], warnings or [f"경고: path 변환 결과 없음 (id={element.get('id')})"]

    def _create_text(
        self,
        *,
        element: etree._Element,
        transform: np.ndarray,
        style: Dict[str, str],
        classes: Tuple[str, ...],
    ) -> Tuple[List[SvgPrimitive], List[str]]:
        text_content = extract_text_content(element)
        if not text_content:
            return [], []

        x = float(element.get("x", "0") or 0)
        y = float(element.get("y", "0") or 0)
        position = transform_point(transform, (x, y))

        primitive = SvgPrimitive(
            kind="text",
            points=[position],
            style=dict(style),
            classes=classes,
            element_id=element.get("id"),
            attributes=dict(element.attrib),
            extra={
                "text": text_content,
                "text_anchor": element.get("text-anchor", style.get("text-anchor")),
            },
        )
        return [primitive], []


def extract_text_content(element: etree._Element) -> str:
    tspans = [node for node in element if etree.QName(node.tag).localname.lower() == "tspan"]
    if tspans:
        lines = []
        for tspan in tspans:
            text = "".join(tspan.itertext()).strip()
            if text:
                lines.append(text)
        if lines:
            return "\n".join(lines)
    combined = " ".join("".join(element.itertext()).split())
    return combined


def parse_length(value: str | None) -> float:
    if not value:
        return 0.0
    value = value.strip()
    unit = "".join(ch for ch in value if ch.isalpha())
    number = value.rstrip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
    try:
        magnitude = float(number)
    except ValueError:
        return 0.0
    if not unit:
        return magnitude
    factor = UNIT_CONVERSIONS.get(unit.lower())
    if not factor:
        return magnitude
    return magnitude * factor


def parse_viewbox(value: str | None) -> Tuple[float, float, float, float] | None:
    if not value:
        return None
    parts = [p for p in value.replace(",", " ").split(" ") if p]
    if len(parts) != 4:
        return None
    try:
        numbers = tuple(float(p) for p in parts)
    except ValueError:
        return None
    return numbers  # type: ignore[return-value]


def parse_points_attribute(value: str) -> List[Point]:
    points: List[Point] = []
    cleaned = value.replace(",", " ")
    parts = [p for p in cleaned.strip().split() if p]
    if len(parts) % 2 != 0:
        parts = parts[:-1]
    for i in range(0, len(parts), 2):
        try:
            x = float(parts[i])
            y = float(parts[i + 1])
        except ValueError:
            continue
        points.append((x, y))
    return points


def merge_classes(inherited: Tuple[str, ...], current: Tuple[str, ...]) -> Tuple[str, ...]:
    merged: Dict[str, None] = dict.fromkeys(inherited)
    for cls in current:
        merged.setdefault(cls, None)
    return tuple(merged.keys())


def distance(p1: Point, p2: Point) -> float:
    return float(((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5)


def resolve_reference_path(base_dir: Path, href: str) -> Path:
    normalized = href.replace("\\", "/")
    if normalized.startswith("file://"):
        normalized = normalized[7:]
    path = Path(normalized)
    if not path.is_absolute():
        candidate = (base_dir / normalized).resolve()
    else:
        candidate = path
    if not candidate.exists():
        fallback = (base_dir / Path(normalized).name).resolve()
        if fallback.exists():
            return fallback
    return candidate
