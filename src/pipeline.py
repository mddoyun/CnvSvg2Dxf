from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

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

    def load_svg(self, path: Path) -> Tuple[SvgDocument, SvgDocumentSummary]:
        document = self.loader.load(path)
        summary = document.summary()
        return document, summary

    def convert(self, document: SvgDocument, output_path: Path, rules: Iterable[MappingRule] | None = None) -> ConversionResult:
        mapping_rules = list(rules or MappingManager.default_rules())
        mapping_manager = MappingManager.with_defaults(mapping_rules)
        options = ConversionOptions(output_path=output_path, mapping_rules=mapping_rules)
        writer = DxfWriter()
        return writer.write(document, options, mapping_manager)

    def default_rules(self) -> list[MappingRule]:
        return MappingManager.default_rules()
