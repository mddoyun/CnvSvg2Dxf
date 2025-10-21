from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from lxml import etree

CSS_RULE_RE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]+)\}")
COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


@dataclass
class CssRule:
    selector_type: str
    selector_value: str
    properties: Dict[str, Any]


class StyleResolver:
    """Resolve styles combining CSS files, element attributes, and inline rules."""

    def __init__(self, css_files: Iterable[Path] | None = None):
        self.rules: List[CssRule] = []
        css_files = list(css_files or [])
        for path in css_files:
            if path.exists():
                self._load_css(path.read_text(encoding="utf-8"), path)

    def add_css_text(self, text: str) -> None:
        self._load_css(text, None)

    def _load_css(self, text: str, source: Path | None = None) -> None:
        clean = COMMENT_RE.sub("", text)
        for match in CSS_RULE_RE.finditer(clean):
            selectors = [s.strip() for s in match.group("selectors").split(",") if s.strip()]
            properties = self._parse_properties(match.group("body"))
            for selector in selectors:
                selector_type, selector_value = self._parse_selector(selector)
                rule = CssRule(selector_type, selector_value, properties)
                self.rules.append(rule)

    @staticmethod
    def _parse_properties(body: str) -> Dict[str, Any]:
        props: Dict[str, Any] = {}
        for declaration in body.split(";"):
            if not declaration.strip():
                continue
            if ":" not in declaration:
                continue
            name, value = declaration.split(":", 1)
            props[name.strip()] = value.strip()
        return props

    @staticmethod
    def _parse_selector(selector: str) -> Tuple[str, str]:
        if selector.startswith("."):
            return "class", selector[1:]
        if selector.startswith("#"):
            return "id", selector[1:]
        if selector == "*":
            return "universal", "*"
        return "tag", selector.lower()

    def resolve(self, element: etree._Element, extra_style: Dict[str, Any] | None = None) -> Dict[str, Any]:
        style: Dict[str, Any] = {}
        classes = set(self.extract_classes(element))
        elem_id = element.get("id")
        tag = etree.QName(element.tag).localname.lower()

        for rule in self.rules:
            if rule.selector_type == "universal":
                style.update(rule.properties)
            elif rule.selector_type == "tag" and rule.selector_value == tag:
                style.update(rule.properties)
            elif rule.selector_type == "class" and rule.selector_value in classes:
                style.update(rule.properties)
            elif rule.selector_type == "id" and elem_id and rule.selector_value == elem_id:
                style.update(rule.properties)

        style.update(self._attributes_to_style(element))

        inline_style = element.get("style")
        if inline_style:
            style.update(parse_inline_style(inline_style))

        if extra_style:
            style.update(extra_style)
        return style

    @staticmethod
    def extract_classes(element: etree._Element) -> Tuple[str, ...]:
        value = element.get("class")
        if not value:
            return tuple()
        return tuple(cls for cls in value.split(" ") if cls)

    @staticmethod
    def _attributes_to_style(element: etree._Element) -> Dict[str, Any]:
        attrs = {}
        for key in ("stroke", "stroke-width", "stroke-dasharray", "fill", "fill-rule"):
            if key in element.attrib:
                attrs[key] = element.attrib[key]
        return attrs


def parse_inline_style(style_value: str) -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    for part in style_value.split(";"):
        if not part.strip():
            continue
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        properties[name.strip()] = value.strip()
    return properties
