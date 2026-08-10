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
        # rateOfFire/numProjectiles/arcGapDegrees are weapon-level attack-
        # cadence/fan-out attributes (RealmEye's "Weapon Attributes" wiki),
        # not properties of the projectile's flight - carried here anyway so
        # shootInput.py's outgoing-shot construction can reuse this same
        # lookup instead of a second file. visualObjectType bridges to this
        # projectile's own renderMap.json entry for its real glyph/color.
        self.rateOfFire = rateOfFire
        self.numProjectiles = numProjectiles
        self.arcGapDegrees = arcGapDegrees
        self.visualObjectType = visualObjectType


def projectileMapLoader(path: str = "Resources/projectileMap.json") -> Dict[int, Dict[int, ProjectileDefinition]]:
    """Loads `Resources/projectileMap.json` (written by
    `Scripts/AssetPipeline/writeProjectileMap.py`) into
    {ownerObjectType: {projectileId: ProjectileDefinition}}.

    `ownerObjectType` is a weapon or enemy's static objectType; `projectileId`
    is the slot a live SERVERPLAYERSHOOT/ENEMYSHOOT packet's containerType/
    bulletType references - see `getProjectileDefinition`.
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
    """Which projectile id each shot in a player weapon's own multi-shot fan
    actually uses - **not** all the same id, for weapons with more than one
    `<Projectile>` block. Confirmed against real game data: every tiered bow
    (e.g. Golden Bow) defines two distinct projectiles for its 3-shot volley -
    id 0 "Large Arrow" (the stronger one) and id 1 "Small Arrow" (weaker) -
    and the fan's *center* shot (closest to the aim direction) uses the
    strong one while the flanking side shots use the weak one. this is a
    real, confirmed gameplay mechanic (RotMG's own "true DPS" calculations
    account for it), not a rendering nicety - previously this codebase always
    used id 0 for every shot in the fan, silently wrong for every such
    weapon's side shots (both for the player's own predicted shots and for
    rendering other players'/enemies' bow volleys).

    Since SERVERPLAYERSHOOT carries no per-shot projectile-id field (unlike
    ENEMYSHOOT's `bulletType`), the client has to derive this purely from
    static weapon data - shots are ranked by absolute distance from the fan's
    center angle (ties share a rank, matching the bow's symmetric left/right
    side shots), and ranks map onto the available ids sorted ascending
    (lowest id = closest to center), clamping to the last id once ids run
    out. This exactly reproduces every confirmed 3-shot/2-id tiered bow.
    Rarer patterns (an even shot count with multiple ids, or 3+ distinct ids
    on one weapon) aren't independently confirmed - this formula still
    produces a deterministic, reasonable result for them, just not verified
    against real capture data the way the common case is.
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
