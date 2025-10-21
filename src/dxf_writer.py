from __future__ import annotations

import math
from typing import Iterable, List, Tuple

import ezdxf
from ezdxf import colors as ezdxf_colors

from .mapping import MappingManager
from .models import ConversionOptions, ConversionResult, LayerAttributes, SvgDocument, SvgPrimitive, parse_rgb
from .svg_loader import parse_length

# AutoCAD Color Index (ACI) to RGB mapping for standard colors
ACI_TO_RGB = {
    1: (255, 0, 0),  # Red
    2: (255, 255, 0),  # Yellow
    3: (0, 255, 0),  # Green
    4: (0, 255, 255),  # Cyan
    5: (0, 0, 255),  # Blue
    6: (255, 0, 255),  # Magenta
    7: (255, 255, 255),  # White/Black
    8: (128, 128, 128),  # Gray
    9: (192, 192, 192),  # Light Gray
    # ... other colors can be added if needed
}


def rgb_to_aci(rgb: Tuple[int, int, int]) -> int:
    """Finds the closest ACI color for a given RGB tuple."""
    min_dist = float("inf")
    closest_aci = 7  # Default to white/black

    # First, check for an exact match in the standard palette
    for aci, aci_rgb in ACI_TO_RGB.items():
        if aci_rgb == rgb:
            return aci

    # If no exact match, find the closest color by Euclidean distance
    # This is a simplified approach. ezdxf has a more sophisticated one.
    for aci, aci_rgb in ACI_TO_RGB.items():
        dist = sum([(c1 - c2) ** 2 for c1, c2 in zip(rgb, aci_rgb)])
        if dist < min_dist:
            min_dist = dist
            closest_aci = aci
    return closest_aci


class DxfWriter:
    """Create DXF documents from SVG primitives."""

    def __init__(self) -> None:
        self._style_cache: set[str] = set()
        self.mapping: MappingManager | None = None

    def write(self, document: SvgDocument, options: ConversionOptions, mapping: MappingManager) -> ConversionResult:
        doc = ezdxf.new("R2013")
        msp = doc.modelspace()
        written = 0
        log_messages: List[str] = []
        warnings: List[str] = []
        layers_created = set()

        self.mapping = mapping

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
                    written += self._write_text(doc, msp, primitive, dxf_attribs, log_messages)
                else:
                    warnings.append(f"미지원 요소 건너뜀: {primitive.label()}")
            except Exception as exc:  # pragma: no cover - defensive
                warnings.append(f"DXF 작성 실패 ({primitive.label()}): {exc}")

        doc.saveas(str(options.output_path))
        self.mapping = None

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
        fill_raw_value = (primitive.style.get("fill") or "").strip()
        fill_value = fill_raw_value.lower()
        has_fill = closed and fill_value not in {"", "none", "transparent"}
        entities_created = 0

        mapping = self.mapping
        pattern_info = None
        pattern_color_spec = None
        pattern_id = None
        if has_fill and mapping:
            pattern_id = mapping.extract_pattern_id(fill_value)
            pattern_info = mapping.resolve_pattern(pattern_id)
            if pattern_info:
                pattern_color_spec = mapping.normalize_color(pattern_info.get("color"))

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
            if pattern_info:
                if str(pattern_info.get("solid", False)).lower() in {"true", "1", "yes", "y"}:
                    hatch.set_solid_fill(True)
                else:
                    pattern_name = pattern_info.get("pattern")
                    if pattern_name:
                        scale = float(pattern_info.get("scale", 1.0) or 1.0)
                        angle = float(pattern_info.get("angle", 0.0) or 0.0)
                        try:
                            hatch.set_pattern_fill(pattern_name, scale=scale, angle=angle)
                        except ezdxf.DXFValueError:
                            hatch.set_solid_fill(True)
                    else:
                        hatch.set_solid_fill(True)
            else:
                hatch.set_solid_fill(True)

            color_spec = pattern_color_spec or (mapping.normalize_color(fill_raw_value) if mapping else None)
            self._apply_entity_color(hatch, color_spec, attrs)
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

    def _write_text(self, doc, msp, primitive: SvgPrimitive, attrs, log) -> int:
        position = primitive.points[0]
        content = primitive.extra.get("text", "")
        if not content:
            return 0
        scale_factor = float(primitive.extra.get("text_scale", 1.0) or 1.0)
        height = self._font_size_to_height(primitive.style) * abs(scale_factor)
        text_attrs = dict(attrs)
        text_attrs.setdefault("height", height)
        rotation = float(primitive.extra.get("rotation_deg", 0.0) or 0.0)
        anchor = (primitive.extra or {}).get("text_anchor")
        font_family = primitive.extra.get("font_family")

        style_name = self._ensure_text_style(doc, font_family)
        if style_name:
            text_attrs["style"] = style_name

        if "\n" in content:
            mtext_content = content.replace("\n", "\\P")
            mtext = msp.add_mtext(mtext_content, dxfattribs=text_attrs)
            mtext.set_location(insert=position, rotation=rotation)
            entity = mtext
        else:
            text_entity = msp.add_text(content, dxfattribs=text_attrs)
            text_entity.dxf.insert = position
            text_entity.dxf.rotation = rotation
            entity = text_entity

        anchor = (primitive.extra or {}).get("text_anchor")
        if isinstance(anchor, str):
            anchor = anchor.lower()
        if anchor in {"middle", "center"} and hasattr(entity.dxf, "halign"):
            entity.dxf.halign = 1  # center
            entity.dxf.align_point = position
        elif anchor in {"end", "right"} and hasattr(entity.dxf, "halign"):
            entity.dxf.halign = 2  # right
            entity.dxf.align_point = position
        log.append(f"TEXT '{content[:20]}' h={height:.2f} rot={rotation:.1f}")
        return 1

    @staticmethod
    def _font_size_to_height(style: dict) -> float:
        value = style.get("font-size")
        if not value:
            return 3.5
        length = parse_length(str(value))
        if length <= 0:
            return 3.5
        return length

    def _ensure_text_style(self, doc, font_family: str | None) -> str | None:
        mapping = self.mapping
        font_entry = mapping.resolve_font(font_family) if mapping else None
        style_name = None
        font_name = None

        if font_entry:
            style_name = font_entry.get("style")
            font_name = font_entry.get("font") or font_family

        if not style_name:
            if not font_family:
                return None
            style_name = sanitize_style_name(font_family)
            font_name = font_family

        style_name = sanitize_style_name(style_name)
        if not style_name:
            return None
        if style_name.upper() == "STANDARD":
            return "STANDARD"
        cache_key = style_name.upper()
        if cache_key not in self._style_cache:
            if style_name not in doc.styles:
                try:
                    doc.styles.add(style_name, font=font_name)
                except Exception:
                    try:
                        doc.styles.add(style_name, font="arial.ttf")
                    except Exception:
                        self._style_cache.add("STANDARD")
                        return "STANDARD"
            self._style_cache.add(cache_key)
        return style_name

    def _apply_entity_color(self, entity, color_spec: str | None, fallback_attrs: dict) -> None:
        """Applies color to an entity from a color spec string (ACI or #RRGGBB)."""
        if not color_spec:
            if "true_color" in fallback_attrs:
                entity.rgb = ezdxf_colors.int2rgb(fallback_attrs["true_color"])
            elif "color" in fallback_attrs:
                entity.dxf.color = fallback_attrs["color"]
            return

        if color_spec.upper() in {"BYLAYER", "BYBLOCK"}:
            # Let the entity inherit color from layer/block
            return

        # ACI color index
        if color_spec.isdigit():
            try:
                aci = int(color_spec)
                if 1 <= aci <= 255:
                    entity.dxf.color = aci
                return
            except ValueError:
                pass  # Fallback to other formats

        # Hex color string
        if color_spec.startswith("#"):
            try:
                rgb_int = parse_rgb(color_spec)
                entity.rgb = ezdxf_colors.int2rgb(rgb_int)
            except ValueError:
                pass  # Invalid hex, do nothing


def ensure_layer(doc: ezdxf.EzDxf, layer_name: str, attrs: LayerAttributes) -> None:
    if layer_name in doc.layers:
        return

    color = 7  # Default to white/black
    if attrs.color and attrs.color.isdigit():
        color = int(attrs.color)
    elif attrs.color and attrs.color.startswith("#"):
        try:
            rgb = ezdxf_colors.int2rgb(parse_rgb(attrs.color))
            color = rgb_to_aci(rgb)
        except (ValueError, TypeError):
            color = 7

    doc.layers.add(name=layer_name, color=color, linetype=attrs.linetype or "Continuous")


def sanitize_style_name(name: str) -> str:
    sanitized = []
    for ch in name.strip():
        if ch.isalnum() or ch in "-_":
            sanitized.append(ch)
        elif ch == " ":
            sanitized.append("_")
    value = "".join(sanitized)
    return value[:31] if value else "STANDARD"
