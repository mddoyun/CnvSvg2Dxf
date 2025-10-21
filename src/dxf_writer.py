from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, List, Tuple

import ezdxf
from ezdxf import colors

from .mapping import MappingManager
from .models import ConversionOptions, ConversionResult, LayerAttributes, SvgDocument, SvgPrimitive
from .svg_loader import parse_length


class DxfWriter:
    """Create DXF documents from SVG primitives."""

    def write(self, document: SvgDocument, options: ConversionOptions, mapping: MappingManager) -> ConversionResult:
        doc = ezdxf.new("R2013")
        msp = doc.modelspace()
        written = 0
        log_messages: List[str] = []
        warnings: List[str] = []
        layers_created = set()

        for primitive in document.primitives:
            attrs = mapping.resolve(primitive)
            dxf_attribs = attrs.to_dxf_attribs()
            ensure_layer(doc, attrs.layer, attrs)
            if attrs.layer not in layers_created:
                layers_created.add(attrs.layer)

            try:
                if primitive.kind == "line":
                    written += self._write_line(msp, primitive.points, dxf_attribs, log_messages, primitive)
                elif primitive.kind == "polyline":
                    written += self._write_polyline(msp, primitive.points, primitive.extra, dxf_attribs, log_messages, primitive)
                elif primitive.kind == "circle":
                    written += self._write_circle(msp, primitive, dxf_attribs, log_messages)
                elif primitive.kind == "ellipse":
                    written += self._write_ellipse(msp, primitive, dxf_attribs, log_messages)
                elif primitive.kind == "text":
                    written += self._write_text(msp, primitive, dxf_attribs, log_messages)
                else:
                    warnings.append(f"미지원 요소 건너뜀: {primitive.label()}")
            except Exception as exc:  # pragma: no cover - defensive
                warnings.append(f"DXF 작성 실패 ({primitive.label()}): {exc}")

        doc.saveas(str(options.output_path))

        result = ConversionResult(
            output_path=options.output_path,
            written_entities=written,
            created_layers=sorted(layers_created),
            log_messages=log_messages,
            warnings=warnings,
        )
        return result

    def _write_line(self, msp, points: List[Tuple[float, float]], attrs, log, primitive) -> int:
        if len(points) != 2:
            return 0
        msp.add_line(points[0], points[1], dxfattribs=attrs)
        log.append(f"LINE: {primitive.label()} -> {attrs.get('layer')}")
        return 1

    def _write_polyline(self, msp, points: List[Tuple[float, float]], extra, attrs, log, primitive) -> int:
        if len(points) < 2:
            return 0
        closed = bool(extra.get("closed")) if isinstance(extra, dict) else False
        fill_value = (primitive.style.get("fill") or "").strip().lower()
        has_fill = closed and fill_value not in {"", "none", "transparent"}
        entities_created = 0

        stroke_value_raw = primitive.style.get("stroke") or ""
        stroke_value = stroke_value_raw.strip().lower()
        stroke_width_raw = primitive.style.get("stroke-width")
        stroke_width = None
        if stroke_width_raw:
            try:
                stroke_width = float(stroke_width_raw)
            except ValueError:
                stroke_width = parse_length(stroke_width_raw)
        material_class = any(cls.startswith("material-") for cls in primitive.classes)

        if not closed and material_class and "projection" in primitive.classes:
            if stroke_value in {"", "none", "transparent"}:
                return 0
            if stroke_width is not None and stroke_width <= 0.1:
                return 0

        if has_fill:
            hatch_layer = attrs.get("layer")
            hatch = msp.add_hatch(dxfattribs={"layer": hatch_layer} if hatch_layer else {})
            if "true_color" in attrs:
                hatch.rgb = colors.int2rgb(attrs["true_color"])
            elif "color" in attrs:
                hatch.dxf.color = attrs["color"]
            hatch.paths.add_polyline_path(points, is_closed=True)
            log.append(f"HATCH: {primitive.label()} -> {attrs.get('layer')}")
            entities_created += 1

        skip_boundary = False
        if has_fill and material_class and "cut" not in primitive.classes:
            if stroke_value in {"", "none", "transparent"}:
                skip_boundary = True
            elif stroke_width is not None and stroke_width <= 0.1:
                skip_boundary = True

        if not skip_boundary:
            poly_points = points
            if closed and points[0] == points[-1] and len(points) > 1:
                poly_points = points[:-1]
            msp.add_lwpolyline(poly_points, format="xy", close=closed, dxfattribs=attrs)
            log.append(f"LWPOLYLINE({len(poly_points)}): {primitive.label()} -> {attrs.get('layer')} closed={closed}")
            entities_created += 1

        return entities_created

    def _write_circle(self, msp, primitive: SvgPrimitive, attrs, log) -> int:
        center = primitive.points[0]
        radius_x = primitive.extra.get("radius_x", 0.0)
        radius_y = primitive.extra.get("radius_y", 0.0)
        if math.isclose(radius_x, radius_y, rel_tol=1e-3):
            radius = radius_x
            msp.add_circle(center, radius, dxfattribs=attrs)
            log.append(f"CIRCLE r={radius:.3f}")
        else:
            ratio = radius_y / radius_x if radius_x else 1.0
            msp.add_ellipse(center, major_axis=(radius_x, 0), ratio=ratio, dxfattribs=attrs)
            log.append(f"ELLIPSE rx={radius_x:.3f} ry={radius_y:.3f}")
        return 1

    def _write_ellipse(self, msp, primitive: SvgPrimitive, attrs, log) -> int:
        center = primitive.points[0]
        radius_x = primitive.extra.get("radius_x", 0.0)
        radius_y = primitive.extra.get("radius_y", 0.0)
        ratio = radius_y / radius_x if radius_x else 1.0
        msp.add_ellipse(center, major_axis=(radius_x, 0), ratio=ratio, dxfattribs=attrs)
        log.append(f"ELLIPSE rx={radius_x:.3f} ry={radius_y:.3f}")
        return 1

    def _write_text(self, msp, primitive: SvgPrimitive, attrs, log) -> int:
        position = primitive.points[0]
        content = primitive.extra.get("text", "")
        if not content:
            return 0
        height = self._font_size_to_height(primitive.style)
        text_attrs = dict(attrs)
        text_attrs.setdefault("height", height)
        text_entity = msp.add_text(content, dxfattribs=text_attrs)
        text_entity.dxf.insert = position
        anchor = (primitive.extra or {}).get("text_anchor")
        if isinstance(anchor, str):
            anchor = anchor.lower()
        if anchor in {"middle", "center"}:
            text_entity.dxf.halign = 1  # center
            text_entity.dxf.align_point = position
        elif anchor in {"end", "right"}:
            text_entity.dxf.halign = 2  # right
            text_entity.dxf.align_point = position
        log.append(f"TEXT '{content[:20]}' h={height:.2f}")
        return 1

    @staticmethod
    def _font_size_to_height(style: dict) -> float:
        value = style.get("font-size")
        if not value:
            return 3.5
        return parse_length(str(value))


def ensure_layer(doc: ezdxf.EzDxf, layer_name: str, attrs: LayerAttributes) -> None:
    if layer_name in doc.layers:
        return
    color = 7
    if attrs.color and attrs.color.startswith("#"):
        # Map to closest AutoCAD color index if possible; fallback to 7.
        color = 7
    doc.layers.add(name=layer_name, color=color, linetype=attrs.linetype or "Continuous")
