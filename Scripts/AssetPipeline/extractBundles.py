"""
Extracts raw game-data assets (XML/JSON TextAssets, the binary sprite atlas
index, four spritesheet PNGs) from the local RotMG Exalt Unity install into
`Resources/_generated/`.

Adapted from exalt-extractor's Resources.py/Extractor.py, with two fixes
found against a real install: the sprite atlas TextAsset is named
"spritesheetf" and is a binary blob, not JSON as exalt-extractor assumes;
and TextAssets are classified by sniffing their first byte (`<`/`{`/`[`)
instead of a hardcoded name blacklist, which goes stale across game updates.
Every file loads cleanly through `UnityPy.load()` (no per-file try/except
needed) - confirmed against a real install.
"""

import json
import sys
from pathlib import Path

import UnityPy

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    # allow running this file directly (`python extractBundles.py`), not
    # just via `python -m Scripts.AssetPipeline.extractBundles` from the
    # repo root - either way, `Scripts.AssetPipeline.*` needs to resolve
    sys.path.insert(0, _REPO_ROOT)

from Scripts.AssetPipeline.locateInstall import findInstallPath

# Texture2D names known to be the game's spritesheet atlases (not UI icons).
SPRITESHEET_NAMES = {"characters", "characters_masks", "groundTiles", "mapObjects"}

OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "Resources" / "_generated"


def _script_bytes(text_asset) -> bytes:
    """UnityPy decodes m_Script as str via surrogateescape (doesn't know if a
    TextAsset is text or binary) - re-encoding the same way round-trips
    binary assets back to their exact original bytes.
    """
    script = text_asset.m_Script
    return script.encode("utf-8", errors="surrogateescape") if isinstance(script, str) else bytes(script)


def _classify(raw: bytes) -> str:
    """Sniff a TextAsset's content to decide its real extension."""
    stripped = raw.lstrip()
    if stripped.startswith(b"<"):
        return "xml"
    if stripped[:1] in (b"{", b"["):
        return "json"
    return "bin"


def _iter_unity_objects(install_path: Path):
    for path in install_path.rglob("*"):
        if not path.is_file():
            continue
        env = UnityPy.load(str(path))
        yield from env.objects


def extractAll(install_path: Path | None = None, output_root: Path = OUTPUT_ROOT) -> dict:
    """
    Walk the install directory, dump every TextAsset (by sniffed content
    type) and every known spritesheet Texture2D into `output_root`.
    Returns a small summary dict for the caller to report/verify.
    """
    if install_path is None:
        install_path = findInstallPath()

    xml_dir = output_root / "xml"
    json_dir = output_root / "json"
    png_dir = output_root / "png"
    for d in (xml_dir, json_dir, png_dir):
        d.mkdir(parents=True, exist_ok=True)

    written_names: set[str] = set()
    spritesheets_found: set[str] = set()
    counts = {"xml": 0, "json": 0, "bin": 0, "png": 0}
    large_textures_skipped = []

    for obj in _iter_unity_objects(install_path):
        if obj.type.name == "TextAsset":
            data = obj.read()
            name = data.m_Name
            if not name or name in written_names:
                continue
            raw = _script_bytes(data)
            kind = _classify(raw)
            if kind == "xml":
                (xml_dir / f"{name}.xml").write_bytes(raw)
            elif kind == "json":
                (json_dir / f"{name}.json").write_bytes(raw)
            else:
                (output_root / f"{name}.bin").write_bytes(raw)
            written_names.add(name)
            counts[kind] += 1

        elif obj.type.name == "Texture2D":
            data = obj.read()
            name = data.m_Name
            if name in SPRITESHEET_NAMES:
                data.image.save(png_dir / f"{name}.png", "PNG")
                spritesheets_found.add(name)
                counts["png"] += 1
            elif data.m_Width * data.m_Height >= 1_000_000:
                # Large texture not in our known-name allowlist — flag it,
                # since a future game update could rename/add a spritesheet.
                large_textures_skipped.append((name, data.m_Width, data.m_Height))

    return {
        "install_path": str(install_path),
        "output_root": str(output_root),
        "counts": counts,
        "spritesheets_found": sorted(spritesheets_found),
        "spritesheets_missing": sorted(SPRITESHEET_NAMES - spritesheets_found),
        "large_textures_skipped": large_textures_skipped,
    }


if __name__ == "__main__":
    summary = extractAll()
    print(f"Install path: {summary['install_path']}")
    print(f"Output root:  {summary['output_root']}")
    print(f"Counts: {summary['counts']}")
    print(f"Spritesheets found: {summary['spritesheets_found']}")
    if summary["spritesheets_missing"]:
        print(f"Spritesheets MISSING: {summary['spritesheets_missing']}")
    if summary["large_textures_skipped"]:
        print("Large textures NOT extracted (not in SPRITESHEET_NAMES) - review if these should be added:")
        for name, w, h in summary["large_textures_skipped"]:
            print(f"  {name}: {w}x{h}")
