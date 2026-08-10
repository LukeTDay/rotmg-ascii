"""
Parses XML TextAssets from `extractBundles.py` into per-object/per-ground-type
identity data: numeric id, display name, sprite rects (via `spriteIndex.py`).

Same defensive "skip element if a critical field is missing" pattern as
`Utils/XML/parseObjectNames.py`/`parseGroundTypes.py`, with three differences:
- `manifest.json` lists which extracted files are "objects" vs "tiles"
  (ground), including per-dungeon overrides — the authoritative file list,
  not a filename guess.
- A `<RandomTexture>` block wraps several `<Texture>` variants (e.g. "Wood
  Plank Floor" has 5) — all are collected, not just the first.
- `<AnimatedTexture>` is treated like `<Texture>` (same File/Index children).
"""

import json
import sys
import xml.etree.ElementTree as et
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    # allow running this file directly (`python parseGameXml.py`), not
    # just via `python -m Scripts.AssetPipeline.parseGameXml`
    sys.path.insert(0, _REPO_ROOT)

from Scripts.AssetPipeline.spriteIndex import SpriteRect, loadSpriteIndex

GENERATED_ROOT = Path(__file__).resolve().parents[2] / "Resources" / "_generated"

TEXTURE_TAGS = ("Texture", "AnimatedTexture")

# Fields needed to simulate flight/damage/hitbox; everything else a
# <Projectile> can carry (Wavy, Boomerang, TurnRate*, etc. - real flight
# variants, not typos) is preserved in ParsedProjectile.extras instead.
_PROJECTILE_CORE_TAGS = {
    "ObjectId", "Speed", "LifetimeMS", "Damage", "MinDamage", "MaxDamage",
    "Size", "MultiHit", "ArmorPiercing", "PassesCover",
}

# Click-to-interact NPC classes - same per-field check as isLootBag/isPortal.
_INTERACTIVE_NPC_CLASSES = {"Merchant", "Enchanter", "YardUpgrader", "InteractiveInfoObject"}


@dataclass
class ParsedProjectile:
    id: int
    objectId: str
    speed: float
    lifetimeMS: int
    damage: int = 0
    minDamage: int | None = None
    maxDamage: int | None = None
    size: int | None = None
    multiHit: bool = False
    armorPiercing: bool = False
    passesCover: bool = False
    extras: dict[str, str] = field(default_factory=dict)  # raw text of any other child tag, by tag name
    # Belong to the owning <Object>, not the <Projectile> child (confirmed
    # vs real weapon XML) - duplicated onto every ParsedProjectile here so
    # one lookup serves both rendering and outgoing-shot construction.
    rateOfFire: float = 1.0
    numProjectiles: int = 1
    arcGapDegrees: float = 11.25


@dataclass
class ParsedEntity:
    entityId: int
    name: str
    textureRefs: list[tuple[str, int]] = field(default_factory=list)  # (spriteSheetName, index)
    projectiles: list[ParsedProjectile] = field(default_factory=list)
    # Object-only flags (Ground keeps defaults) feeding the map renderer's
    # tier hierarchy. HealthBarBoss is the real client's own boss-UI flag,
    # reused here to uppercase a boss's name-derived glyph.
    blocksMovement: bool = False
    isEnemy: bool = False
    isLootBag: bool = False
    isPortal: bool = False
    isInteractiveNpc: bool = False
    isBoss: bool = False


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


def _parseNumber(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _parseProjectiles(elem: et.Element) -> list[ParsedProjectile]:
    """Parses every <Projectile id="N"> child of a weapon/enemy <Object>; `id`
    selects which projectile a SERVERPLAYERSHOOT/ENEMYSHOOT packet refers to
    (default 0). RateOfFire/NumProjectiles/ArcGap live on the owning <Object>,
    not the <Projectile> itself (confirmed vs real weapon XML), so they're
    read once and duplicated onto each result. ArcGap defaults to 11.25 when
    undefined - an explicit 0 is a real "no spread" value, not the same thing.
    """
    rateOfFire = _parseNumber(elem.findtext("RateOfFire"))
    rateOfFire = rateOfFire if rateOfFire is not None else 1.0

    numProjectilesRaw = _parseNumber(elem.findtext("NumProjectiles"))
    numProjectiles = int(numProjectilesRaw) if numProjectilesRaw is not None else 1

    arcGapDegrees = _parseNumber(elem.findtext("ArcGap"))
    arcGapDegrees = arcGapDegrees if arcGapDegrees is not None else 11.25

    projectiles: list[ParsedProjectile] = []
    for projElem in elem.findall("Projectile"):
        objectIdElem = projElem.find("ObjectId")
        speed = _parseNumber(projElem.findtext("Speed"))
        lifetime = _parseNumber(projElem.findtext("LifetimeMS"))
        if objectIdElem is None or not objectIdElem.text or speed is None or lifetime is None:
            continue  # can't simulate flight without these - skip this projectile
        # Raw XML <Speed> is 10x true tiles/second (confirmed against
        # RealmEye's documented values) - divided so .speed is real
        # tiles/second downstream.
        speed /= 10.0

        try:
            projId = int(projElem.get("id", "0"))
        except ValueError:
            projId = 0

        damage = _parseNumber(projElem.findtext("Damage"))
        minDamage = _parseNumber(projElem.findtext("MinDamage"))
        maxDamage = _parseNumber(projElem.findtext("MaxDamage"))
        size = _parseNumber(projElem.findtext("Size"))

        extras: dict[str, str] = {}
        for child in projElem:
            if child.tag in _PROJECTILE_CORE_TAGS:
                continue
            extras[child.tag] = child.text if child.text is not None else ""

        projectiles.append(ParsedProjectile(
            id=projId,
            objectId=objectIdElem.text.strip(),
            speed=speed,
            lifetimeMS=int(lifetime),
            damage=int(damage) if damage is not None else 0,
            minDamage=int(minDamage) if minDamage is not None else None,
            maxDamage=int(maxDamage) if maxDamage is not None else None,
            size=int(size) if size is not None else None,
            multiHit=projElem.find("MultiHit") is not None,
            armorPiercing=projElem.find("ArmorPiercing") is not None,
            passesCover=projElem.find("PassesCover") is not None,
            extras=extras,
            rateOfFire=rateOfFire,
            numProjectiles=numProjectiles,
            arcGapDegrees=arcGapDegrees,
        ))
    return projectiles


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
        if tag == "Object":
            projectiles = _parseProjectiles(elem)
            blocksMovement = elem.find("OccupySquare") is not None or elem.find("FullOccupy") is not None
            isEnemy = elem.find("Enemy") is not None
            classElem = elem.find("Class")
            classText = classElem.text.strip() if classElem is not None and classElem.text is not None else None
            isLootBag = classText == "Container"
            isPortal = classText == "Portal"
            isInteractiveNpc = classText in _INTERACTIVE_NPC_CLASSES
            isBoss = elem.find("HealthBarBoss") is not None
        else:
            projectiles = []
            blocksMovement = isEnemy = isLootBag = isPortal = isInteractiveNpc = isBoss = False
        entities[entityId] = ParsedEntity(
            entityId=entityId,
            name=name,
            textureRefs=textureRefs,
            projectiles=projectiles,
            blocksMovement=blocksMovement,
            isEnemy=isEnemy,
            isLootBag=isLootBag,
            isPortal=isPortal,
            isInteractiveNpc=isInteractiveNpc,
            isBoss=isBoss,
        )
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
