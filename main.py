# main.py
"""Main application entry point."""

import os
import sys

from PyQt6.QtWidgets import QApplication

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from gui.program_selector_window import ProgramSelectorWindow
from app_version import APP_DISPLAY_NAME, APP_NAME, APP_VERSION
from utils.deployment_paths import ensure_runtime_directories

def main():
    ensure_runtime_directories()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setApplicationVersion(APP_VERSION)
    win = ProgramSelectorWindow()
    win.move(20, 20)
    win.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()

