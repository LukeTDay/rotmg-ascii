"""
Orchestrator: runs the full asset pipeline end to end, writing
`Resources/renderMap.json` + `Resources/version.txt`. Re-extracts from the
local install every run rather than assuming `_generated/` is up to date.

    python -m Scripts.AssetPipeline.run
"""

import sys
import time
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    # allow running this file directly (`python run.py`), not just via
    # `python -m Scripts.AssetPipeline.run` from the repo root
    sys.path.insert(0, _REPO_ROOT)

from Scripts.AssetPipeline.deriveRenderInfo import deriveAll, loadSheetImages
from Scripts.AssetPipeline.extractBundles import extractAll
from Scripts.AssetPipeline.findVersion import findGameVersion
from Scripts.AssetPipeline.locateInstall import findInstallPath
from Scripts.AssetPipeline.mergeOverrides import loadOverrides, mergeOverrides, writeRenderMap
from Scripts.AssetPipeline.parseGameXml import GENERATED_ROOT, parseAll
from Scripts.AssetPipeline.spriteIndex import loadSpriteIndex
from Scripts.AssetPipeline.writeProjectileMap import buildProjectileMap, writeProjectileMap

VERSION_TXT_PATH = Path(__file__).resolve().parents[2] / "Resources" / "version.txt"


def run() -> None:
    t0 = time.time()

    print("[1/6] Locating install and extracting assets...")
    install_path = findInstallPath()
    extract_summary = extractAll(install_path)
    print(f"      {extract_summary['counts']}")
    if extract_summary["spritesheets_missing"]:
        raise RuntimeError(f"Missing expected spritesheets: {extract_summary['spritesheets_missing']}")

    print("[2/6] Finding game version...")
    game_version = findGameVersion(install_path)
    VERSION_TXT_PATH.write_text(game_version, encoding="utf-8")
    print(f"      {game_version} -> Resources/version.txt")

    print("[3/6] Parsing object/ground XML...")
    parsed = parseAll()
    print(f"      {len(parsed['objects'])} objects, {len(parsed['ground'])} ground types "
          f"({len(parsed['missing_files'])} manifest files missing on disk)")

    print("[4/6] Deriving char/color render info...")
    sprite_index = loadSpriteIndex(GENERATED_ROOT / "spritesheetf.bin")
    sheet_images = loadSheetImages(GENERATED_ROOT / "png")
    derived = deriveAll(parsed, sprite_index, sheet_images)

    print("[5/6] Merging overrides and writing renderMap.json...")
    overrides = loadOverrides()
    override_count = sum(len(v) for v in overrides.values())
    merged = mergeOverrides(derived, overrides)
    writeRenderMap(merged)

    total_entries = len(merged["objects"]) + len(merged["ground"])
    print(f"\n[6/6] Writing projectileMap.json...")
    projectile_map = buildProjectileMap(parsed["objects"])
    writeProjectileMap(projectile_map)
    projectile_total = sum(len(v) for v in projectile_map.values())

    print(f"\nDone in {time.time() - t0:.1f}s - {total_entries} render entries "
          f"({override_count} overridden) written to Resources/renderMap.json, "
          f"{projectile_total} projectile definitions written to Resources/projectileMap.json")


if __name__ == "__main__":
    run()
