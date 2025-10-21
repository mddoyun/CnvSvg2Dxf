from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from .dxf_writer import DxfWriter
from .mapping import MappingManager
from .models import ConversionOptions, ConversionResult, MappingRule, SvgDocument, SvgDocumentSummary
from .svg_loader import SvgLoader


class PipelineController:
    def __init__(self, css_paths: Iterable[Path] | None = None):
        css_paths = list(css_paths or [])
        default_css = Path("ReferenceBonsaiSource/default.css")
        if default_css.exists() and default_css not in css_paths:
            css_paths.append(default_css)
        self.css_paths = css_paths
        self.loader = SvgLoader(css_files=self.css_paths)
        self.mapping_manager = MappingManager.with_defaults()

    def load_svg(self, path: Path) -> Tuple[SvgDocument, SvgDocumentSummary]:
        document = self.loader.load(path)
        summary = document.summary()
        return document, summary

    def convert(self, document: SvgDocument, output_path: Path, rules: Iterable[MappingRule] | None = None) -> ConversionResult:
        if rules is not None:
            self.mapping_manager.rules = list(rules)
        options = ConversionOptions(output_path=output_path, mapping_rules=self.mapping_manager.to_rules())
        writer = DxfWriter()
        return writer.write(document, options, self.mapping_manager)

    def default_rules(self) -> list[MappingRule]:
        return self.mapping_manager.to_rules()

    # Mapping configuration helpers -----------------------------------------
    def get_material_map(self) -> Dict[str, Dict[str, Any]]:
        return self.mapping_manager.get_material_map()

    def get_pattern_map(self) -> Dict[str, Dict[str, Any]]:
        return self.mapping_manager.get_pattern_map()

    def get_font_map(self) -> Dict[str, Dict[str, Any]]:
        return self.mapping_manager.get_font_map()

    def update_mapping_config(
        self,
        materials: Dict[str, Dict[str, Any]],
        patterns: Dict[str, Dict[str, Any]],
        fonts: Dict[str, Dict[str, Any]],
    ) -> None:
        self.mapping_manager.set_material_map(materials)
        self.mapping_manager.set_pattern_map(patterns)
        self.mapping_manager.set_font_map(fonts)

    def save_mapping_config(self) -> None:
        self.mapping_manager.save_config()
