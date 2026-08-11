import math
import random
import time
from typing import Dict, Optional, Set, Tuple

from Data.WorldPosData import WorldPosData


class Projectile:
    def __init__(self, bulletId: int, ownerId: int, shotIndex: int, startingPos: WorldPosData, angle: float,
                 speed: float, damage: int, lifetimeMS: int, size: Optional[int] = None,
                 visualObjectType: Optional[int] = None, multiHit: bool = False, armorPiercing: bool = False,
                 minDamage: Optional[int] = None, maxDamage: Optional[int] = None):
        self.bulletId = bulletId
        self.ownerId = ownerId
        self.shotIndex = shotIndex
        self.startingPos = startingPos.clone()
        self.angle = angle
        self.speed = speed
        # Rolled once at spawn, not re-rolled per target - matches "this
        # shot's power was set when fired," not per-hit. `damage` is only
        # used as a fixed value when the weapon has no min/max range (a
        # flat <Damage> tag - some non-random attacks); most weapons roll
        # between minDamage/maxDamage instead, same as the real server does.
        self.damage = random.randint(minDamage, maxDamage) if minDamage is not None and maxDamage is not None else damage
        self.lifetimeMS = lifetimeMS
        self.size = size
        # Own renderMap.json objectType (separate <Object> from the firer);
        # None falls back to a fixed color.
        self.visualObjectType = visualObjectType
        self.spawnTime = time.time()
        # Piercing shots (multiHit=True) keep flying and can hit more than
        # one enemy over their lifetime; non-multiHit shots stop at the
        # first. hitTargetIds guards against re-reporting the same enemy
        # every frame while still overlapping it - see
        # Renders/GameScreen/hitDetection.py.
        self.multiHit = multiHit
        # Bypasses the target's defense entirely for kill-guess purposes -
        # see Renders/GameScreen/hitDetection.py's damage-after-defense estimate.
        self.armorPiercing = armorPiercing
        self.hitTargetIds: Set[int] = set()

    def isExpired(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return (now - self.spawnTime) * 1000 >= self.lifetimeMS

    def posAt(self, now: Optional[float] = None) -> WorldPosData:
        now = time.time() if now is None else now
        dist = self.speed * (now - self.spawnTime)
        return WorldPosData(
            self.startingPos.x + math.cos(self.angle) * dist,
            self.startingPos.y + math.sin(self.angle) * dist,
        )


class ProjectileStore:
    """Active in-flight bullets, tracked client-side - RotMG never resends a
    projectile's position after the shoot packet, so flight is simulated
    from startingPos/angle/speed until lifetimeMS expires.

    Keyed by (ownerId, bulletId, shotIndex): bulletId alone can collide
    across different multi-shot bursts from the same owner if the fanned
    index were folded into it, so shotIndex is kept separate instead -
    hit-reporting needs the real bulletId sent back unmodified.

    speed/lifetimeMS/size aren't in the shoot packets - spawn() takes them
    as explicit args since XML-definition lookup isn't wired up yet.
    """

    def __init__(self):
        self.projectiles: Dict[Tuple[int, int, int], Projectile] = {}

    def spawn(self, bulletId: int, ownerId: int, startingPos: WorldPosData, angle: float,
              speed: float, damage: int, lifetimeMS: int, size: Optional[int] = None, shotIndex: int = 0,
              visualObjectType: Optional[int] = None, multiHit: bool = False, armorPiercing: bool = False,
              minDamage: Optional[int] = None, maxDamage: Optional[int] = None) -> None:
        key = (ownerId, bulletId, shotIndex)
        self.projectiles[key] = Projectile(
            bulletId, ownerId, shotIndex, startingPos, angle, speed, damage, lifetimeMS, size, visualObjectType,
            multiHit, armorPiercing, minDamage, maxDamage,
        )

    def remove(self, ownerId: int, bulletId: int, shotIndex: int = 0) -> None:
        self.projectiles.pop((ownerId, bulletId, shotIndex), None)

    def prune(self, now: Optional[float] = None) -> None:
        # Enemy-hit detection/reporting lives in Renders/GameScreen/
        # hitDetection.py (called before this each frame) - this only prunes
        # on expiry (or after hitDetection.py removes a non-multiHit shot
        # that already connected).
        now = time.time() if now is None else now
        expired = [key for key, proj in self.projectiles.items() if proj.isExpired(now)]
        for key in expired:
            del self.projectiles[key]
