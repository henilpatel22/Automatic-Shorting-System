"""
watcher.py
----------
Real-time folder monitoring via watchdog.
Bridges the watchdog events → sorter.move_file().
"""

import logging
import threading
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

import sorter
from folder_manager import load_folders


# ─────────────────────────────────────────────
# Event handler
# ─────────────────────────────────────────────

class FolderEventHandler(FileSystemEventHandler):
    """Handles file-system events for a single watched folder."""

    def __init__(
        self,
        watch_path: Path,
        smart_rename: bool,
        duplicate_action: str,
        recursive: bool = False,
        log_callback=None,
    ):
        super().__init__()
        self.watch_path = watch_path
        self.smart_rename = smart_rename
        self.duplicate_action = duplicate_action
        self.recursive = recursive
        self.log_callback = log_callback  # callable(msg: str, level: str)

    def _emit_log(self, msg: str, level: str = "info"):
        logging.log(getattr(logging, level.upper(), logging.INFO), msg)
        if self.log_callback:
            self.log_callback(msg, level)

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return

        src = Path(event.src_path)

        # Small delay – let the OS finish writing the file
        time.sleep(0.8)

        # Skip files already inside an organised subfolder IF not recursive
        if not self.recursive and src.parent != self.watch_path:
            return

        result = sorter.move_file(
            src,
            self.watch_path,
            use_smart_rename=self.smart_rename,
            duplicate_action=self.duplicate_action,
        )

        status = result["status"]
        msg    = result["message"]

        if status == "moved":
            self._emit_log(f"✅ {msg}", "info")
        elif status == "skipped":
            self._emit_log(f"⏭ {msg}", "info")
        else:
            self._emit_log(f"❌ {msg}", "error")


# ─────────────────────────────────────────────
# Watcher manager (singleton-style)
# ─────────────────────────────────────────────

class WatcherManager:
    """
    Manages a pool of watchdog observers – one per active folder.
    Thread-safe: uses an internal lock for start/stop/reload operations.
    """

    def __init__(self, log_callback=None):
        self._lock     = threading.Lock()
        self._observer = None          # single Observer for all watches
        self._watches  = {}            # path_str → watch handle
        self._running  = False
        self.log_callback = log_callback

    # ── Public API ────────────────────────────

    def start(self) -> bool:
        """Start the watcher observer.  Returns True if started fresh."""
        with self._lock:
            if self._running:
                return False
            self._observer = Observer()
            self._observer.start()
            self._running = True
            self._reload_watches()
            self._log("🟢 Monitoring started", "info")
            return True

    def stop(self) -> bool:
        """Stop the watcher observer.  Returns True if stopped."""
        with self._lock:
            if not self._running:
                return False
            self._observer.stop()
            self._observer.join()
            self._observer = None
            self._watches  = {}
            self._running  = False
            self._log("🔴 Monitoring stopped", "info")
            return True

    @property
    def is_running(self) -> bool:
        return self._running

    def reload(self):
        """Re-read config and adjust active watches (add/remove as needed)."""
        with self._lock:
            if not self._running:
                return
            self._reload_watches()

    # ── Private ───────────────────────────────

    def _reload_watches(self):
        """Sync observer watches with the current enabled-folder list."""
        from folder_manager import load_folders
        enabled = [f for f in load_folders() if f.get("enabled", True)]
        enabled_paths = {str(Path(f["path"]).resolve()) for f in enabled}

        # Remove watches for folders no longer in the list
        removed = set(self._watches) - enabled_paths
        for path_str in removed:
            try:
                self._observer.unschedule(self._watches[path_str])
            except Exception:
                pass
            del self._watches[path_str]
            self._log(f"➖ Stopped watching: {path_str}", "info")

        # Add watches for new folders
        for entry in enabled:
            path_str = str(Path(entry["path"]).resolve())
            if path_str in self._watches:
                continue  # already watching

            p = Path(path_str)
            if not p.exists():
                self._log(f"⚠ Folder not found, skipping: {p}", "warning")
                continue

            handler = FolderEventHandler(
                watch_path=p,
                smart_rename=entry.get("smart_rename", False),
                duplicate_action=entry.get("duplicate_action", "rename"),
                recursive=entry.get("recursive", False),
                log_callback=self.log_callback,
            )
            try:
                watch = self._observer.schedule(
                    handler, str(p), recursive=entry.get("recursive", False)
                )
                self._watches[path_str] = watch
                self._log(f"➕ Watching: {p} (recursive={entry.get('recursive', False)})", "info")
            except Exception as e:
                self._log(f"❌ Cannot watch {p}: {e}", "error")

    def _log(self, msg: str, level: str = "info"):
        logging.log(getattr(logging, level.upper(), logging.INFO), msg)
        if self.log_callback:
            self.log_callback(msg, level)
