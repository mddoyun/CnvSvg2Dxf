from __future__ import annotations

import sys

from PyQt5.QtWidgets import QApplication

from .ui.main_window import MainWindow


def create_application() -> tuple[QApplication, MainWindow]:
    """Create the Qt application and main window."""
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    return app, window


def run() -> int:
    """Entry point for running the PyQt UI."""
    app, window = create_application()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(run())

