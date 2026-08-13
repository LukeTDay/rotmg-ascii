"""
Merges hand-curated overrides onto the auto-derived render info and writes
the final `Resources/renderMap.json`.

Same tracked-template/gitignored-live-file split as
`Config/Account Credentials/account_credentials.json` (see CLAUDE.md):
`renderMapOverrides.jsonEXAMPLE` is tracked; `renderMapOverrides.json` is
gitignored and not auto-created - copy the example to activate it.

Overrides are merged per-field (shallow merge onto the auto-generated
entry), so an override only needs to specify what it's changing.
"""

import json
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    # allow running this file directly (`python mergeOverrides.py`), not
    # just via `python -m Scripts.AssetPipeline.mergeOverrides`
    sys.path.insert(0, _REPO_ROOT)

from Scripts.AssetPipeline.deriveRenderInfo import RenderInfo

OVERRIDES_PATH = Path(__file__).resolve().parents[2] / "Resources" / "renderMapOverrides.json"
RENDER_MAP_PATH = Path(__file__).resolve().parents[2] / "Resources" / "renderMap.json"

EMPTY_OVERRIDES = {"objects": {}, "ground": {}}


def loadOverrides(path: Path = OVERRIDES_PATH) -> dict:
    """Never raises - a missing overrides file just means no overrides."""
    if not path.is_file():
        return dict(EMPTY_OVERRIDES)
    return json.loads(path.read_text(encoding="utf-8"))


def mergeOverrides(derived: dict[str, dict[int, RenderInfo]], overrides: dict) -> dict:
    """Returns the final JSON-ready structure: {"objects": {"<id>": {...}}, "ground": {...}}."""
    result: dict[str, dict[str, dict]] = {"objects": {}, "ground": {}}
    for category in ("objects", "ground"):
        base = {
            str(entity_id): {
                "name": info.name,
                "chars": info.chars,
                "color": info.color,
                "blocksMovement": info.blocksMovement,
                "isEnemy": info.isEnemy,
                "isLootBag": info.isLootBag,
                "isPortal": info.isPortal,
                "isInteractiveNpc": info.isInteractiveNpc,
                "isBeacon": info.isBeacon,
                "isBeaconMarker": info.isBeaconMarker,
                "isBoss": info.isBoss,
                "weaponLabel": info.weaponLabel,
                "bagColorTier": info.bagColorTier,
                "tier": info.tier,
                "mpCost": info.mpCost,
                "mpEndCost": info.mpEndCost,
                "description": info.description,
                "baseSize": info.baseSize,
                "hitboxScale": info.hitboxScale,
            }
            for entity_id, info in derived[category].items()
        }
        for id_str, override_fields in overrides.get(category, {}).items():
            entry = dict(base.get(id_str, {}))
            entry.update(override_fields)
            base[id_str] = entry
        result[category] = base
    return result


def writeRenderMap(merged: dict, output_path: Path = RENDER_MAP_PATH) -> None:
    output_path.write_text(json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    from Scripts.AssetPipeline.deriveRenderInfo import deriveAll, loadSheetImages
    from Scripts.AssetPipeline.parseGameXml import GENERATED_ROOT, parseAll
    from Scripts.AssetPipeline.spriteIndex import loadSpriteIndex

    parsed = parseAll()
    sprite_index = loadSpriteIndex(GENERATED_ROOT / "spritesheetf.bin")
    sheet_images = loadSheetImages(GENERATED_ROOT / "png")
    derived = deriveAll(parsed, sprite_index, sheet_images)

    overrides = loadOverrides()
    print(f"Loaded overrides: {sum(len(v) for v in overrides.values())} entries")

    merged = mergeOverrides(derived, overrides)
    writeRenderMap(merged)
    print(f"Wrote {RENDER_MAP_PATH}")

    for id_str in list(overrides.get("objects", {}).keys())[:3]:
        print(f"  [objects] {id_str}: {merged['objects'].get(id_str)}")
    for id_str in list(overrides.get("ground", {}).keys())[:3]:
        print(f"  [ground] {id_str}: {merged['ground'].get(id_str)}")
