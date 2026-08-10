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
        # The projectile's own renderMap.json objectType (a separate <Object>
        # from the weapon/enemy that fired it, e.g. "Cultist Fire Shot") -
        # None if ProjectileDefinition couldn't resolve one, in which case
        # the map renderer falls back to a fixed color.
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
    """Active in-flight bullets, tracked client-side. RotMG never sends a
    projectile's position again after the shoot packet that spawned it - the
    client is responsible for simulating flight from `startingPos`/`angle`/
    `speed` and expiring each bullet once `lifetimeMS` elapses (see
    CLAUDE.local.md's notes on client-side hit detection).

    Keyed by (ownerId, bulletId, shotIndex) - `bulletId` alone isn't enough:
    a single SERVERPLAYERSHOOT/ENEMYSHOOT multi-shot burst shares one
    server-assigned bulletId across every bullet it fans out, and `bulletId`
    is a small server-side counter, so a later *unrelated* burst from the
    same owner could plausibly be assigned an id that collides with an
    earlier burst's fanned index if that index were folded into the id
    itself (e.g. `bulletId + i`). `shotIndex` (0 for a normal single shot)
    keeps those separate without touching the real id, which matters once
    hit-reporting needs to send that id back unmodified.

    `speed`/`lifetimeMS`/`size` aren't in the shoot packets themselves - they
    come from the projectile's static XML definition (see
    `Scripts/AssetPipeline/parseGameXml.py`'s `ParsedProjectile`), which isn't
    loaded at runtime yet. `spawn()` takes them as explicit arguments rather
    than resolving them itself, so this store doesn't need to know how/where
    that lookup eventually happens.
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
        # TODO: no client-side hit detection exists yet - a projectile is
        # only ever removed here for expiring, never for actually colliding
        # with something. RotMG's real hit resolution is client-driven: the
        # client that owns a projectile is responsible for noticing it
        # overlaps an enemy/player and sending a hit-report packet
        # (ENEMYHIT/PLAYERHIT/OTHERHIT - the server doesn't do this itself),
        # which is also how it gets removed early instead of just expiring.
        # Implementing this needs GameState threaded in here (or into a new
        # caller-side check next to gameScreen.py's existing prune() call)
        # to test each projectile's posAt(now) against nearby enemy
        # positions, using this key's ownerId/bulletId/shotIndex to build the
        # hit packet - see this class's own docstring above.
        now = time.time() if now is None else now
        expired = [key for key, proj in self.projectiles.items() if proj.isExpired(now)]
        for key in expired:
            del self.projectiles[key]
