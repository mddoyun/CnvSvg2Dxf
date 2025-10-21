from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from .svg_loader import parse_length

from .models import LayerAttributes, MappingRule, SvgPrimitive


@dataclass
class MappingManager:
    rules: List[MappingRule]

    @classmethod
    def with_defaults(cls, overrides: Iterable[MappingRule] | None = None) -> "MappingManager":
        rules = cls.default_rules()
        if overrides:
            rules = list(overrides)
        return cls(rules=list(rules))

    @staticmethod
    def default_rules() -> List[MappingRule]:
        return [
            MappingRule("class:IfcWall*", "A-WALL", "#000000", "Continuous", 0.35),
            MappingRule("class:IfcSlab*", "A-SLAB", "#000000", "Continuous", 0.35),
            MappingRule("class:IfcColumn*", "A-COLU", "#000000", "Continuous", 0.35),
            MappingRule("class:IfcBeam*", "A-BEAM", "#000000", "Continuous", 0.35),
            MappingRule("class:IfcDoor*", "A-DOOR", "#000000", "Continuous", 0.25),
            MappingRule("class:IfcWindow*", "A-WIN", "#000000", "Continuous", 0.25),
            MappingRule("class:PredefinedType-DIMENSION", "A-DIMS", "#000000", "Continuous", 0.18),
            MappingRule("class:DIMENSION", "A-DIMS", "#000000", "Continuous", 0.18),
            MappingRule("class:PredefinedType-TEXT", "A-ANNO", "#000000", "Continuous", 0.18),
            MappingRule("class:annotation", "A-ANNO", "#000000", "Continuous", 0.18),
            MappingRule("class:IfcAnnotation*", "A-ANNO", "#000000", "Continuous", 0.18),
            MappingRule("class:GRID", "A-GRID", "#000000", "Continuous", 0.18),
            MappingRule("class:PredefinedType-GRID", "A-GRID", "#000000", "Continuous", 0.18),
            MappingRule("tag:text", "A-TEXT", "#000000", "Continuous", 0.18),
            MappingRule("any", "0", "BYLAYER", "Continuous", None),
        ]

    def resolve(self, primitive: SvgPrimitive) -> LayerAttributes:
        material_classes = [cls for cls in primitive.classes if cls.startswith("material-")]
        if material_classes:
            material = material_classes[0]
            layer_suffix = material.split("-", 1)[1] if "-" in material else material
            layer_name = f"MAT-{_sanitize_layer_name(layer_suffix)}"
            color = self._color_from_style(primitive)
            lineweight = self._lineweight_from_style(primitive)
            return LayerAttributes(layer=layer_name, color=color, linetype="Continuous", lineweight_mm=lineweight)

        for rule in self.rules:
            if self._matches_selector(primitive, rule.selector):
                return LayerAttributes(
                    layer=rule.layer or "0",
                    color=rule.color or self._color_from_style(primitive),
                    linetype=rule.linetype or self._linetype_from_style(primitive),
                    lineweight_mm=rule.lineweight_mm if rule.lineweight_mm is not None else self._lineweight_from_style(primitive),
                )

        return LayerAttributes(
            layer="0",
            color=self._color_from_style(primitive),
            linetype=self._linetype_from_style(primitive),
            lineweight_mm=self._lineweight_from_style(primitive),
        )

    def _matches_selector(self, primitive: SvgPrimitive, selector: str) -> bool:
        selector = selector.strip()
        if not selector:
            return False
        if selector.lower() == "any":
            return True
        if ":" not in selector:
            return False
        selector_type, selector_value = selector.split(":", 1)
        selector_type = selector_type.strip().lower()
        selector_value = selector_value.strip()
        if selector_type == "class":
            return any(fnmatch.fnmatch(cls, selector_value) for cls in primitive.classes)
        if selector_type == "tag":
            return fnmatch.fnmatch(primitive.kind, selector_value)
        if selector_type == "id":
            return primitive.element_id is not None and fnmatch.fnmatch(primitive.element_id, selector_value)
        if selector_type == "attr" and "=" in selector_value:
            name, value = [part.strip() for part in selector_value.split("=", 1)]
            attr_value = primitive.attributes.get(name)
            return attr_value is not None and fnmatch.fnmatch(str(attr_value), value)
        if selector_type == "style" and "=" in selector_value:
            name, value = [part.strip() for part in selector_value.split("=", 1)]
            style_value = primitive.style.get(name)
            return style_value is not None and fnmatch.fnmatch(str(style_value), value)
        return False

    @staticmethod
    def _color_from_style(primitive: SvgPrimitive) -> str:
        value = primitive.style.get("stroke")
        if isinstance(value, str):
            value = value.strip()
        if isinstance(value, str) and value not in {"none", "transparent"} and value.startswith("#") and len(value) in {4, 7}:
            if len(value) == 4:
                r, g, b = value[1], value[2], value[3]
                value = f"#{r}{r}{g}{g}{b}{b}"
            return value
        fill = primitive.style.get("fill")
        if isinstance(fill, str):
            fill = fill.strip()
        if isinstance(fill, str) and fill not in {"none", "transparent"} and fill.startswith("#") and len(fill) in {4, 7}:
            if len(fill) == 4:
                r, g, b = fill[1], fill[2], fill[3]
                fill = f"#{r}{r}{g}{g}{b}{b}"
            return fill
        return "BYLAYER"

    @staticmethod
    def _lineweight_from_style(primitive: SvgPrimitive) -> float | None:
        value = primitive.style.get("stroke-width")
        if not value:
            return None
        value = str(value).strip()
        try:
            return float(value)
        except ValueError:
            try:
                return parse_length(value)
            except Exception:
                return None

    @staticmethod
    def _linetype_from_style(primitive: SvgPrimitive) -> str:
        dash = primitive.style.get("stroke-dasharray")
        if dash and dash not in {"none", "0"}:
            return "DASHED"
        return "Continuous"

    def to_rules(self) -> List[MappingRule]:
        return list(self.rules)


def _sanitize_layer_name(value: str) -> str:
    sanitized = []
    for char in value.upper():
        if char.isalnum() or char in "-_":
            sanitized.append(char)
        else:
            sanitized.append("_")
    return "".join(sanitized) or "MATERIAL"
