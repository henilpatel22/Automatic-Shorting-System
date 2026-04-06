"""
folder_manager.py
-----------------
Manages the list of user-selected watch folders.
Persists settings to config.json.

Schema (config.json):
{
    "folders": [
        {
            "path":    "C:/Users/You/Downloads",
            "enabled": true,
            "smart_rename":      false,
            "duplicate_action":  "rename"   // "rename" | "skip" | "overwrite"
        },
        ...
    ],
    "global_settings": {
        "start_on_launch": false,
        "log_level": "INFO"
    }
}
"""

import json
import logging
from pathlib import Path
from typing import Optional

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULT_FOLDER_ENTRY = {
    "path": "",
    "enabled": True,
    "smart_rename": False,
    "duplicate_action": "rename",   # rename | skip | overwrite
    "recursive": False,
}

DEFAULT_GLOBAL = {
    "start_on_launch": False,
    "log_level": "INFO",
    "gemini_api_key": "",
    "music_ai_enabled": False,
}


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _load_raw() -> dict:
    """Load the raw config dict from disk, returning defaults on failure."""
    if not CONFIG_FILE.exists():
        return {"folders": [], "global_settings": DEFAULT_GLOBAL.copy()}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "folders" not in data:
            data["folders"] = []
        if "global_settings" not in data:
            data["global_settings"] = DEFAULT_GLOBAL.copy()
        return data
    except (json.JSONDecodeError, OSError) as e:
        logging.error(f"[CONFIG] Failed to load config: {e}")
        return {"folders": [], "global_settings": DEFAULT_GLOBAL.copy()}


def _save_raw(data: dict) -> bool:
    """Write the config dict to disk. Returns True on success."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except OSError as e:
        logging.error(f"[CONFIG] Failed to save config: {e}")
        return False


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def load_folders() -> list[dict]:
    """
    Return list of folder-entry dicts from config.json.
    Each dict is guaranteed to have all DEFAULT_FOLDER_ENTRY keys.
    """
    raw = _load_raw()
    folders = []
    for entry in raw.get("folders", []):
        merged = DEFAULT_FOLDER_ENTRY.copy()
        merged.update(entry)
        folders.append(merged)
    return folders


def save_folders(folders: list[dict]) -> bool:
    """Persist the given list of folder entries to config.json."""
    raw = _load_raw()
    raw["folders"] = folders
    return _save_raw(raw)


def add_folder(
    path: str,
    enabled: bool = True,
    smart_rename: bool = False,
    duplicate_action: str = "rename",
) -> tuple[bool, str]:
    """
    Add a new folder to the watch list.

    Returns (success: bool, message: str).
    """
    p = Path(path).resolve()
    if not p.exists():
        return False, f"Path does not exist: {path}"
    if not p.is_dir():
        return False, f"Not a directory: {path}"

    folders = load_folders()
    # Prevent duplicates and NESTED watches
    for f in folders:
        existing = Path(f["path"]).resolve()
        
        # Check if new path is a subfolder of an existing path
        try:
            p.relative_to(existing)
            return False, f"Folder is already covered by a parent watch: {existing.name}"
        except ValueError:
            pass
            
        # Check if existing path is a subfolder of the NEW path
        try:
            existing.relative_to(p)
            return False, f"New path contains an already watched subfolder: {existing.name}"
        except ValueError:
            pass

    new_entry = {
        "path": str(p),
        "enabled": enabled,
        "smart_rename": smart_rename,
        "duplicate_action": duplicate_action,
    }
    folders.append(new_entry)
    ok = save_folders(folders)
    if ok:
        logging.info(f"[FOLDER] Added: {p}")
        return True, f"Added: {p}"
    return False, "Failed to save config"


def remove_folder(path: str) -> tuple[bool, str]:
    """Remove a folder from the watch list by path string."""
    p = Path(path).resolve()
    folders = load_folders()
    original_len = len(folders)
    folders = [f for f in folders if Path(f["path"]).resolve() != p]
    if len(folders) == original_len:
        return False, f"Folder not found: {path}"
    ok = save_folders(folders)
    if ok:
        logging.info(f"[FOLDER] Removed: {p}")
        return True, f"Removed: {p}"
    return False, "Failed to save config"


def toggle_folder(path: str, enabled: Optional[bool] = None) -> tuple[bool, str]:
    """
    Enable or disable sorting for a specific folder.
    If *enabled* is None, the current state is flipped.
    """
    p = Path(path).resolve()
    folders = load_folders()
    for f in folders:
        if Path(f["path"]).resolve() == p:
            new_state = (not f["enabled"]) if enabled is None else enabled
            f["enabled"] = new_state
            save_folders(folders)
            state_str = "enabled" if new_state else "disabled"
            logging.info(f"[FOLDER] {state_str}: {p}")
            return True, f"Folder {state_str}: {p.name}"
    return False, f"Folder not found: {path}"


def update_folder_settings(
    path: str,
    smart_rename: Optional[bool] = None,
    duplicate_action: Optional[str] = None,
) -> tuple[bool, str]:
    """Update per-folder settings (smart_rename, duplicate_action)."""
    p = Path(path).resolve()
    folders = load_folders()
    for f in folders:
        if Path(f["path"]).resolve() == p:
            if smart_rename is not None:
                f["smart_rename"] = smart_rename
            if duplicate_action is not None:
                f["duplicate_action"] = duplicate_action
            save_folders(folders)
            return True, f"Settings updated for: {p.name}"
    return False, f"Folder not found: {path}"


def get_enabled_folders() -> list[dict]:
    """Return only folders with enabled=True."""
    return [f for f in load_folders() if f.get("enabled", True)]


def load_global_settings() -> dict:
    """Return the global_settings dict from config."""
    raw = _load_raw()
    settings = DEFAULT_GLOBAL.copy()
    settings.update(raw.get("global_settings", {}))
    return settings


def save_global_settings(settings: dict) -> bool:
    """Persist global settings to config."""
    raw = _load_raw()
    raw["global_settings"] = settings
    return _save_raw(raw)
