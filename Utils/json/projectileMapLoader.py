from typing import Dict, List, Optional
import json


class SubattackDef:
    """One <Subattack projectileId="N"> a weapon fires - a weapon fires ALL
    of its subattacks, each on its own independent cooldown (own rateOfFire),
    each its own numProjectiles-count fan spread by its own arcGapDegrees of
    its own projectileId. See Scripts/AssetPipeline/parseGameXml.ParsedSubattack."""

    def __init__(self, projectileId: int, numProjectiles: int, arcGapDegrees: float, rateOfFire: float):
        self.projectileId = projectileId
        self.numProjectiles = numProjectiles
        self.arcGapDegrees = arcGapDegrees
        self.rateOfFire = rateOfFire


class OwnerEntry:
    """Everything projectileMap.json stores for one weapon/enemy objectType."""

    def __init__(self, projectiles: Dict[int, "ProjectileDefinition"], subattacks: List[SubattackDef]):
        self.projectiles = projectiles
        self.subattacks = subattacks


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


def projectileMapLoader(path: str = "Resources/projectileMap.json") -> Dict[int, OwnerEntry]:
    """Loads `Resources/projectileMap.json` into {ownerObjectType: OwnerEntry}.
    `projectileId` is the slot a SERVERPLAYERSHOOT/ENEMYSHOOT packet's
    containerType/bulletType references - see `getProjectileDefinition`.
    `subattacks` is the weapon's ordered <Subattack> list - see `getSubattacks`.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    result: Dict[int, OwnerEntry] = {}
    for ownerStr, ownerData in raw.items():
        owner = int(ownerStr)
        projectiles = {
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
            for idStr, data in ownerData.get("projectiles", {}).items()
        }
        subattacks = [
            SubattackDef(
                projectileId=sub["projectileId"],
                numProjectiles=sub["numProjectiles"],
                arcGapDegrees=sub["arcGapDegrees"],
                rateOfFire=sub["rateOfFire"],
            )
            for sub in ownerData.get("subattacks", [])
        ]
        result[owner] = OwnerEntry(projectiles=projectiles, subattacks=subattacks)
    return result


def getProjectileDefinition(
    projectileMap: Dict[int, OwnerEntry], ownerObjectType: int, projectileId: int
) -> Optional[ProjectileDefinition]:
    entry = projectileMap.get(ownerObjectType)
    return entry.projectiles.get(projectileId) if entry is not None else None


def getSubattacks(projectileMap: Dict[int, OwnerEntry], ownerObjectType: int) -> List[SubattackDef]:
    """The weapon's ordered <Subattack> list - a weapon fires ALL of these,
    each independently timed by its own rateOfFire (see SubattackDef).
    Empty for an unknown owner (caller should fall back to a single default)."""
    entry = projectileMap.get(ownerObjectType)
    return entry.subattacks if entry is not None else []


def resolveShotProjectileIds(
    projectileMap: Dict[int, OwnerEntry], ownerObjectType: int, numProjectiles: int
) -> List[int]:
    """Not every shot in a multi-shot fan uses the same projectile id: tiered
    bows (e.g. Golden Bow) use a stronger id for the center shot and a weaker
    id for flanking shots - a real damage mechanic, not cosmetic.
    SERVERPLAYERSHOOT carries no per-shot id, so shots are ranked by distance
    from the fan's center angle (ties share a rank) and mapped onto the
    available ids sorted ascending (closest = lowest id), clamping past the
    last id. Verified against confirmed 3-shot/2-id bows; other id/shot-count
    combos are unverified but still deterministic.

    Used only for the *incoming* SERVERPLAYERSHOOT/ENEMYSHOOT echo path
    (rendering other players'/enemies' shots) - the outgoing path in
    shootInput.py uses each Subattack's own explicit projectileId instead,
    since it already knows which subattack it's firing.
    """
    entry = projectileMap.get(ownerObjectType)
    available = sorted(entry.projectiles.keys()) if entry is not None else []
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
