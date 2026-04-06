"""
gui.py
------
PyQt6-based GUI for Smart Automatic File Organizer.
Dark-theme, professional layout.
"""

import sys
import logging
import threading
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QTextEdit,
    QFileDialog, QSplitter, QGroupBox, QCheckBox, QComboBox,
    QProgressDialog, QMessageBox, QFrame, QToolButton, QSizePolicy,
    QStatusBar, QSystemTrayIcon, QMenu, QAbstractItemView, QLineEdit,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QObject, QTimer, QSize,
)
from PyQt6.QtGui import (
    QIcon, QFont, QColor, QPalette, QAction, QPixmap,
)

import folder_manager
import sorter
from watcher import WatcherManager

# ─────────────────────────────────────────────
# Log bridge (thread-safe signal → GUI)
# ─────────────────────────────────────────────

class LogBridge(QObject):
    """Emit log messages safely to the GUI thread."""
    message = pyqtSignal(str, str)   # (text, level)


_bridge = LogBridge()


class _QtLogHandler(logging.Handler):
    def emit(self, record):
        level = record.levelname.lower()
        msg   = self.format(record)
        _bridge.message.emit(msg, level)


# ─────────────────────────────────────────────
# Worker threads
# ─────────────────────────────────────────────

class SortExistingWorker(QThread):
    """Runs sorter.sort_existing_files() off the main thread."""
    progress  = pyqtSignal(int, int, dict)    # done, total, result
    finished  = pyqtSignal(int, int)          # moved_count, skipped_count

    def __init__(self, folder_entry: dict, parent=None):
        super().__init__(parent)
        self.folder_entry = folder_entry
        self.recursive    = folder_entry.get("recursive", False)

    def run(self):
        path   = Path(self.folder_entry["path"])
        moved  = 0
        skipped = 0

        def cb(done, total, res):
            nonlocal moved, skipped
            if res["status"] == "moved":
                moved += 1
            else:
                skipped += 1
            self.progress.emit(done, total, res)

        sorter.sort_existing_files(
            path,
            use_smart_rename=self.folder_entry.get("smart_rename", False),
            duplicate_action=self.folder_entry.get("duplicate_action", "rename"),
            recursive=self.recursive,
            progress_callback=cb,
        )
        self.finished.emit(moved, skipped)


# ─────────────────────────────────────────────
# Folder list item widget
# ─────────────────────────────────────────────

class FolderItemWidget(QWidget):
    """Custom row widget shown inside the folder list."""
    toggled       = pyqtSignal(str, bool)   # path, new_enabled
    removed       = pyqtSignal(str)         # path
    sort_existing = pyqtSignal(str)         # path
    settings_changed = pyqtSignal(str, str, str, bool)  # path, smart_rename, dup_action, recursive

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.entry = entry
        path       = Path(entry["path"])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # ── Status dot ────────────────────────
        self.status_dot = QLabel("●")
        self.status_dot.setFixedWidth(18)
        self._update_dot(entry["enabled"])
        layout.addWidget(self.status_dot)

        # ── Path label ────────────────────────
        self.path_label = QLabel(str(path))
        self.path_label.setToolTip(str(path))
        self.path_label.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Preferred)
        font = self.path_label.font()
        font.setPointSize(9)
        self.path_label.setFont(font)
        layout.addWidget(self.path_label)

        # ── Smart rename checkbox ──────────────
        self.cb_smart = QCheckBox("Smart Rename")
        self.cb_smart.setChecked(entry.get("smart_rename", False))
        self.cb_smart.setToolTip("Append timestamp to filename when moved")
        self.cb_smart.stateChanged.connect(self._on_settings_change)
        layout.addWidget(self.cb_smart)

        # ── Duplicate action ───────────────────
        self.dup_combo = QComboBox()
        self.dup_combo.addItems(["rename", "skip", "overwrite"])
        idx = self.dup_combo.findText(entry.get("duplicate_action", "rename"))
        self.dup_combo.setCurrentIndex(max(idx, 0))
        self.dup_combo.setToolTip("Duplicate file action")
        self.dup_combo.setFixedWidth(100)
        self.dup_combo.currentTextChanged.connect(self._on_settings_change)
        layout.addWidget(self.dup_combo)

        # ── Recursive checkbox ─────────────────
        self.cb_recursive = QCheckBox("Recursive")
        self.cb_recursive.setChecked(entry.get("recursive", False))
        self.cb_recursive.setToolTip("Monitor and sort files inside sub-folders")
        self.cb_recursive.stateChanged.connect(self._on_settings_change)
        layout.addWidget(self.cb_recursive)

        # ── Sort now button ────────────────────
        btn_sort = QToolButton()
        btn_sort.setText("Sort Now")
        btn_sort.setToolTip("Sort all existing files in this folder immediately")
        btn_sort.clicked.connect(lambda: self.sort_existing.emit(self.entry["path"]))
        layout.addWidget(btn_sort)

        # ── Toggle enable ─────────────────────
        self.btn_toggle = QToolButton()
        self._update_toggle_btn(entry["enabled"])
        self.btn_toggle.clicked.connect(self._on_toggle)
        layout.addWidget(self.btn_toggle)

        # ── Remove ────────────────────────────
        btn_remove = QToolButton()
        btn_remove.setText("✕")
        btn_remove.setToolTip("Remove from watch list")
        btn_remove.setStyleSheet("color: #e05252;")
        btn_remove.clicked.connect(lambda: self.removed.emit(self.entry["path"]))
        layout.addWidget(btn_remove)

    # ── Helpers ───────────────────────────────

    def _update_dot(self, enabled: bool):
        color = "#4ade80" if enabled else "#6b7280"
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 14px;")

    def _update_toggle_btn(self, enabled: bool):
        self.btn_toggle.setText("⏸ Pause" if enabled else "▶ Resume")
        self.btn_toggle.setToolTip("Pause/resume sorting for this folder")

    def _on_toggle(self):
        new_state = not self.entry["enabled"]
        self.entry["enabled"] = new_state
        self._update_dot(new_state)
        self._update_toggle_btn(new_state)
        self.toggled.emit(self.entry["path"], new_state)

    def _on_settings_change(self):
        self.entry["smart_rename"]    = self.cb_smart.isChecked()
        self.entry["duplicate_action"] = self.dup_combo.currentText()
        self.entry["recursive"]       = self.cb_recursive.isChecked()
        self.settings_changed.emit(
            self.entry["path"],
            str(self.entry["smart_rename"]),
            self.entry["duplicate_action"],
            self.entry["recursive"]
        )

    def refresh(self, entry: dict):
        """Refresh widget state from a new entry dict."""
        self.entry = entry
        self._update_dot(entry["enabled"])
        self._update_toggle_btn(entry["enabled"])
        self.cb_smart.blockSignals(True)
        self.cb_smart.setChecked(entry.get("smart_rename", False))
        self.cb_smart.blockSignals(False)
        idx = self.dup_combo.findText(entry.get("duplicate_action", "rename"))
        self.dup_combo.blockSignals(True)
        self.dup_combo.setCurrentIndex(max(idx, 0))
        self.dup_combo.blockSignals(False)
        self.cb_recursive.blockSignals(True)
        self.cb_recursive.setChecked(entry.get("recursive", False))
        self.cb_recursive.blockSignals(False)


# ─────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────

class MainWindow(QMainWindow):
    _log_signal = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart File Organizer")
        self.setMinimumSize(900, 620)
        self._watcher = WatcherManager(log_callback=self._emit_log)
        self._worker  = None            # SortExistingWorker
        self._item_widgets: dict[str, FolderItemWidget] = {}

        # Connect log bridge
        _bridge.message.connect(self._append_log)

        self._build_ui()
        self._apply_dark_theme()
        self._refresh_folder_list()

        # Auto-start if configured
        g = folder_manager.load_global_settings()
        if g.get("start_on_launch", False):
            self._start_monitoring()

    # ── UI construction ───────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Top bar ───────────────────────────
        root.addWidget(self._build_topbar())

        # ── Splitter (folders | log) ──────────
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Left/Top panel container
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        left_layout.addWidget(self._build_ai_panel())
        left_layout.addWidget(self._build_folder_panel())
        
        splitter.addWidget(left_container)
        splitter.addWidget(self._build_log_panel())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

        # ── Status bar ────────────────────────
        self.statusBar().showMessage("Ready")

    def _build_topbar(self) -> QWidget:
        bar   = QWidget()
        hbox  = QHBoxLayout(bar)
        hbox.setContentsMargins(0, 0, 0, 0)

        # Logo / title
        title = QLabel("🗂 Smart File Organizer")
        f = title.font()
        f.setPointSize(14)
        f.setBold(True)
        title.setFont(f)
        hbox.addWidget(title)

        hbox.addStretch()

        # Status badge
        self.lbl_status = QLabel("● Idle")
        self.lbl_status.setStyleSheet("color: #6b7280; font-weight: bold;")
        hbox.addWidget(self.lbl_status)

        hbox.addSpacing(16)

        # Start / Stop
        self.btn_start = QPushButton("▶  Start Monitoring")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.setFixedHeight(36)
        self.btn_start.clicked.connect(self._toggle_monitoring)
        hbox.addWidget(self.btn_start)

        # Undo
        btn_undo = QPushButton("↩  Undo Last Move")
        btn_undo.setFixedHeight(36)
        btn_undo.setToolTip("Reverse the most recently organised file")
        btn_undo.clicked.connect(self._undo_last)
        hbox.addWidget(btn_undo)

        return bar

        return box

    def _build_ai_panel(self) -> QGroupBox:
        box = QGroupBox("🤖 AI Music Analysis (Gemini)")
        box.setFixedHeight(100)
        layout = QHBoxLayout(box)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(15)

        # Enable toggle
        self.cb_ai_music = QCheckBox("Enable AI Classification")
        self.cb_ai_music.setToolTip("Use Gemini AI to categorize music into moods (Party, Romantic, etc.)")
        layout.addWidget(self.cb_ai_music)

        # API Key input
        layout.addWidget(QLabel("API Key:"))
        self.txt_api_key = QLineEdit()
        self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_api_key.setPlaceholderText("Paste your Gemini API key here...")
        self.txt_api_key.setToolTip("Get a free key from Google AI Studio")
        layout.addWidget(self.txt_api_key)

        # Save button
        btn_save_ai = QPushButton("💾 Save")
        btn_save_ai.setFixedWidth(80)
        btn_save_ai.clicked.connect(self._save_ai_settings)
        layout.addWidget(btn_save_ai)

        # Load current settings
        gs = folder_manager.load_global_settings()
        self.cb_ai_music.setChecked(gs.get("music_ai_enabled", False))
        self.txt_api_key.setText(gs.get("gemini_api_key", ""))

        return box

    def _save_ai_settings(self):
        gs = folder_manager.load_global_settings()
        gs["music_ai_enabled"] = self.cb_ai_music.isChecked()
        gs["gemini_api_key"]   = self.txt_api_key.text().strip()
        
        if folder_manager.save_global_settings(gs):
            self._emit_log("AI Settings saved successfully", "info")
            self.statusBar().showMessage("AI Settings updated", 3000)
        else:
            self._emit_log("Failed to save AI Settings", "error")

    def _build_folder_panel(self) -> QGroupBox:
        box  = QGroupBox("Watched Folders")
        vbox = QVBoxLayout(box)

        # Action buttons row
        hbox = QHBoxLayout()
        btn_add = QPushButton("➕  Add Folder")
        btn_add.clicked.connect(self._add_folder)
        hbox.addWidget(btn_add)
        hbox.addStretch()
        vbox.addLayout(hbox)

        # Folder list
        self.folder_list = QListWidget()
        self.folder_list.setSpacing(2)
        self.folder_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.folder_list.setAlternatingRowColors(True)
        vbox.addWidget(self.folder_list)

        return box

    def _build_log_panel(self) -> QGroupBox:
        box  = QGroupBox("Activity Log")
        vbox = QVBoxLayout(box)

        # Controls
        hrow = QHBoxLayout()
        btn_clear = QPushButton("🗑  Clear Log")
        btn_clear.setFixedHeight(28)
        btn_clear.clicked.connect(self._clear_log)
        hrow.addStretch()
        hrow.addWidget(btn_clear)
        vbox.addLayout(hrow)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas", 9))
        self.log_box.setObjectName("log_box")
        vbox.addWidget(self.log_box)

        return box

    # ── Folder list management ─────────────────

    def _refresh_folder_list(self):
        self.folder_list.clear()
        self._item_widgets.clear()

        folders = folder_manager.load_folders()
        for entry in folders:
            self._add_list_row(entry)

    def _add_list_row(self, entry: dict):
        path_str = entry["path"]
        widget   = FolderItemWidget(entry)

        widget.toggled.connect(self._on_toggle)
        widget.removed.connect(self._on_remove)
        widget.sort_existing.connect(self._on_sort_existing)
        widget.settings_changed.connect(self._on_settings_changed)

        item = QListWidgetItem(self.folder_list)
        item.setSizeHint(widget.sizeHint())
        self.folder_list.addItem(item)
        self.folder_list.setItemWidget(item, widget)

        self._item_widgets[path_str] = widget

    # ── Button handlers ───────────────────────

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select a folder to watch", "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not path:
            return
        ok, msg = folder_manager.add_folder(path)
        self._emit_log(msg, "info" if ok else "error")
        if ok:
            entries = folder_manager.load_folders()
            entry   = next((e for e in entries if e["path"] == str(Path(path).resolve())), None)
            if entry:
                self._add_list_row(entry)
            if self._watcher.is_running:
                self._watcher.reload()

    def _on_remove(self, path: str):
        reply = QMessageBox.question(
            self, "Remove Folder",
            f"Remove from watch list?\n{path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        ok, msg = folder_manager.remove_folder(path)
        self._emit_log(msg, "info" if ok else "error")
        if ok:
            self._refresh_folder_list()
            if self._watcher.is_running:
                self._watcher.reload()

    def _on_toggle(self, path: str, enabled: bool):
        ok, msg = folder_manager.toggle_folder(path, enabled)
        self._emit_log(msg, "info" if ok else "error")
        if ok and self._watcher.is_running:
            self._watcher.reload()

    def _on_settings_changed(self, path: str, smart_rename_str: str, dup_action: str, recursive: bool):
        smart = smart_rename_str.lower() == "true"
        folder_manager.update_folder_settings(path, smart_rename=smart, duplicate_action=dup_action)
        # Update recursive flag as well (need to update folder_manager too)
        folders = folder_manager.load_folders()
        p = Path(path).resolve()
        for f in folders:
            if Path(f["path"]).resolve() == p:
                f["recursive"] = recursive
                folder_manager.save_folders(folders)
                break
        
        if self._watcher.is_running:
            self._watcher.reload()

    def _on_sort_existing(self, path: str):
        folders = folder_manager.load_folders()
        entry   = next((e for e in folders if e["path"] == path), None)
        if not entry:
            return

        # Identify files for progress count
        if entry.get("recursive", False):
            files = [f for f in Path(path).rglob("*") if f.is_file()]
        else:
            files = [f for f in Path(path).iterdir() if f.is_file()]

        if not files:
            QMessageBox.information(self, "Nothing to sort", "No files found in this folder hierarchy.")
            return

        # Run in background thread
        self._worker = SortExistingWorker(entry)
        self._worker.progress.connect(self._on_sort_progress)
        self._worker.finished.connect(self._on_sort_finished)

        self._progress_dlg = QProgressDialog(
            f"Sorting {len(files)} files…", "Cancel", 0, len(files), self
        )
        self._progress_dlg.setWindowTitle("Sorting…")
        self._progress_dlg.setMinimumDuration(0)
        self._progress_dlg.show()
        self._worker.start()

    def _on_sort_progress(self, done: int, total: int, res: dict):
        if hasattr(self, "_progress_dlg"):
            self._progress_dlg.setValue(done)
        self._emit_log(res["message"], "info" if res["status"] == "moved" else "info")

    def _on_sort_finished(self, moved: int, skipped: int):
        if hasattr(self, "_progress_dlg"):
            self._progress_dlg.close()
        self._emit_log(f"✅ Sort complete: {moved} moved, {skipped} skipped", "info")
        self.statusBar().showMessage(f"Sort complete: {moved} moved, {skipped} skipped", 5000)

    def _undo_last(self):
        result = sorter.undo_last_move()
        level  = "info" if result["status"] == "ok" else "warning"
        self._emit_log(result["message"], level)
        if result["status"] == "ok":
            self.statusBar().showMessage(result["message"], 4000)

    def _toggle_monitoring(self):
        if self._watcher.is_running:
            self._stop_monitoring()
        else:
            self._start_monitoring()

    def _start_monitoring(self):
        self._watcher.start()
        self.btn_start.setText("⏹  Stop Monitoring")
        self.btn_start.setObjectName("btn_stop")
        self.btn_start.setStyle(self.btn_start.style())   # force style refresh
        self.lbl_status.setText("● Monitoring")
        self.lbl_status.setStyleSheet("color: #4ade80; font-weight: bold;")
        self.statusBar().showMessage("Monitoring started")

    def _stop_monitoring(self):
        self._watcher.stop()
        self.btn_start.setText("▶  Start Monitoring")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.setStyle(self.btn_start.style())
        self.lbl_status.setText("● Idle")
        self.lbl_status.setStyleSheet("color: #6b7280; font-weight: bold;")
        self.statusBar().showMessage("Monitoring stopped")

    def _clear_log(self):
        self.log_box.clear()

    # ── Logging ───────────────────────────────

    def _emit_log(self, msg: str, level: str = "info"):
        """Thread-safe log emit (may be called from watcher thread)."""
        _bridge.message.emit(msg, level)

    def _append_log(self, msg: str, level: str):
        ts = datetime.now().strftime("%H:%M:%S")
        colors = {
            "info":    "#c9d1d9",
            "warning": "#f0b429",
            "error":   "#e05252",
            "debug":   "#6b7280",
        }
        color = colors.get(level, "#c9d1d9")
        html  = f'<span style="color:#6b7280">[{ts}]</span> <span style="color:{color}">{msg}</span>'
        self.log_box.append(html)
        # Auto-scroll
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── Close event ───────────────────────────

    def closeEvent(self, event):
        if self._watcher.is_running:
            self._watcher.stop()
        event.accept()

    # ── Dark theme ────────────────────────────

    def _apply_dark_theme(self):
        self.setStyleSheet("""
/* ─── Global ─────────────────────────── */
* {
    font-family: "Segoe UI", sans-serif;
    font-size: 10pt;
}
QMainWindow, QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
}

/* ─── Group boxes ────────────────────── */
QGroupBox {
    border: 1px solid #21262d;
    border-radius: 8px;
    margin-top: 8px;
    padding-top: 12px;
    background-color: #161b22;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    color: #8b949e;
    font-weight: bold;
}

/* ─── Buttons ────────────────────────── */
QPushButton {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover {
    background-color: #30363d;
    border-color: #58a6ff;
}
QPushButton:pressed {
    background-color: #161b22;
}
QPushButton#btn_start {
    background-color: #238636;
    color: #ffffff;
    border-color: #2ea043;
    font-weight: bold;
}
QPushButton#btn_start:hover {
    background-color: #2ea043;
}
QPushButton#btn_stop {
    background-color: #b62324;
    color: #ffffff;
    border-color: #da3633;
    font-weight: bold;
}
QPushButton#btn_stop:hover {
    background-color: #da3633;
}

/* ─── Tool buttons ───────────────────── */
QToolButton {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 5px;
    padding: 4px 10px;
}
QToolButton:hover {
    background-color: #30363d;
    border-color: #58a6ff;
}

/* ─── List widget ────────────────────── */
QListWidget {
    background-color: #0d1117;
    border: 1px solid #21262d;
    border-radius: 6px;
    alternate-background-color: #161b22;
}
QListWidget::item:selected {
    background-color: #1f6feb22;
    border: none;
}

/* ─── Log box ────────────────────────── */
QTextEdit#log_box {
    background-color: #010409;
    border: 1px solid #21262d;
    border-radius: 6px;
}

/* ─── Combo / CheckBox ───────────────── */
QComboBox {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 5px;
    padding: 2px 6px;
    color: #c9d1d9;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #161b22;
    border: 1px solid #30363d;
    selection-background-color: #1f6feb;
}
QCheckBox { spacing: 5px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #30363d;
    border-radius: 3px;
    background-color: #21262d;
}
QCheckBox::indicator:checked {
    background-color: #1f6feb;
    border-color: #58a6ff;
}

/* ─── Splitter ───────────────────────── */
QSplitter::handle { background-color: #21262d; height: 2px; }

/* ─── Status bar ─────────────────────── */
QStatusBar { background-color: #161b22; border-top: 1px solid #21262d; }

/* ─── Scroll bars ────────────────────── */
QScrollBar:vertical {
    background: #0d1117; width: 8px; border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #30363d; border-radius: 4px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #58a6ff; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)
