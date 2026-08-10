"""
Writes `Resources/projectileMap.json`: every <Projectile> definition from
`parseGameXml.py`, keyed by owning weapon/enemy objectType then projectile
`id` (the slot a SERVERPLAYERSHOOT/ENEMYSHOOT packet references).

Unlike renderMap.json, no derive/override step - straight structural copy,
since speed/damage/lifetime come directly from XML, not pixel data.
"""

import json
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    # allow running this file directly (`python writeProjectileMap.py`), not
    # just via `python -m Scripts.AssetPipeline.writeProjectileMap`
    sys.path.insert(0, _REPO_ROOT)

from Scripts.AssetPipeline.parseGameXml import ParsedProjectile

PROJECTILE_MAP_PATH = Path(__file__).resolve().parents[2] / "Resources" / "projectileMap.json"


def _projectileToDict(proj: ParsedProjectile, nameToId: dict) -> dict:
    return {
        "objectId": proj.objectId,
        "speed": proj.speed,
        "lifetimeMS": proj.lifetimeMS,
        "damage": proj.damage,
        "minDamage": proj.minDamage,
        "maxDamage": proj.maxDamage,
        "size": proj.size,
        "multiHit": proj.multiHit,
        "armorPiercing": proj.armorPiercing,
        "passesCover": proj.passesCover,
        "extras": proj.extras,
        "rateOfFire": proj.rateOfFire,
        "numProjectiles": proj.numProjectiles,
        "arcGapDegrees": proj.arcGapDegrees,
        # A projectile's visual identity is a separate <Object> (objectId is
        # a display name, not numeric) - resolved to its entity id here so
        # the renderer can reuse the normal renderMap.json color path
        # instead of a second derivation pipeline.
        "visualObjectType": nameToId.get(proj.objectId),
    }


def buildProjectileMap(parsed_objects: dict) -> dict:
    """`parsed_objects` is `parseAll()["objects"]` - {entityId: ParsedEntity}."""
    nameToId = {entity.name: entityId for entityId, entity in parsed_objects.items()}
    result: dict[str, dict[str, dict]] = {}
    for entityId, entity in parsed_objects.items():
        if not entity.projectiles:
            continue
        result[str(entityId)] = {str(proj.id): _projectileToDict(proj, nameToId) for proj in entity.projectiles}
    return result


def writeProjectileMap(projectile_map: dict, output_path: Path = PROJECTILE_MAP_PATH) -> None:
    output_path.write_text(json.dumps(projectile_map, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    from Scripts.AssetPipeline.parseGameXml import parseAll

    parsed = parseAll()
    projectile_map = buildProjectileMap(parsed["objects"])
    writeProjectileMap(projectile_map)
    total = sum(len(v) for v in projectile_map.values())
    print(f"Wrote {len(projectile_map)} owners ({total} projectile definitions) to {PROJECTILE_MAP_PATH}")
