from __future__ import annotations

from pathlib import Path
from typing import List

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

        self.tabs.addTab(tab, "레이어 매핑")

    def _populate_default_rules(self) -> None:
        self.rules_table.setRowCount(0)
        for rule in self.controller.default_rules():
            self._insert_rule_row(rule)

    def _insert_rule_row(self, rule: MappingRule) -> None:
        row = self.rules_table.rowCount()
        self.rules_table.insertRow(row)
        for column, value in enumerate(rule.as_row()):
            item = QTableWidgetItem(value)
            self.rules_table.setItem(row, column, item)

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
        rules = self._collect_rules_from_table()

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
        if not rules:
            rules = MappingManager.default_rules()
        return rules

    def _item_text(self, row: int, column: int) -> str:
        item = self.rules_table.item(row, column)
        return item.text().strip() if item and item.text() else ""

    def _add_rule(self) -> None:
        self._insert_rule_row(MappingRule(selector="class:", layer="0"))

    def _remove_rule(self) -> None:
        selected_rows = sorted({idx.row() for idx in self.rules_table.selectedIndexes()}, reverse=True)
        for row in selected_rows:
            self.rules_table.removeRow(row)

    def _reset_rules(self) -> None:
        self._populate_default_rules()

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "확인", message)
        self.statusBar().showMessage(message, 5000)

