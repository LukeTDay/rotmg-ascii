from typing import Dict, Optional
import json


class ProjectileDefinition:
    def __init__(self, objectId: str, speed: float, lifetimeMS: int, damage: int,
                 minDamage: Optional[int], maxDamage: Optional[int], size: Optional[int],
                 multiHit: bool, armorPiercing: bool, passesCover: bool, extras: dict):
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
            )
            for idStr, data in projectiles.items()
        }
    return result


def getProjectileDefinition(
    projectileMap: Dict[int, Dict[int, ProjectileDefinition]], ownerObjectType: int, projectileId: int
) -> Optional[ProjectileDefinition]:
    return projectileMap.get(ownerObjectType, {}).get(projectileId)
