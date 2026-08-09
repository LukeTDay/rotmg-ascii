"""
Finds the game's build version string (the one `gameVersion.txt` at the repo
root needs for the HELLO handshake, per CLAUDE.md).

It isn't in any TextAsset, XML, or JSON extracted by `extractBundles.py` —
confirmed by grepping every extracted file. It turns out to be a compiled
string literal inside the il2cpp metadata file
(`<install>/il2cpp_data/Metadata/global-metadata.dat`), which sits right in
the install directory — no `ExaltDumper`/full il2cpp dump required, just a
regex over the raw bytes.

Confirmed against a real install: the 5-part dotted pattern (`6.13.0.0.0`)
appears in `global-metadata.dat` exactly once, right next to `"127.0.0.1"`
and `"*Client*"` string literals, and matches this repo's existing
`gameVersion.txt` exactly.
"""

import re
from pathlib import Path

# Matches RotMG's 5-part version scheme (X.Y.Z.W.V). Deliberately 5 parts,
# not e.g. Unity's or a general N.N.N pattern, so it doesn't also match
# nearby noise like "127.0.0.1" IP-address strings in the same file.
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
    from Scripts.AssetPipeline.locateInstall import findInstallPath

    path = findInstallPath()
    print(f"Game version: {findGameVersion(path)}")
