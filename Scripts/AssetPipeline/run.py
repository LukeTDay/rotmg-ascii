"""
Orchestrator: runs the full asset pipeline end to end and writes the final
`Resources/renderMap.json`. Re-extracts fresh from the local install every
run (fast - a few seconds) rather than assuming `Resources/_generated/` is
already up to date, since the whole point is "run this after every game
update" without manual steps.

    python -m Scripts.AssetPipeline.run
"""

import time

from Scripts.AssetPipeline.deriveRenderInfo import deriveAll, loadSheetImages
from Scripts.AssetPipeline.extractBundles import extractAll
from Scripts.AssetPipeline.mergeOverrides import loadOverrides, mergeOverrides, writeRenderMap
from Scripts.AssetPipeline.parseGameXml import GENERATED_ROOT, parseAll
from Scripts.AssetPipeline.spriteIndex import loadSpriteIndex


def run() -> None:
    t0 = time.time()

    print("[1/4] Extracting assets from the local install...")
    extract_summary = extractAll()
    print(f"      {extract_summary['counts']}")
    if extract_summary["spritesheets_missing"]:
        raise RuntimeError(f"Missing expected spritesheets: {extract_summary['spritesheets_missing']}")

    print("[2/4] Parsing object/ground XML...")
    parsed = parseAll()
    print(f"      {len(parsed['objects'])} objects, {len(parsed['ground'])} ground types "
          f"({len(parsed['missing_files'])} manifest files missing on disk)")

    print("[3/4] Deriving char/color render info...")
    sprite_index = loadSpriteIndex(GENERATED_ROOT / "spritesheetf.bin")
    sheet_images = loadSheetImages(GENERATED_ROOT / "png")
    derived = deriveAll(parsed, sprite_index, sheet_images)

    print("[4/4] Merging overrides and writing renderMap.json...")
    overrides = loadOverrides()
    override_count = sum(len(v) for v in overrides.values())
    merged = mergeOverrides(derived, overrides)
    writeRenderMap(merged)

    total_entries = len(merged["objects"]) + len(merged["ground"])
    print(f"\nDone in {time.time() - t0:.1f}s - {total_entries} entries "
          f"({override_count} overridden) written to Resources/renderMap.json")


if __name__ == "__main__":
    run()
