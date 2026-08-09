"""
Merges hand-curated overrides on top of the auto-derived render info, and
writes the final `Resources/renderMap.json`.

Follows the same tracked-template / gitignored-live-file split as
`Credentials/account_credentials.json` + `.jsonEXAMPLE` (this repo's
existing convention, see CLAUDE.md): `renderMapOverrides.jsonEXAMPLE` ships
real example overrides and is tracked; `renderMapOverrides.json` is the
file this module actually reads, gitignored (covered by the repo's blanket
`*.json` rule), and not auto-created - copy the example to activate it.
That way a curated override (e.g. giving loot bags a `$` instead of the
default `*`) can ship in the repo without any risk of someone's local
override edits getting committed by accident.

An override entry is merged **per-field**, not swapped in wholesale: it's
shallow-merged on top of the auto-generated entry for that id (or used
as-is if the id has no auto-generated entry at all). That means a hand
override only needs to specify the fields it's actually changing - e.g.
just `chars` to reassign a glyph - without having to also copy over the
`name`/`color` it isn't touching.
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
            str(entity_id): {"name": info.name, "chars": info.chars, "color": info.color}
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
