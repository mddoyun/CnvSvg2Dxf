from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

Point = Tuple[float, float]
ColorRGB = Tuple[int, int, int]


@dataclass
class SvgPrimitive:
    """Normalized SVG primitive ready for DXF conversion."""

    kind: str
    points: List[Point] = field(default_factory=list)
    style: Dict[str, Any] = field(default_factory=dict)
    classes: Tuple[str, ...] = field(default_factory=tuple)
    element_id: str | None = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    def label(self) -> str:
        """Human readable name for logs."""
        if self.element_id:
            return f"{self.kind}#{self.element_id}"
        if self.classes:
            return f"{self.kind}({'.'.join(self.classes)})"
        return self.kind


@dataclass
class SvgDocument:
    path: Path
    width_mm: float
    height_mm: float
    viewbox: Tuple[float, float, float, float]
    scale_x: float
    scale_y: float
    primitives: List[SvgPrimitive]
    css_files: List[Path] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> "SvgDocumentSummary":
        counts: Dict[str, int] = {}
        for primitive in self.primitives:
            counts[primitive.kind] = counts.get(primitive.kind, 0) + 1
        return SvgDocumentSummary(
            path=self.path,
            entity_counts=counts,
            total_entities=len(self.primitives),
            warnings=list(self.warnings),
            known_classes=self.collect_classes(),
        )

    def collect_classes(self) -> List[str]:
        seen: set[str] = set()
        for primitive in self.primitives:
            seen.update(primitive.classes)
        return sorted(seen)


@dataclass
class SvgDocumentSummary:
    path: Path
    entity_counts: Dict[str, int]
    total_entities: int
    warnings: List[str] = field(default_factory=list)
    known_classes: List[str] = field(default_factory=list)

    def format_counts(self) -> str:
        return ", ".join(f"{k}: {v}" for k, v in sorted(self.entity_counts.items()))


@dataclass
class MappingRule:
    selector: str
    layer: str
    color: str = "BYLAYER"
    linetype: str = "Continuous"
    lineweight_mm: float | None = None

    def as_row(self) -> List[str]:
        weight = "" if self.lineweight_mm is None else f"{self.lineweight_mm:.2f}"
        return [self.selector, self.layer, self.color, self.linetype, weight]


@dataclass
class LayerAttributes:
    layer: str
    color: str = "BYLAYER"
    linetype: str = "Continuous"
    lineweight_mm: float | None = None

    def to_dxf_attribs(self) -> Dict[str, Any]:
        attribs: Dict[str, Any] = {"layer": self.layer}
        if self.color and self.color.upper() != "BYLAYER":
            attribs["true_color"] = parse_rgb(self.color)
        if self.linetype and self.linetype.upper() != "BYLAYER":
            attribs["linetype"] = self.linetype
        if self.lineweight_mm is not None:
            attribs["lineweight"] = lineweight_to_hundredths_mm(self.lineweight_mm)
        return attribs


@dataclass
class ConversionOptions:
    output_path: Path
    mapping_rules: Iterable[MappingRule] = field(default_factory=list)


@dataclass
class ConversionResult:
    output_path: Path
    written_entities: int
    created_layers: List[str] = field(default_factory=list)
    log_messages: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def parse_rgb(value: str) -> int:
    """Convert color hex value (#RRGGBB) to DXF true color integer."""
    value = value.strip()
    if value.startswith("#"):
        value = value[1:]
    if len(value) != 6:
        raise ValueError(f"Unsupported color value: {value}")
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    return (r << 16) + (g << 8) + b


def lineweight_to_hundredths_mm(weight_mm: float) -> int:
    """Convert millimeter lineweight to DXF integer (1/100 mm)."""
    return int(round(weight_mm * 100))

