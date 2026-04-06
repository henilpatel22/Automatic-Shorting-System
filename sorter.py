"""
sorter.py
---------
Core file sorting engine.
Handles: extension-based classification, subfolder creation,
         duplicate detection, smart rename, and undo stack.
"""

import os
import re
import shutil
import hashlib
import logging
from datetime import datetime
from pathlib import Path

# AI/Metadata imports
import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
import google.generativeai as genai

# ─────────────────────────────────────────────
# Extension → Category mapping
# ─────────────────────────────────────────────
CATEGORY_MAP: dict[str, list[str]] = {
    "Images":     [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg",
                   ".webp", ".ico", ".tiff", ".tif", ".heic", ".raw"],
    "Videos":     [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
                   ".webm", ".m4v", ".3gp", ".mpeg"],
    "Music":      [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma",
                   ".m4a", ".opus", ".aiff"],
    "Documents":  [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt",
                   ".pptx", ".odt", ".ods", ".odp", ".txt", ".rtf",
                   ".csv", ".md", ".epub", ".mobi"],
    "Archives":   [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2",
                   ".xz", ".iso", ".dmg", ".cab"],
    "Code":       [".py", ".js", ".ts", ".html", ".css", ".java",
                   ".c", ".cpp", ".cs", ".php", ".rb", ".go", ".rs",
                   ".swift", ".kt", ".sh", ".bat", ".ps1", ".sql",
                   ".json", ".xml", ".yaml", ".yml", ".toml", ".ini",
                   ".cfg", ".env"],
    "Executables":[".exe", ".msi", ".apk", ".deb", ".rpm", ".appx"],
    "Fonts":      [".ttf", ".otf", ".woff", ".woff2", ".eot"],
    "3D":         [".obj", ".fbx", ".stl", ".blend", ".dae", ".3ds"],
}

# Reverse lookup: extension → category name
EXT_TO_CATEGORY: dict[str, str] = {
    ext: cat
    for cat, exts in CATEGORY_MAP.items()
    for ext in exts
}

# Categories that are organised further by Year → Month
# (only created when a file actually lands there → no empty folders)
DATE_SORTED_CATEGORIES: frozenset[str] = frozenset({
    "Documents", "Images", "Videos",
})

# Files that signify a project root or vital config.
# These will NEVER be moved, even if they are in the root of a watched folder.
PROJECT_FILE_NAMES: frozenset[str] = frozenset({
    ".gitignore", ".gitattributes", ".gitmodules", ".env", "LICENSE",
    "README.md", "README.txt", "package.json", "package-lock.json",
    "requirements.txt", "Gemfile", "Makefile", "Dockerfile",
    "docker-compose.yml", "go.mod", "go.sum", "pom.xml", "build.gradle",
    "CMakeLists.txt", "Pipfile", "pyproject.toml", ".editorconfig"
})

PROJECT_EXTENSIONS: frozenset[str] = frozenset({
    ".git", ".svn", ".vscode", ".idea", ".tmp", ".crdownload"
})

# ─────────────────────────────────────────────
# AI Music Classification
# ─────────────────────────────────────────────

# Maps common genres to moods (fallback if AI is disabled or key is missing)
GENRE_TO_MOOD: dict[str, str] = {
    # Party
    "pop": "Party", "dance": "Party", "hip hop": "Party", "rap": "Party", "edm": "Party", 
    "electronic": "Party", "house": "Party", "techno": "Party",
    # Romantic/Emotional
    "love": "Romantic", "soul": "Romantic", "rnb": "Romantic", "r&b": "Romantic", 
    "ballad": "Romantic", "blues": "Romantic",
    # Chill/Relaxing
    "lofi": "Chill", "jazz": "Chill", "ambient": "Chill", "acoustic": "Chill", 
    "folk": "Chill", "chillout": "Chill", "indie": "Chill",
    # Energetic/Rock
    "rock": "Energetic", "metal": "Energetic", "punk": "Energetic", "alt": "Energetic",
    # Study/Focus
    "classical": "Study", "instrumental": "Study", "piano": "Study", "synthwave": "Study",
}

class MusicAnalyzer:
    """Extracts metadata and determines the mood of a song."""

    @staticmethod
    def get_metadata(path: Path) -> dict:
        """Read ID3 tags or MP4/FLAC metadata."""
        data = {"title": path.stem, "artist": "Unknown", "genre": "Unknown"}
        try:
            if path.suffix.lower() == ".mp3":
                audio = EasyID3(path)
                data["title"]  = audio.get("title", [path.stem])[0]
                data["artist"] = audio.get("artist", ["Unknown"])[0]
                data["genre"]  = audio.get("genre", ["Unknown"])[0]
            elif path.suffix.lower() in [".m4a", ".mp4"]:
                audio = MP4(path)
                data["title"]  = audio.get("\xa9nam", [path.stem])[0]
                data["artist"] = audio.get("\xa9ART", ["Unknown"])[0]
                data["genre"]  = audio.get("\xa9gen", ["Unknown"])[0]
            elif path.suffix.lower() == ".flac":
                audio = FLAC(path)
                data["title"]  = audio.get("title", [path.stem])[0]
                data["artist"] = audio.get("artist", ["Unknown"])[0]
                data["genre"]  = audio.get("genre", ["Unknown"])[0]
        except Exception:
            pass
        return data

    @staticmethod
    def determine_mood(metadata: dict, api_key: str = "", use_ai: bool = False) -> str:
        """Classify mood using AI or local genre mapping."""
        title = metadata["title"]
        artist = metadata["artist"]
        genre = metadata["genre"].lower()

        # Step 1: Attempt AI Classification (Gemini)
        if use_ai and api_key and len(api_key) > 5:
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                prompt = (
                    f"Categorize this song mood into ONE word from this list: "
                    f"[Party, Romantic, Chill, Energetic, Sad, Study].\n"
                    f"Song Title: {title}\n"
                    f"Artist: {artist}\n"
                    f"Genre: {genre}\n"
                    f"Folder Context: {metadata.get('folder_hint', 'None')}\n"
                    f"Return ONLY the word."
                )
                response = model.generate_content(prompt)
                # Clean markdown and common junk
                mood = response.text.strip()
                mood = re.sub(r"[*#_`]", "", mood).capitalize()
                
                valid_moods = ["Party", "Romantic", "Chill", "Energetic", "Sad", "Study"]
                for m in valid_moods:
                    if m.lower() in mood.lower():
                        return m
            except Exception as e:
                logging.error(f"[AI] Mood error: {e}")

        # Step 2: Fallback to local Genre mapping
        for g, mood in GENRE_TO_MOOD.items():
            if g in genre:
                return mood

        # Step 3: Default
        return "Others"

# ─────────────────────────────────────────────
# Undo stack  (in-memory, per session)
# ─────────────────────────────────────────────
_undo_stack: list[dict] = []   # [{"src": str, "dst": str}, ...]
MAX_UNDO = 50                  # keep last N moves


def get_category(file_path: Path) -> str:
    """Return the category name for a given file, or 'Others'."""
    ext = file_path.suffix.lower()
    return EXT_TO_CATEGORY.get(ext, "Others")


def _file_md5(path: Path, chunk_size: int = 65536) -> str:
    """Compute MD5 hash of a file for duplicate detection."""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
    except (PermissionError, OSError):
        return ""
    return h.hexdigest()


def _smart_rename(file_path: Path) -> Path:
    """
    Append a timestamp to the filename stem.
    E.g. report.pdf → report_20240415_143022.pdf
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_name = f"{file_path.stem}_{ts}{file_path.suffix}"
    return file_path.with_name(new_name)


def _resolve_destination(dst_path: Path, src_path: Path,
                         use_smart_rename: bool,
                         duplicate_action: str) -> Path | None:
    """
    Resolve the final destination path, handling duplicates.

    duplicate_action:
        "skip"     – leave the source file untouched
        "overwrite"– replace the destination file
        "rename"   – add a numeric/timestamp suffix
    Returns None if the file should be skipped.
    """
    if not dst_path.exists():
        return dst_path

    # Check if they're the same file by content
    if _file_md5(src_path) == _file_md5(dst_path):
        logging.info(f"[DUPLICATE] Identical file skipped: {src_path.name}")
        return None  # always skip true duplicates

    if duplicate_action == "skip":
        logging.info(f"[DUPLICATE] Skipped (diff content): {src_path.name}")
        return None

    if duplicate_action == "overwrite":
        return dst_path

    # rename: find a free numeric suffix
    stem, suffix = dst_path.stem, dst_path.suffix
    parent = dst_path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def move_file(
    src: Path,
    watch_folder: Path,
    use_smart_rename: bool = False,
    duplicate_action: str = "rename",
) -> dict:
    """
    Move *src* into the appropriate subfolder inside *watch_folder*.

    Returns a result dict:
        {
          "status":   "moved" | "skipped" | "error",
          "src":      str,
          "dst":      str | None,
          "category": str,
          "message":  str,
        }
    """
    result = {
        "src": str(src),
        "dst": None,
        "category": "",
        "message": "",
    }

    try:
        if not src.is_file():
            result["status"] = "skipped"
            result["message"] = "Not a regular file"
            return result

        # ── Circular Move Protection ──────────────────────────────
        # If the file is already inside a category folder (or subfolder of one),
        # don't move it again. This prevents recursive loops.
        category_names = set(CATEGORY_MAP.keys()) | {"Others", "Unsorted"}
        parts = src.relative_to(watch_folder).parts
        if any(p in category_names for p in parts[:-1]):
            result["status"] = "skipped"
            result["message"] = f"Already organized (in {parts[0]})"
            return result

        # ── Project File Protection ──────────────────────────────────
        # Skip files that look like project configuration or markers
        if src.name.lower() in PROJECT_FILE_NAMES or src.suffix.lower() in PROJECT_EXTENSIONS:
            result["status"] = "skipped"
            result["message"] = f"Project file ignored: {src.name}"
            return result

        category = get_category(src)
        result["category"] = category

        # ── Update Music Path based on Mood (AI) ───────────────────
        # If it's music, we add an extra 'Mood' subfolder
        # (This is fetched from global settings via the manager)
        if category == "Music":
            from folder_manager import load_global_settings
            gs         = load_global_settings()
            use_ai     = gs.get("music_ai_enabled", False)
            api_key    = gs.get("gemini_api_key", "")
            
            metadata   = MusicAnalyzer.get_metadata(src)
            # Add folder name as hint for the AI
            metadata["folder_hint"] = src.parent.name
            mood       = MusicAnalyzer.determine_mood(metadata, api_key, use_ai)
            
            dst_dir    = watch_folder / category / mood
        # ── Build destination directory (Common Categories) ─────────
        # For Documents, Images, and Videos we add a Year/Month layer
        elif category in DATE_SORTED_CATEGORIES:
            mtime   = src.stat().st_mtime
            dt      = datetime.fromtimestamp(mtime)
            year    = dt.strftime("%Y")           # e.g. "2024"
            month   = dt.strftime("%B")           # e.g. "April"
            dst_dir = watch_folder / category / year / month
        else:
            dst_dir = watch_folder / category

        # mkdir is deferred to here — folder only exists once a file moves in
        dst_dir.mkdir(parents=True, exist_ok=True)

        # Apply smart rename if requested
        effective_name = _smart_rename(src).name if use_smart_rename else src.name
        dst_path = dst_dir / effective_name

        # Handle duplicates
        final_dst = _resolve_destination(dst_path, src, use_smart_rename, duplicate_action)
        if final_dst is None:
            result["status"] = "skipped"
            result["message"] = "Duplicate – skipped"
            return result

        shutil.move(str(src), str(final_dst))

        # Record in undo stack
        _undo_stack.append({"src": str(src), "dst": str(final_dst)})
        if len(_undo_stack) > MAX_UNDO:
            _undo_stack.pop(0)

        result["status"] = "moved"
        result["dst"] = str(final_dst)
        # Show the full relative sub-path in the log message
        try:
            rel = final_dst.relative_to(watch_folder)
        except ValueError:
            rel = final_dst.name
        result["message"] = f"{src.name} → {rel}"
        logging.info(f"[MOVED] {src} → {final_dst}")

    except PermissionError as e:
        result["status"] = "error"
        result["message"] = f"Permission denied: {e}"
        logging.error(f"[ERROR] {e}")
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)
        logging.error(f"[ERROR] {e}")

    return result


def undo_last_move() -> dict:
    """
    Reverse the most recent file move.

    Returns:
        {"status": "ok"|"error"|"empty", "message": str}
    """
    if not _undo_stack:
        return {"status": "empty", "message": "Nothing to undo"}

    entry = _undo_stack.pop()
    src_original = Path(entry["src"])
    dst_current  = Path(entry["dst"])

    try:
        if not dst_current.exists():
            return {"status": "error",
                    "message": f"File no longer exists: {dst_current.name}"}

        # Restore to original location
        src_original.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst_current), str(src_original))
        logging.info(f"[UNDO] {dst_current} → {src_original}")
        return {"status": "ok",
                "message": f"Restored: {dst_current.name} → {src_original.parent}"}
    except Exception as e:
        logging.error(f"[UNDO ERROR] {e}")
        return {"status": "error", "message": str(e)}


def sort_existing_files(
    folder: Path,
    use_smart_rename: bool = False,
    duplicate_action: str = "rename",
    recursive: bool = False,
    progress_callback=None,
) -> list[dict]:
    """
    Sort all existing files in *folder*.
    If recursive=True, scans all sub-folders too.
    """
    results = []
    try:
        if recursive:
            files = [f for f in folder.rglob("*") if f.is_file()]
        else:
            files = [f for f in folder.iterdir() if f.is_file()]
    except PermissionError:
        return results

    for i, f in enumerate(files):
        res = move_file(f, folder, use_smart_rename, duplicate_action)
        results.append(res)
        if progress_callback:
            progress_callback(i + 1, len(files), res)

    return results
