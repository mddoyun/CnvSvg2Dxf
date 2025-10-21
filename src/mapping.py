from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from .models import LayerAttributes, MappingRule, SvgPrimitive, parse_rgb
from .svg_loader import parse_length

STYLE_CONFIG_PATH = Path("ReferenceBonsaiSource/style_mapping.json")
LEGACY_MATERIAL_PATH = Path("ReferenceBonsaiSource/material_layers.json")


DEFAULT_PATTERN_MAP: Dict[str, Dict[str, Any]] = {
    "concrete": {"pattern": "AR-CONC", "scale": 1.0, "angle": 0.0},
    "brick": {"pattern": "AR-BRSTD", "scale": 1.0, "angle": 0.0},
    "glass": {"pattern": "AR-SHINGLE", "scale": 1.0, "angle": 0.0},
    "sand": {"pattern": "AR-SAND", "scale": 1.0, "angle": 0.0},
    "wood": {"pattern": "AR-WOOD", "scale": 1.0, "angle": 0.0},
    "steel": {"pattern": "ANSI37", "scale": 1.0, "angle": 0.0},
    "diagonal1": {"pattern": "ANSI45", "scale": 1.0, "angle": 0.0},
    "diagonal2": {"pattern": "ANSI45", "scale": 0.5, "angle": 0.0},
    "diagonal3": {"pattern": "ANSI45", "scale": 0.33, "angle": 0.0},
    "crosshatch1": {"pattern": "ANSI31", "scale": 1.0, "angle": 0.0},
    "crosshatch2": {"pattern": "ANSI31", "scale": 0.5, "angle": 0.0},
    "crosshatch3": {"pattern": "ANSI31", "scale": 0.33, "angle": 0.0},
    "square1": {"pattern": "AR-SQUARE", "scale": 1.0, "angle": 0.0},
    "square2": {"pattern": "AR-SQUARE", "scale": 0.5, "angle": 0.0},
    "square3": {"pattern": "AR-SQUARE", "scale": 0.33, "angle": 0.0},
    "honeycomb": {"pattern": "AR-HBONE", "scale": 1.0, "angle": 0.0},
    "earth": {"pattern": "AR-EARTH", "scale": 1.0, "angle": 0.0},
    "liquid": {"pattern": "AR-RIPPLE", "scale": 1.0, "angle": 0.0},
    "grass": {"pattern": "AR-SAND", "scale": 0.75, "angle": 0.0},
}

DEFAULT_FONT_MAP: Dict[str, Dict[str, Any]] = {
    "opengost type b tt": {"style": "OpenGost_Type_B_TT"}
}

CSS_COLOR_MAP: Dict[str, str] = {
    "black": "#000000",
    "white": "#FFFFFF",
    "red": "#FF0000",
    "green": "#00FF00",
    "blue": "#0000FF",
    "yellow": "#FFFF00",
    "magenta": "#FF00FF",
    "cyan": "#00FFFF",
    "gray": "#808080",
    "grey": "#808080",
    "lightgray": "#D3D3D3",
    "darkgray": "#404040",
}


def _load_style_config() -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    materials: Dict[str, Any] = {}
    patterns: Dict[str, Any] = {}
    fonts: Dict[str, Any] = {}
    if STYLE_CONFIG_PATH.exists():
        try:
            data = json.loads(STYLE_CONFIG_PATH.read_text(encoding="utf-8"))
            materials = data.get("materials", {}) if isinstance(data, dict) else {}
            patterns = data.get("patterns", {}) if isinstance(data, dict) else {}
            fonts = data.get("fonts", {}) if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            pass
    elif LEGACY_MATERIAL_PATH.exists():
        try:
            materials = json.loads(LEGACY_MATERIAL_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return materials, patterns, fonts


def _normalize_material_map(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        key_clean = key.strip()
        if not key_clean:
            continue
        entry: Dict[str, Any] = {}
        if isinstance(value, str):
            entry["layer"] = value.strip()
        elif isinstance(value, dict):
            for field in ("layer", "color", "linetype", "lineweight"):
                if field in value and value[field] not in (None, ""):
                    entry[field] = value[field]
        if entry:
            result[key_clean] = entry
    return result


def _normalize_pattern_map(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        key_clean = key.strip()
        if not key_clean:
            continue
        entry: Dict[str, Any] = {}
        if isinstance(value, str):
            entry["pattern"] = value
        elif isinstance(value, dict):
            for field in ("pattern", "scale", "angle", "color", "solid"):
                if field in value and value[field] not in (None, ""):
                    entry[field] = value[field]
        if entry:
            result[key_clean] = _coerce_pattern_entry(entry)
    return result


def _coerce_pattern_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    coerced = dict(entry)
    if "scale" in coerced:
        try:
            coerced["scale"] = float(coerced["scale"])
        except (TypeError, ValueError):
            pass
    if "angle" in coerced:
        try:
            coerced["angle"] = float(coerced["angle"])
        except (TypeError, ValueError):
            pass
    if "solid" in coerced:
        value = coerced["solid"]
        if isinstance(value, str):
            coerced["solid"] = value.strip().lower() in {"true", "1", "yes", "y"}
        else:
            coerced["solid"] = bool(value)
    return coerced


def _normalize_font_map(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        key_clean = key.strip()
        if not key_clean:
            continue
        entry: Dict[str, Any] = {}
        if isinstance(value, str):
            entry["style"] = value.strip()
        elif isinstance(value, dict):
            for field in ("style", "font"):
                if field in value and value[field] not in (None, ""):
                    entry[field] = value[field]
        if entry:
            if "style" in entry:
                entry["style"] = sanitize_style_name(str(entry["style"]))
            result[key_clean] = entry
    return result


@dataclass
class MappingManager:
    rules: List[MappingRule] = field(default_factory=list)
    material_layers: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    pattern_map: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    font_map: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    _material_alias: Dict[str, str] = field(default_factory=dict, init=False)
    _pattern_alias: Dict[str, str] = field(default_factory=dict, init=False)
    _font_alias: Dict[str, str] = field(default_factory=dict, init=False)

    @classmethod
    def with_defaults(cls, overrides: Iterable[MappingRule] | None = None) -> "MappingManager":
        materials_raw, patterns_raw, fonts_raw = _load_style_config()
        materials = _normalize_material_map(materials_raw)
        patterns = {key: _coerce_pattern_entry(value) for key, value in DEFAULT_PATTERN_MAP.items()}
        normalized_patterns = _normalize_pattern_map(patterns_raw)
        for key, value in normalized_patterns.items():
            patterns[key] = _coerce_pattern_entry(value)
        fonts = {key: dict(value) for key, value in DEFAULT_FONT_MAP.items()}
        normalized_fonts = _normalize_font_map(fonts_raw)
        for key, value in normalized_fonts.items():
            fonts[key] = dict(value)

        rules = cls.default_rules()
        if overrides:
            rules = list(overrides)

        manager = cls(
            rules=list(rules),
            material_layers=materials,
            pattern_map=patterns,
            font_map=fonts,
        )
        manager._rebuild_aliases()
        return manager

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

    def _rebuild_aliases(self) -> None:
        self._material_alias = {key.lower(): key for key in self.material_layers}
        self._pattern_alias = {key.lower(): key for key in self.pattern_map}
        self._font_alias = {key.lower(): key for key in self.font_map}

    # Configuration management -------------------------------------------------
    def set_material_map(self, mapping: Dict[str, Dict[str, Any]]) -> None:
        self.material_layers = _normalize_material_map(mapping)
        self._rebuild_aliases()

    def set_pattern_map(self, mapping: Dict[str, Dict[str, Any]]) -> None:
        normalized = _normalize_pattern_map(mapping)
        combined = {key: _coerce_pattern_entry(value) for key, value in DEFAULT_PATTERN_MAP.items()}
        for key, value in normalized.items():
            combined[key] = _coerce_pattern_entry(value)
        self.pattern_map = combined
        self._rebuild_aliases()

    def set_font_map(self, mapping: Dict[str, Dict[str, Any]]) -> None:
        normalized = _normalize_font_map(mapping)
        combined = {key: dict(value) for key, value in DEFAULT_FONT_MAP.items()}
        for key, value in normalized.items():
            combined[key] = dict(value)
        self.font_map = combined
        self._rebuild_aliases()

    def save_config(self) -> None:
        materials = {key: self._clean_dict(value) for key, value in self.material_layers.items()}
        patterns: Dict[str, Dict[str, Any]] = {}
        for key, value in self.pattern_map.items():
            default = DEFAULT_PATTERN_MAP.get(key)
            if default and self._dicts_equal(value, default):
                continue
            patterns[key] = self._clean_dict(value)
        fonts: Dict[str, Dict[str, Any]] = {}
        for key, value in self.font_map.items():
            default = DEFAULT_FONT_MAP.get(key)
            if default and self._dicts_equal(value, default):
                continue
            fonts[key] = self._clean_dict(value)
        data = {
            "materials": materials,
            "patterns": patterns,
            "fonts": fonts,
        }
        STYLE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        STYLE_CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    @staticmethod
    def _clean_dict(value: Dict[str, Any]) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        for key, val in value.items():
            if val in (None, ""):
                continue
            if isinstance(val, float):
                cleaned[key] = float(f"{val:.6f}")
            else:
                cleaned[key] = val
        return cleaned

    @staticmethod
    def _dicts_equal(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        keys = set(a.keys()) | set(b.keys())
        for key in keys:
            va = a.get(key)
            vb = b.get(key)
            if isinstance(va, (int, float)) or isinstance(vb, (int, float)):
                try:
                    if float(va) == float(vb):
                        continue
                except (TypeError, ValueError):
                    return False
                return False
            if va != vb:
                return False
        return True

    def get_material_map(self) -> Dict[str, Dict[str, Any]]:
        return {key: dict(value) for key, value in self.material_layers.items()}

    def get_pattern_map(self) -> Dict[str, Dict[str, Any]]:
        return {key: dict(value) for key, value in self.pattern_map.items()}

    def get_font_map(self) -> Dict[str, Dict[str, Any]]:
        return {key: dict(value) for key, value in self.font_map.items()}

    # Resolution ----------------------------------------------------------------
    def resolve(self, primitive: SvgPrimitive) -> LayerAttributes:
        material_classes = [cls for cls in primitive.classes if cls.startswith("material-")]
        if material_classes:
            material = material_classes[0]
            return self._material_attributes(material, primitive)

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
        if isinstance(value, str) and value not in {"none", "transparent"} and value.startswith("#"):
            return normalize_hex(value)
        fill = primitive.style.get("fill")
        if isinstance(fill, str):
            fill = fill.strip()
        if isinstance(fill, str) and fill not in {"none", "transparent"} and fill.startswith("#"):
            return normalize_hex(fill)
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

    def _material_attributes(self, material_class: str, primitive: SvgPrimitive) -> LayerAttributes:
        key = self._material_alias.get(material_class.lower())
        short = None
        if not key and "-" in material_class:
            short = material_class.split("-", 1)[1]
            key = self._material_alias.get(short.lower())
        config = self.material_layers.get(key) if key else None

        short_key = short or (material_class.split("-", 1)[1] if "-" in material_class else material_class)
        default_layer = f"MAT-{_sanitize_layer_name(short_key)}"
        default_color = self._color_from_style(primitive)
        default_lineweight = self._lineweight_from_style(primitive)
        default_linetype = "Continuous"

        if config is None:
            return LayerAttributes(layer=default_layer, color=default_color, linetype=default_linetype, lineweight_mm=default_lineweight)

        layer = config.get("layer", default_layer)
        color = parse_color_spec(config.get("color"), default_color)
        linetype = config.get("linetype", default_linetype)
        lineweight = default_lineweight
        lw_value = config.get("lineweight")
        if isinstance(lw_value, (int, float)):
            lineweight = float(lw_value)
        elif isinstance(lw_value, str):
            try:
                lineweight = float(lw_value)
            except ValueError:
                try:
                    lineweight = parse_length(lw_value)
                except Exception:
                    pass

        return LayerAttributes(layer=layer, color=color, linetype=linetype, lineweight_mm=lineweight)

    # Pattern / font helpers ---------------------------------------------------
    def extract_pattern_id(self, fill_value: str | None) -> str | None:
        if not fill_value:
            return None
        value = fill_value.strip()
        if not value.lower().startswith("url("):
            return None
        inside = value[4:-1].strip()
        if inside.startswith("#"):
            inside = inside[1:]
        if not inside:
            return None
        return inside.lower()

    def resolve_pattern(self, pattern_id: str | None) -> Dict[str, Any] | None:
        if not pattern_id:
            return None
        key = self._pattern_alias.get(pattern_id.lower())
        if not key:
            return None
        return self.pattern_map.get(key)

    def normalize_color(self, value: str | None, fallback: str | None = None) -> str | None:
        return parse_color_spec(value, fallback)

    def resolve_font(self, font_family: str | None) -> Dict[str, Any] | None:
        if not font_family:
            return None
        key = self._font_alias.get(font_family.lower())
        if not key:
            return None
        entry = self.font_map.get(key)
        if not entry:
            return None
        style = entry.get("style")
        if style:
            entry = dict(entry)
            entry["style"] = sanitize_style_name(str(style))
        return entry

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


def sanitize_style_name(name: str) -> str:
    sanitized = []
    for char in name.strip():
        if char.isalnum() or char in "-_":
            sanitized.append(char)
        elif char == " ":
            sanitized.append("_")
    value = "".join(sanitized)
    return value[:31] if value else "STANDARD"


def parse_color_spec(value: str | None, fallback: str | None = None) -> str | None:
    if not value:
        return fallback
    spec = value.strip()
    if not spec:
        return fallback
    if spec.lower() == "bylayer":
        return "BYLAYER"
    if spec.lower() == "byblock":
        return "BYBLOCK"
    if spec.startswith("#"):
        try:
            return normalize_hex(spec)
        except ValueError:
            return fallback
    css = CSS_COLOR_MAP.get(spec.lower())
    if css:
        return css
    return fallback


def normalize_hex(value: str) -> str:
    if not value.startswith("#"):
        raise ValueError("Not a hex color")
    hex_value = value[1:]
    if len(hex_value) == 3:
        hex_value = "".join(ch * 2 for ch in hex_value)
    if len(hex_value) != 6:
        raise ValueError("Hex color must be 3 or 6 digits")
    int(hex_value, 16)
    return f"#{hex_value.upper()}"
