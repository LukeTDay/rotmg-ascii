from typing import Dict, List, Optional
import json


class ProjectileDefinition:
    def __init__(self, objectId: str, speed: float, lifetimeMS: int, damage: int,
                 minDamage: Optional[int], maxDamage: Optional[int], size: Optional[int],
                 multiHit: bool, armorPiercing: bool, passesCover: bool, extras: dict,
                 rateOfFire: float = 1.0, numProjectiles: int = 1, arcGapDegrees: float = 11.25,
                 visualObjectType: Optional[int] = None):
        self.objectId = objectId
        self.speed = speed
        self.lifetimeMS = lifetimeMS
        self.damage = damage
        self.minDamage = minDamage
        self.maxDamage = maxDamage
        self.size = size
        self.multiHit = multiHit
        self.armorPiercing = armorPiercing
        self.passesCover = passesCover
        self.extras = extras
        # rateOfFire/numProjectiles/arcGapDegrees are weapon cadence/fan-out
        # attrs, not projectile-flight properties - carried so shootInput.py
        # can reuse this lookup. visualObjectType bridges to renderMap.json
        # for this projectile's real glyph/color.
        self.rateOfFire = rateOfFire
        self.numProjectiles = numProjectiles
        self.arcGapDegrees = arcGapDegrees
        self.visualObjectType = visualObjectType


def projectileMapLoader(path: str = "Resources/projectileMap.json") -> Dict[int, Dict[int, ProjectileDefinition]]:
    """Loads `Resources/projectileMap.json` into
    {ownerObjectType: {projectileId: ProjectileDefinition}}. `projectileId` is
    the slot a SERVERPLAYERSHOOT/ENEMYSHOOT packet's containerType/bulletType
    references - see `getProjectileDefinition`.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    result: Dict[int, Dict[int, ProjectileDefinition]] = {}
    for ownerStr, projectiles in raw.items():
        owner = int(ownerStr)
        result[owner] = {
            int(idStr): ProjectileDefinition(
                objectId=data["objectId"],
                speed=data["speed"],
                lifetimeMS=data["lifetimeMS"],
                damage=data["damage"],
                minDamage=data.get("minDamage"),
                maxDamage=data.get("maxDamage"),
                size=data.get("size"),
                multiHit=data.get("multiHit", False),
                armorPiercing=data.get("armorPiercing", False),
                passesCover=data.get("passesCover", False),
                extras=data.get("extras", {}),
                rateOfFire=data.get("rateOfFire", 1.0),
                numProjectiles=data.get("numProjectiles", 1),
                arcGapDegrees=data.get("arcGapDegrees", 11.25),
                visualObjectType=data.get("visualObjectType"),
            )
            for idStr, data in projectiles.items()
        }
    return result


def getProjectileDefinition(
    projectileMap: Dict[int, Dict[int, ProjectileDefinition]], ownerObjectType: int, projectileId: int
) -> Optional[ProjectileDefinition]:
    return projectileMap.get(ownerObjectType, {}).get(projectileId)


def resolveShotProjectileIds(
    projectileMap: Dict[int, Dict[int, ProjectileDefinition]], ownerObjectType: int, numProjectiles: int
) -> List[int]:
    """Not every shot in a multi-shot fan uses the same projectile id: tiered
    bows (e.g. Golden Bow) use a stronger id for the center shot and a weaker
    id for flanking shots - a real damage mechanic, not cosmetic.
    SERVERPLAYERSHOOT carries no per-shot id, so shots are ranked by distance
    from the fan's center angle (ties share a rank) and mapped onto the
    available ids sorted ascending (closest = lowest id), clamping past the
    last id. Verified against confirmed 3-shot/2-id bows; other id/shot-count
    combos are unverified but still deterministic.
    """
    available = sorted(projectileMap.get(ownerObjectType, {}).keys())
    if not available:
        return [0] * numProjectiles
    if len(available) == 1 or numProjectiles <= 1:
        return [available[0]] * numProjectiles

    offsets = [i - (numProjectiles - 1) / 2 for i in range(numProjectiles)]
    distances = [round(abs(o), 6) for o in offsets]
    distinctDistances = sorted(set(distances))
    distanceToId = {
        dist: available[min(rank, len(available) - 1)]
        for rank, dist in enumerate(distinctDistances)
    }
    return [distanceToId[dist] for dist in distances]
