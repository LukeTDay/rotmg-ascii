import time
from typing import Dict, Optional, Tuple

from Data.WorldPosData import WorldPosData
from Data.StatData import StatData
from Data.GroundTileData import GroundTileData


class GameObject:
    def __init__(self, objectId: int, objectType: int, pos: WorldPosData, stats: Dict[int, StatData]):
        self.objectId = objectId
        self.objectType = objectType
        self.pos = pos
        self.stats = stats
        # Bracket the last observed move for renderPos() to interpolate between.
        # Equal to pos/now until a second NEWTICK arrives, so a fresh object
        # starts static instead of guessing a velocity.
        self.prevPos = pos.clone()
        self.lastMoveTime = time.time()
        self.prevMoveTime = self.lastMoveTime

    def updatePos(self, pos: WorldPosData, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        self.prevPos = self.pos
        self.prevMoveTime = self.lastMoveTime
        self.pos = pos
        self.lastMoveTime = now

    def renderPos(self, now: Optional[float] = None) -> WorldPosData:
        """Smoothed position between NEWTICK packets, interpolated between the
        last two observed positions rather than extrapolated past the latest
        one. Extrapolation was tried and reverted - non-constant-velocity
        movement made it snap/correct every tick. Tradeoff: rendering trails
        real server state by one observed tick interval.
        """
        now = time.time() if now is None else now
        dt = self.lastMoveTime - self.prevMoveTime
        if dt <= 0:
            return self.pos
        targetTime = now - dt
        if targetTime <= self.prevMoveTime:
            return self.prevPos
        if targetTime >= self.lastMoveTime:
            return self.pos
        frac = (targetTime - self.prevMoveTime) / dt
        return WorldPosData(
            self.prevPos.x + (self.pos.x - self.prevPos.x) * frac,
            self.prevPos.y + (self.pos.y - self.prevPos.y) * frac,
        )


class GameState:
    """Owned solely by the renderer. Applies UPDATE (add/remove) and NEWTICK
    (stat/position deltas) in place; nothing else mutates it.
    """

    def __init__(self):
        self.objects: Dict[int, GameObject] = {}
        self.tiles: Dict[Tuple[int, int], GroundTileData] = {}

    def applyUpdate(self, packet) -> None:
        for tile in packet.tiles:
            self.tiles[(tile.x, tile.y)] = tile

        for obj in packet.newObjs:
            self.objects[obj.status.objectId] = GameObject(
                obj.status.objectId,
                obj.objectType,
                obj.status.pos,
                {stat.statType: stat for stat in obj.status.stats},
            )

        for objectId in packet.drops:
            self.objects.pop(objectId, None)

    def applyNewTick(self, packet) -> None:
        now = time.time()
        for status in packet.statuses:
            obj = self.objects.get(status.objectId)
            if obj is None:
                # Delta for an object we never got an UPDATE for - skip it.
                continue
            obj.updatePos(status.pos, now)
            for stat in status.stats:
                obj.stats[stat.statType] = stat
