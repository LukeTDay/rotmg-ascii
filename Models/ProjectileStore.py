import math
import time
from typing import Dict, Optional, Tuple

from Data.WorldPosData import WorldPosData


class Projectile:
    def __init__(self, bulletId: int, ownerId: int, shotIndex: int, startingPos: WorldPosData, angle: float,
                 speed: float, damage: int, lifetimeMS: int, size: Optional[int] = None,
                 visualObjectType: Optional[int] = None):
        self.bulletId = bulletId
        self.ownerId = ownerId
        self.shotIndex = shotIndex
        self.startingPos = startingPos.clone()
        self.angle = angle
        self.speed = speed
        self.damage = damage
        self.lifetimeMS = lifetimeMS
        self.size = size
        # Own renderMap.json objectType (separate <Object> from the firer);
        # None falls back to a fixed color.
        self.visualObjectType = visualObjectType
        self.spawnTime = time.time()

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
              visualObjectType: Optional[int] = None) -> None:
        key = (ownerId, bulletId, shotIndex)
        self.projectiles[key] = Projectile(
            bulletId, ownerId, shotIndex, startingPos, angle, speed, damage, lifetimeMS, size, visualObjectType
        )

    def remove(self, ownerId: int, bulletId: int, shotIndex: int = 0) -> None:
        self.projectiles.pop((ownerId, bulletId, shotIndex), None)

    def prune(self, now: Optional[float] = None) -> None:
        # TODO: no client-side hit detection - projectiles are only pruned
        # on expiry, never on actually hitting something. Needs GameState
        # threaded in here to test posAt() against enemy positions and send
        # ENEMYHIT/PLAYERHIT/OTHERHIT using this key's ids.
        now = time.time() if now is None else now
        expired = [key for key, proj in self.projectiles.items() if proj.isExpired(now)]
        for key in expired:
            del self.projectiles[key]
