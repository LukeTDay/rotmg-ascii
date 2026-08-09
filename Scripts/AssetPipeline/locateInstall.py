"""
Locates the local RotMG Exalt install directory (the folder containing
`resources.assets`, e.g. `.../RotMG Exalt_Data`), so the rest of the asset
pipeline knows where to read Unity asset bundles from.

Ported from exalt-extractor's `utils/Resources.py::get_resource_path`, with
its console-input fallback swapped for a Tkinter folder-picker popup per
project preference, and a local path cache added so the picker only appears
once per machine.
"""

import pathlib
from platform import system

CACHE_FILE = pathlib.Path(__file__).parent / ".installPath.txt"

# Default Exalt resource path relative to the user's home directory, per OS.
PATH_WINDOWS = pathlib.PurePath("Documents", "RealmOfTheMadGod", "Production", "RotMG Exalt_Data")
PATH_MACOS = pathlib.PurePath("RealmOfTheMadGod", "Production", "RotMGExalt.app", "Contents", "Resources", "Data")


def _is_valid_install(path: pathlib.Path) -> bool:
    """A valid Exalt install directory contains a `resources.assets` file."""
    return path.is_dir() and (path / "resources.assets").is_file()


def _default_path() -> pathlib.Path | None:
    """Return the default install path for the current OS, if it exists."""
    home = pathlib.Path.home()
    os_name = system()
    if os_name == "Windows":
        candidate = home / PATH_WINDOWS
    elif os_name == "Darwin":
        candidate = home / PATH_MACOS
    else:
        return None
    return candidate if _is_valid_install(candidate) else None


def _prompt_for_path() -> pathlib.Path:
    """Pop a folder-picker dialog and loop until a valid install dir is chosen."""
    import tkinter
    from tkinter import filedialog, messagebox

    root = tkinter.Tk()
    root.withdraw()
    try:
        while True:
            selected = filedialog.askdirectory(
                title="Locate your RotMG Exalt install (the folder containing resources.assets)"
            )
            if not selected:
                raise SystemExit("No RotMG Exalt install directory selected — aborting.")
            candidate = pathlib.Path(selected)
            if _is_valid_install(candidate):
                return candidate
            messagebox.showerror(
                "Invalid folder",
                f"No 'resources.assets' file found in:\n{candidate}\n\nPlease pick the folder that directly contains it.",
            )
    finally:
        root.destroy()


def _load_cached_path() -> pathlib.Path | None:
    if not CACHE_FILE.is_file():
        return None
    cached = pathlib.Path(CACHE_FILE.read_text(encoding="utf-8").strip())
    return cached if _is_valid_install(cached) else None


def _save_cached_path(path: pathlib.Path) -> None:
    CACHE_FILE.write_text(str(path), encoding="utf-8")


def findInstallPath() -> pathlib.Path:
    """
    Resolve the local RotMG Exalt install directory: cached path, then the
    OS default, then a folder-picker popup as a last resort. The resolved
    path is cached to disk so the picker doesn't reappear on every run.
    """
    for candidate in (_load_cached_path, _default_path):
        path = candidate()
        if path is not None:
            _save_cached_path(path)
            return path

    path = _prompt_for_path()
    _save_cached_path(path)
    return path


if __name__ == "__main__":
    resolved = findInstallPath()
    print(f"Resolved RotMG Exalt install path: {resolved}")
