"""
Writes `Resources/projectileMap.json` - a runtime-loadable lookup of every
<Projectile> definition parsed out of the game XML by `parseGameXml.py`,
keyed by the owning weapon/enemy's objectType and then by the projectile's
own `id` (the slot a live SERVERPLAYERSHOOT/ENEMYSHOOT packet references).

Unlike `renderMap.json`, there's no derive/override step here - this is a
straight structural copy of what `parseGameXml.py` already extracted.
Speed/damage/lifetime come directly from the XML, not approximated from
pixel data the way color is, so there's nothing to hand-correct.
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


def _projectileToDict(proj: ParsedProjectile) -> dict:
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
    }


def buildProjectileMap(parsed_objects: dict) -> dict:
    """`parsed_objects` is `parseAll()["objects"]` - {entityId: ParsedEntity}."""
    result: dict[str, dict[str, dict]] = {}
    for entityId, entity in parsed_objects.items():
        if not entity.projectiles:
            continue
        result[str(entityId)] = {str(proj.id): _projectileToDict(proj) for proj in entity.projectiles}
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
