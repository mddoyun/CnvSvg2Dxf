from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..mapping import MappingManager
from ..models import MappingRule, SvgDocument
from ..pipeline import PipelineController


def sanitize_style_name(name: str) -> str:
    sanitized = []
    for ch in name.strip():
        if ch.isalnum() or ch in "-_":
            sanitized.append(ch)
        elif ch == " ":
            sanitized.append("_")
    value = "".join(sanitized)
    return value[:31] if value else "STANDARD"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SVG → DXF 변환기 (Prototype)")
        self.resize(1080, 720)

        self.controller = PipelineController()
        self.current_document: SvgDocument | None = None

        self._init_ui()
        self._populate_default_rules()

    def _init_ui(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        self.setCentralWidget(container)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._init_convert_tab()
        self._init_mapping_tab()

    def _init_convert_tab(self) -> None:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(12, 12, 12, 12)

        # Input selection
        input_layout = QHBoxLayout()
        self.input_path_edit = QLineEdit()
        self.input_path_edit.setPlaceholderText("SVG 파일 경로")
        browse_input_btn = QPushButton("찾기…")
        browse_input_btn.clicked.connect(self._browse_input)
        input_layout.addWidget(QLabel("SVG 파일:"))
        input_layout.addWidget(self.input_path_edit)
        input_layout.addWidget(browse_input_btn)
        tab_layout.addLayout(input_layout)

        # Output selection
        output_layout = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("DXF 출력 경로")
        browse_output_btn = QPushButton("찾기…")
        browse_output_btn.clicked.connect(self._browse_output)
        output_layout.addWidget(QLabel("DXF 파일:"))
        output_layout.addWidget(self.output_path_edit)
        output_layout.addWidget(browse_output_btn)
        tab_layout.addLayout(output_layout)

        # Actions
        button_layout = QHBoxLayout()
        load_btn = QPushButton("SVG 로드")
        load_btn.clicked.connect(self._load_svg)
        convert_btn = QPushButton("DXF 변환")
        convert_btn.clicked.connect(self._convert_to_dxf)
        button_layout.addWidget(load_btn)
        button_layout.addWidget(convert_btn)
        button_layout.addStretch()
        tab_layout.addLayout(button_layout)

        # Summary
        self.summary_label = QLabel("SVG 파일을 로드하면 요약이 표시됩니다.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setFrameStyle(QLabel.Panel | QLabel.Sunken)
        self.summary_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.summary_label.setMinimumHeight(80)
        tab_layout.addWidget(self.summary_label)

        # Log
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_output.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        tab_layout.addWidget(QLabel("변환 로그:"))
        tab_layout.addWidget(self.log_output, stretch=1)

        self.tabs.addTab(tab, "변환")

    def _init_mapping_tab(self) -> None:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(12, 12, 12, 12)

        self.rules_table = QTableWidget(0, 5)
        self.rules_table.setHorizontalHeaderLabels(["Selector", "Layer", "Color", "Linetype", "Lineweight (mm)"])
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        tab_layout.addWidget(QLabel("레이어/스타일 매핑 규칙"))
        tab_layout.addWidget(self.rules_table)

        button_layout = QHBoxLayout()
        add_btn = QPushButton("규칙 추가")
        add_btn.clicked.connect(self._add_rule)
        remove_btn = QPushButton("선택 삭제")
        remove_btn.clicked.connect(self._remove_rule)
        reset_btn = QPushButton("기본값 복원")
        reset_btn.clicked.connect(self._reset_rules)
        button_layout.addWidget(add_btn)
        button_layout.addWidget(remove_btn)
        button_layout.addWidget(reset_btn)
        button_layout.addStretch()
        tab_layout.addLayout(button_layout)

        helper = QLabel(
            "Selector 예시: 'class:IfcWall*', 'tag:polyline', 'attr:ifc:guid=*', 'style:stroke=#ff0000', 'any'\n"
            "Lineweight는 mm 단위 숫자이며 비워두면 스타일에서 자동으로 추정합니다."
        )
        helper.setWordWrap(True)
        tab_layout.addWidget(helper)

        tab_layout.addSpacing(16)
        tab_layout.addWidget(QLabel("재료 레이어 매핑 (.material-* 클래스)"))
        self.material_table = QTableWidget(0, 5)
        self.material_table.setHorizontalHeaderLabels(["Material Class", "Layer", "Color", "Linetype", "Lineweight (mm)"])
        self.material_table.horizontalHeader().setStretchLastSection(True)
        tab_layout.addWidget(self.material_table)

        material_btn_layout = QHBoxLayout()
        material_add = QPushButton("재료 추가")
        material_add.clicked.connect(self._add_material_entry)
        material_remove = QPushButton("선택 삭제")
        material_remove.clicked.connect(self._remove_material_entry)
        material_btn_layout.addWidget(material_add)
        material_btn_layout.addWidget(material_remove)
        material_btn_layout.addStretch()
        tab_layout.addLayout(material_btn_layout)

        material_helper = QLabel("예: material-concrete → A-CONC, 색상은 #RRGGBB 또는 BYLAYER 입력")
        material_helper.setWordWrap(True)
        tab_layout.addWidget(material_helper)

        tab_layout.addSpacing(16)
        tab_layout.addWidget(QLabel("패턴 매핑 (fill: url(#pattern))"))
        self.pattern_table = QTableWidget(0, 6)
        self.pattern_table.setHorizontalHeaderLabels(["Pattern ID", "DXF Pattern", "Scale", "Angle", "Color", "Solid"])
        self.pattern_table.horizontalHeader().setStretchLastSection(True)
        tab_layout.addWidget(self.pattern_table)

        pattern_btn_layout = QHBoxLayout()
        pattern_add = QPushButton("패턴 추가")
        pattern_add.clicked.connect(self._add_pattern_entry)
        pattern_remove = QPushButton("선택 삭제")
        pattern_remove.clicked.connect(self._remove_pattern_entry)
        pattern_btn_layout.addWidget(pattern_add)
        pattern_btn_layout.addWidget(pattern_remove)
        pattern_btn_layout.addStretch()
        tab_layout.addLayout(pattern_btn_layout)

        pattern_helper = QLabel("패턴 ID는 SVG의 <pattern id> 값입니다. Solid 는 'Y' 또는 'N'.")
        pattern_helper.setWordWrap(True)
        tab_layout.addWidget(pattern_helper)

        tab_layout.addSpacing(16)
        tab_layout.addWidget(QLabel("폰트 매핑 (font-family)"))
        self.font_table = QTableWidget(0, 3)
        self.font_table.setHorizontalHeaderLabels(["Font Family", "DXF Text Style", "Font File"])
        self.font_table.horizontalHeader().setStretchLastSection(True)
        tab_layout.addWidget(self.font_table)

        font_btn_layout = QHBoxLayout()
        font_add = QPushButton("폰트 추가")
        font_add.clicked.connect(self._add_font_entry)
        font_remove = QPushButton("선택 삭제")
        font_remove.clicked.connect(self._remove_font_entry)
        font_btn_layout.addWidget(font_add)
        font_btn_layout.addWidget(font_remove)
        font_btn_layout.addStretch()
        tab_layout.addLayout(font_btn_layout)

        font_helper = QLabel("SVG font-family 값과 사용할 DXF Text Style/폰트 파일을 매핑하세요.")
        font_helper.setWordWrap(True)
        tab_layout.addWidget(font_helper)

        self.save_mapping_btn = QPushButton("맵핑 저장")
        self.save_mapping_btn.clicked.connect(self._save_mapping_config)
        tab_layout.addWidget(self.save_mapping_btn, alignment=Qt.AlignRight)

        self.tabs.addTab(tab, "레이어 매핑")

    def _populate_default_rules(self) -> None:
        self.rules_table.setRowCount(0)
        for rule in self.controller.default_rules():
            self._insert_rule_row(rule)
        self._populate_material_table()
        self._populate_pattern_table()
        self._populate_font_table()

    def _insert_rule_row(self, rule: MappingRule) -> None:
        row = self.rules_table.rowCount()
        self.rules_table.insertRow(row)
        for column, value in enumerate(rule.as_row()):
            self._set_table_item(self.rules_table, row, column, value)

    def _set_table_item(self, table: QTableWidget, row: int, column: int, value: Any) -> None:
        text = "" if value is None else str(value)
        table.setItem(row, column, QTableWidgetItem(text))

    def _populate_material_table(self) -> None:
        self.material_table.setRowCount(0)
        materials = self.controller.get_material_map()
        for material in sorted(materials.keys()):
            entry = materials[material]
            row = self.material_table.rowCount()
            self.material_table.insertRow(row)
            self._set_table_item(self.material_table, row, 0, material)
            self._set_table_item(self.material_table, row, 1, entry.get("layer", ""))
            self._set_table_item(self.material_table, row, 2, entry.get("color", ""))
            self._set_table_item(self.material_table, row, 3, entry.get("linetype", ""))
            self._set_table_item(self.material_table, row, 4, entry.get("lineweight", ""))

    def _populate_pattern_table(self) -> None:
        self.pattern_table.setRowCount(0)
        patterns = self.controller.get_pattern_map()
        for pattern_id in sorted(patterns.keys()):
            entry = patterns[pattern_id]
            row = self.pattern_table.rowCount()
            self.pattern_table.insertRow(row)
            self._set_table_item(self.pattern_table, row, 0, pattern_id)
            self._set_table_item(self.pattern_table, row, 1, entry.get("pattern", ""))
            self._set_table_item(self.pattern_table, row, 2, entry.get("scale", ""))
            self._set_table_item(self.pattern_table, row, 3, entry.get("angle", ""))
            self._set_table_item(self.pattern_table, row, 4, entry.get("color", ""))
            solid_value = entry.get("solid", "")
            if isinstance(solid_value, bool):
                solid_value = "Y" if solid_value else "N"
            self._set_table_item(self.pattern_table, row, 5, solid_value)

    def _populate_font_table(self) -> None:
        self.font_table.setRowCount(0)
        fonts = self.controller.get_font_map()
        for family in sorted(fonts.keys()):
            entry = fonts[family]
            row = self.font_table.rowCount()
            self.font_table.insertRow(row)
            self._set_table_item(self.font_table, row, 0, family)
            self._set_table_item(self.font_table, row, 1, entry.get("style", ""))
            self._set_table_item(self.font_table, row, 2, entry.get("font", ""))

    # Slots / event handlers -------------------------------------------------

    def _browse_input(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "SVG 파일 선택", "", "SVG (*.svg)")
        if file_path:
            self.input_path_edit.setText(file_path)

    def _browse_output(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(self, "DXF 파일 저장", "", "DXF (*.dxf)")
        if file_path:
            if not file_path.lower().endswith(".dxf"):
                file_path += ".dxf"
            self.output_path_edit.setText(file_path)

    def _load_svg(self) -> None:
        path_text = self.input_path_edit.text().strip()
        if not path_text:
            self._show_error("SVG 파일 경로를 입력해 주세요.")
            return

        path = Path(path_text)
        if not path.exists():
            self._show_error("SVG 파일을 찾을 수 없습니다.")
            return

        document, summary = self.controller.load_svg(path)
        self.current_document = document

        summary_text = [
            f"파일: {summary.path.name}",
            f"요소 수: {summary.total_entities}",
            f"종류별: {summary.format_counts()}",
        ]
        if summary.warnings:
            summary_text.append("경고:")
            summary_text.extend(f"  - {w}" for w in summary.warnings[:10])
            if len(summary.warnings) > 10:
                summary_text.append(f"  … 총 {len(summary.warnings)}건")

        self.summary_label.setText("\n".join(summary_text))
        self.statusBar().showMessage("SVG 로드 완료", 3000)

    def _convert_to_dxf(self) -> None:
        if self.current_document is None:
            self._show_error("먼저 SVG 파일을 로드해 주세요.")
            return

        output_text = self.output_path_edit.text().strip()
        if not output_text:
            self._show_error("DXF 출력 경로를 지정해 주세요.")
            return

        output_path = Path(output_text)
        rules = self._apply_mapping_changes(save=False)

        result = self.controller.convert(self.current_document, output_path, rules)

        self.log_output.clear()
        if result.log_messages:
            self.log_output.appendPlainText("\n".join(result.log_messages))
        if result.warnings:
            self.log_output.appendPlainText("\n경고:")
            self.log_output.appendPlainText("\n".join(result.warnings))

        message = (
            f"DXF 변환 완료: {output_path}\n"
            f"엔티티 {result.written_entities}개 작성, 생성된 레이어 {len(result.created_layers)}개"
        )
        QMessageBox.information(self, "완료", message)
        self.statusBar().showMessage("DXF 변환 완료", 3000)

    def _collect_rules_from_table(self) -> List[MappingRule]:
        rules: List[MappingRule] = []
        for row in range(self.rules_table.rowCount()):
            selector = self._item_text(row, 0)
            if not selector:
                continue
            layer = self._item_text(row, 1) or "0"
            color = self._item_text(row, 2) or "BYLAYER"
            linetype = self._item_text(row, 3) or "Continuous"
            weight_text = self._item_text(row, 4)
            lineweight = None
            if weight_text:
                try:
                    lineweight = float(weight_text)
                except ValueError:
                    self.log_output.appendPlainText(f"경고: 행 {row + 1}의 선굵기 값이 잘못되었습니다. ({weight_text})")
            rules.append(MappingRule(selector=selector, layer=layer, color=color, linetype=linetype, lineweight_mm=lineweight))
        return rules

    def _collect_material_mapping(self) -> Dict[str, Dict[str, Any]]:
        mapping: Dict[str, Dict[str, Any]] = {}
        for row in range(self.material_table.rowCount()):
            material = self._item_text(row, 0, self.material_table)
            if not material:
                continue
            entry: Dict[str, Any] = {}
            layer = self._item_text(row, 1, self.material_table)
            if layer:
                entry["layer"] = layer
            color = self._item_text(row, 2, self.material_table)
            if color:
                entry["color"] = color
            linetype = self._item_text(row, 3, self.material_table)
            if linetype:
                entry["linetype"] = linetype
            weight_text = self._item_text(row, 4, self.material_table)
            if weight_text:
                entry["lineweight"] = weight_text
            if entry:
                mapping[material] = entry
        return mapping

    def _collect_pattern_mapping(self) -> Dict[str, Dict[str, Any]]:
        mapping: Dict[str, Dict[str, Any]] = {}
        for row in range(self.pattern_table.rowCount()):
            pattern_id = self._item_text(row, 0, self.pattern_table)
            if not pattern_id:
                continue
            entry: Dict[str, Any] = {}
            pattern_name = self._item_text(row, 1, self.pattern_table)
            if pattern_name:
                entry["pattern"] = pattern_name
            scale_text = self._item_text(row, 2, self.pattern_table)
            if scale_text:
                try:
                    entry["scale"] = float(scale_text)
                except ValueError:
                    self.log_output.appendPlainText(f"경고: 패턴 '{pattern_id}'의 Scale 값을 해석할 수 없습니다: {scale_text}")
            angle_text = self._item_text(row, 3, self.pattern_table)
            if angle_text:
                try:
                    entry["angle"] = float(angle_text)
                except ValueError:
                    self.log_output.appendPlainText(f"경고: 패턴 '{pattern_id}'의 Angle 값을 해석할 수 없습니다: {angle_text}")
            color = self._item_text(row, 4, self.pattern_table)
            if color:
                entry["color"] = color
            solid_text = self._item_text(row, 5, self.pattern_table)
            if solid_text:
                entry["solid"] = solid_text
            if entry:
                mapping[pattern_id] = entry
        return mapping

    def _collect_font_mapping(self) -> Dict[str, Dict[str, Any]]:
        mapping: Dict[str, Dict[str, Any]] = {}
        for row in range(self.font_table.rowCount()):
            family = self._item_text(row, 0, self.font_table)
            if not family:
                continue
            entry: Dict[str, Any] = {}
            style = self._item_text(row, 1, self.font_table)
            if style:
                entry["style"] = style
            font_file = self._item_text(row, 2, self.font_table)
            if font_file:
                entry["font"] = font_file
            if "style" not in entry or not entry["style"]:
                entry["style"] = sanitize_style_name(family)
            mapping[family] = entry
        return mapping

    def _item_text(self, row: int, column: int, table: QTableWidget | None = None) -> str:
        widget_table = table or self.rules_table
        item = widget_table.item(row, column)
        return item.text().strip() if item and item.text() else ""

    def _add_rule(self) -> None:
        self._insert_rule_row(MappingRule(selector="class:", layer="0"))

    def _remove_rule(self) -> None:
        self._remove_selected_rows(self.rules_table)

    def _add_material_entry(self) -> None:
        row = self.material_table.rowCount()
        self.material_table.insertRow(row)
        for column in range(5):
            self._set_table_item(self.material_table, row, column, "")

    def _remove_material_entry(self) -> None:
        self._remove_selected_rows(self.material_table)

    def _add_pattern_entry(self) -> None:
        row = self.pattern_table.rowCount()
        self.pattern_table.insertRow(row)
        for column in range(6):
            default = "N" if column == 5 else ""
            self._set_table_item(self.pattern_table, row, column, default)

    def _remove_pattern_entry(self) -> None:
        self._remove_selected_rows(self.pattern_table)

    def _add_font_entry(self) -> None:
        row = self.font_table.rowCount()
        self.font_table.insertRow(row)
        for column in range(3):
            self._set_table_item(self.font_table, row, column, "")

    def _remove_font_entry(self) -> None:
        self._remove_selected_rows(self.font_table)

    def _remove_selected_rows(self, table: QTableWidget) -> None:
        selected_rows = sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True)
        for row in selected_rows:
            table.removeRow(row)

    def _apply_mapping_changes(self, save: bool) -> List[MappingRule]:
        rules = self._collect_rules_from_table()
        materials = self._collect_material_mapping()
        patterns = self._collect_pattern_mapping()
        fonts = self._collect_font_mapping()

        if not rules:
            rules = MappingManager.default_rules()

        self.controller.mapping_manager.rules = list(rules)
        self.controller.update_mapping_config(materials, patterns, fonts)

        if save:
            self.controller.save_mapping_config()
            self.statusBar().showMessage("맵핑 설정을 저장했습니다.", 3000)

        return rules

    def _save_mapping_config(self) -> None:
        self._apply_mapping_changes(save=True)
        self._populate_material_table()
        self._populate_pattern_table()
        self._populate_font_table()

    def _reset_rules(self) -> None:
        default_rules = MappingManager.default_rules()
        self.controller.mapping_manager.rules = list(default_rules)
        self.rules_table.setRowCount(0)
        for rule in default_rules:
            self._insert_rule_row(rule)
        self._populate_material_table()
        self._populate_pattern_table()
        self._populate_font_table()

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "확인", message)
        self.statusBar().showMessage(message, 5000)
