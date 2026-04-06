"""
main.py
-------
Entry point for Smart Automatic File Organizer.
Sets up logging, then launches the GUI.
"""

import sys
import logging
from pathlib import Path

# ── Configure logging BEFORE importing GUI ──
LOG_FILE = Path(__file__).parent / "organizer.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

# Add QtLogHandler so the GUI log panel also receives messages
# (imported after basicConfig so the root logger is configured first)
from PyQt6.QtWidgets import QApplication
from gui import MainWindow, _QtLogHandler

_qt_handler = _QtLogHandler()
_qt_handler.setFormatter(logging.Formatter("%(levelname)s – %(message)s"))
logging.getLogger().addHandler(_qt_handler)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Smart File Organizer")
    app.setApplicationVersion("1.0.0")

    # High-DPI support (PyQt6 enables automatically, but set attribute for safety)
    try:
        from PyQt6.QtCore import Qt
        app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)
    except Exception:
        pass

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
