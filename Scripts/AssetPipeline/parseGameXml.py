"""
Parses the XML TextAssets extracted by `extractBundles.py` into per-object /
per-ground-type identity data: numeric type id, display name, and the list
of sprite rects (via `spriteIndex.py`) that render it.

Follows the same defensive "skip the element if a critical field is
missing" pattern as `Utils/XML/parseObjectNames.py` / `parseGroundTypes.py`
(this repo's existing convention for RotMG XML), but differs from those two
in three ways the real extracted data required:

- There isn't one `object.xml`/`ground.xml` — `manifest.json` (extracted
  alongside the XML files) lists exactly which extracted files belong to
  the "objects" category and which belong to "tiles" (ground), including
  ~150/~55 per-dungeon override files respectively. That list is the
  authoritative source of which files to parse, rather than a filename
  guess.
- A `<Ground>` (and occasionally `<Object>`) element can wrap several
  `<Texture>` children in a `<RandomTexture>` block — the game picks one at
  random for visual variety on otherwise-identical tiles (e.g. "Wood Plank
  Floor" has 5 texture variants). Every variant is collected, not just the
  first, since this is exactly the real, data-driven version of the
  "render a floor as `.` sometimes and `,` other times" case Phase 3/4 are
  designed around.
- `<AnimatedTexture>` is treated the same as `<Texture>` (same `File`/
  `Index` children) per the reference parsing in RealmShark's
  `AssetExtractor.addTexture`.
"""

import json
import xml.etree.ElementTree as et
from dataclasses import dataclass, field
from pathlib import Path

from Scripts.AssetPipeline.spriteIndex import SpriteRect, loadSpriteIndex

GENERATED_ROOT = Path(__file__).resolve().parents[2] / "Resources" / "_generated"

TEXTURE_TAGS = ("Texture", "AnimatedTexture")


@dataclass
class ParsedEntity:
    entityId: int
    name: str
    textureRefs: list[tuple[str, int]] = field(default_factory=list)  # (spriteSheetName, index)


def _parseTypeAttr(raw: str) -> int | None:
    try:
        return int(raw, 16)
    except (TypeError, ValueError):
        return None


def _parseIndex(raw: str) -> int | None:
    raw = raw.strip()
    try:
        return int(raw, 16) if raw.lower().startswith("0x") else int(raw)
    except ValueError:
        return None


def _parseTextureRefs(elem: et.Element) -> list[tuple[str, int]]:
    refs: list[tuple[str, int]] = []
    for child in elem:
        if child.tag in TEXTURE_TAGS:
            fileElem = child.find("File")
            indexElem = child.find("Index")
            if fileElem is None or not fileElem.text or indexElem is None or not indexElem.text:
                continue
            index = _parseIndex(indexElem.text)
            if index is None:
                continue
            refs.append((fileElem.text.strip(), index))
        elif child.tag == "RandomTexture":
            refs.extend(_parseTextureRefs(child))
    return refs


def _parseEntities(xmlText: str, tag: str) -> dict[int, ParsedEntity]:
    """Pure parse: XML text -> {typeId: ParsedEntity}, for either `Object` or `Ground` elements."""
    entities: dict[int, ParsedEntity] = {}
    root = et.fromstring(xmlText)
    for elem in root.findall(tag):
        typeAttr = elem.get("type")
        idAttr = elem.get("id")
        if typeAttr is None or idAttr is None:
            continue
        entityId = _parseTypeAttr(typeAttr)
        if entityId is None:
            continue
        displayIdElem = elem.find("DisplayId")
        name = displayIdElem.text if displayIdElem is not None and displayIdElem.text else idAttr
        textureRefs = _parseTextureRefs(elem)
        if not textureRefs:
            continue  # nothing to render this entity with
        entities[entityId] = ParsedEntity(entityId=entityId, name=name, textureRefs=textureRefs)
    return entities


def _loadManifestFileLists(manifest_path: Path) -> tuple[list[str], list[str]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    object_files = [Path(entry["path"]).stem for entry in manifest.get("objects", [])]
    tile_files = [Path(entry["path"]).stem for entry in manifest.get("tiles", [])]
    return object_files, tile_files


def parseAll(generated_root: Path = GENERATED_ROOT) -> dict:
    """
    Returns:
        {
            "objects": {typeId: ParsedEntity},
            "ground": {typeId: ParsedEntity},
            "missing_files": [names in manifest.json not found on disk],
            "id_collisions": {"objects": count, "ground": count},
        }
    Later files in manifest.json's list win on id collisions (per-dungeon
    files are treated as overrides layered on the global list).
    """
    object_files, tile_files = _loadManifestFileLists(generated_root / "json" / "manifest.json")
    xml_dir = generated_root / "xml"

    def _parse_category(file_names: list[str], tag: str) -> tuple[dict[int, ParsedEntity], int]:
        merged: dict[int, ParsedEntity] = {}
        collisions = 0
        for name in file_names:
            path = xml_dir / f"{name}.xml"
            if not path.is_file():
                missing_files.append(name)
                continue
            parsed = _parseEntities(path.read_text(encoding="utf-8"), tag)
            collisions += len(merged.keys() & parsed.keys())
            merged.update(parsed)
        return merged, collisions

    missing_files: list[str] = []
    objects, object_collisions = _parse_category(object_files, "Object")
    ground, ground_collisions = _parse_category(tile_files, "Ground")

    return {
        "objects": objects,
        "ground": ground,
        "missing_files": missing_files,
        "id_collisions": {"objects": object_collisions, "ground": ground_collisions},
    }


def resolveSpriteRects(
    entity: ParsedEntity, sprite_index: dict[str, dict[int, SpriteRect]]
) -> list[SpriteRect]:
    """Resolve every texture ref on an entity to its SpriteRect, skipping any that don't resolve."""
    rects = []
    for sheet_name, sprite_idx in entity.textureRefs:
        rect = sprite_index.get(sheet_name, {}).get(sprite_idx)
        if rect is not None:
            rects.append(rect)
    return rects


if __name__ == "__main__":
    result = parseAll()
    print(f"Objects: {len(result['objects'])} (id collisions: {result['id_collisions']['objects']})")
    print(f"Ground:  {len(result['ground'])} (id collisions: {result['id_collisions']['ground']})")
    if result["missing_files"]:
        print(f"Missing files referenced by manifest.json: {result['missing_files']}")

    sprite_index = loadSpriteIndex(GENERATED_ROOT / "spritesheetf.bin")
    unresolved = 0
    multi_variant = 0
    samples = []
    for category in ("objects", "ground"):
        for entity_id, entity in result[category].items():
            rects = resolveSpriteRects(entity, sprite_index)
            if not rects:
                unresolved += 1
            elif len(rects) > 1:
                multi_variant += 1
            if len(samples) < 8 and rects:
                samples.append((category, entity_id, entity.name, rects))

    print(f"\nEntities with zero resolvable sprite rects: {unresolved}")
    print(f"Entities with multiple sprite variants (RandomTexture): {multi_variant}")
    print("\nSamples:")
    for category, entity_id, name, rects in samples:
        print(f"  [{category}] {entity_id} {name!r}: {len(rects)} rect(s), first={rects[0]}")
