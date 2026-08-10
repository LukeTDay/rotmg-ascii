"""
Finds the game's build version string that `run.py` writes to
`Resources/version.txt` for the HELLO handshake.

Not in any extracted TextAsset/XML/JSON (confirmed by grep) - it's a
compiled string literal in the install's il2cpp metadata file
(`il2cpp_data/Metadata/global-metadata.dat`), found via regex, no full
il2cpp dump needed. Confirmed against a real install: the 5-part version
pattern appears exactly once in that file.
"""

import re
from pathlib import Path

# 5-part version scheme (X.Y.Z.W.V), deliberately not a general N.N.N
# pattern - avoids matching "127.0.0.1"-style noise in the same file.
VERSION_PATTERN = re.compile(rb"\b\d+\.\d+\.\d+\.\d+\.\d+\b")

METADATA_RELATIVE_PATH = Path("il2cpp_data") / "Metadata" / "global-metadata.dat"


def findGameVersion(install_path: Path) -> str:
    """
    Return the game's build version string found in the install's il2cpp
    metadata file. Raises if the file is missing or the version can't be
    found unambiguously (more than one distinct candidate match).
    """
    metadata_path = install_path / METADATA_RELATIVE_PATH
    if not metadata_path.is_file():
        raise FileNotFoundError(f"il2cpp metadata file not found at: {metadata_path}")

    data = metadata_path.read_bytes()
    candidates = {m.group().decode("ascii") for m in VERSION_PATTERN.finditer(data)}

    if not candidates:
        raise ValueError(f"No version-like string found in {metadata_path}")
    if len(candidates) > 1:
        raise ValueError(
            f"Ambiguous version: found {len(candidates)} distinct candidates in {metadata_path}: {sorted(candidates)}"
        )
    return candidates.pop()


if __name__ == "__main__":
    import sys

    _REPO_ROOT = str(Path(__file__).resolve().parents[2])
    if _REPO_ROOT not in sys.path:
        # allow running this file directly (`python findVersion.py`), not
        # just via `python -m Scripts.AssetPipeline.findVersion`
        sys.path.insert(0, _REPO_ROOT)

    from Scripts.AssetPipeline.locateInstall import findInstallPath

    path = findInstallPath()
    print(f"Game version: {findGameVersion(path)}")
