"""
Orchestrator: runs the full asset pipeline end to end and writes the final
`Resources/renderMap.json` + `Resources/version.txt`. Re-extracts fresh from
the local install every run (fast - a few seconds) rather than assuming
`Resources/_generated/` is already up to date, since the whole point is
"run this after every game update" without manual steps.

    python -m Scripts.AssetPipeline.run
"""

import time
from pathlib import Path

from Scripts.AssetPipeline.deriveRenderInfo import deriveAll, loadSheetImages
from Scripts.AssetPipeline.extractBundles import extractAll
from Scripts.AssetPipeline.findVersion import findGameVersion
from Scripts.AssetPipeline.locateInstall import findInstallPath
from Scripts.AssetPipeline.mergeOverrides import loadOverrides, mergeOverrides, writeRenderMap
from Scripts.AssetPipeline.parseGameXml import GENERATED_ROOT, parseAll
from Scripts.AssetPipeline.spriteIndex import loadSpriteIndex

VERSION_TXT_PATH = Path(__file__).resolve().parents[2] / "Resources" / "version.txt"


def run() -> None:
    t0 = time.time()

    print("[1/5] Locating install and extracting assets...")
    install_path = findInstallPath()
    extract_summary = extractAll(install_path)
    print(f"      {extract_summary['counts']}")
    if extract_summary["spritesheets_missing"]:
        raise RuntimeError(f"Missing expected spritesheets: {extract_summary['spritesheets_missing']}")

    print("[2/5] Finding game version...")
    game_version = findGameVersion(install_path)
    VERSION_TXT_PATH.write_text(game_version, encoding="utf-8")
    print(f"      {game_version} -> Resources/version.txt")

    print("[3/5] Parsing object/ground XML...")
    parsed = parseAll()
    print(f"      {len(parsed['objects'])} objects, {len(parsed['ground'])} ground types "
          f"({len(parsed['missing_files'])} manifest files missing on disk)")

    print("[4/5] Deriving char/color render info...")
    sprite_index = loadSpriteIndex(GENERATED_ROOT / "spritesheetf.bin")
    sheet_images = loadSheetImages(GENERATED_ROOT / "png")
    derived = deriveAll(parsed, sprite_index, sheet_images)

    print("[5/5] Merging overrides and writing renderMap.json...")
    overrides = loadOverrides()
    override_count = sum(len(v) for v in overrides.values())
    merged = mergeOverrides(derived, overrides)
    writeRenderMap(merged)

    total_entries = len(merged["objects"]) + len(merged["ground"])
    print(f"\nDone in {time.time() - t0:.1f}s - {total_entries} entries "
          f"({override_count} overridden) written to Resources/renderMap.json")


if __name__ == "__main__":
    run()
