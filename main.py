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

def main():
    app = QApplication(sys.argv)
    win = ProgramSelectorWindow()
    win.move(20, 20)
    win.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()

