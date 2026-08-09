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
        # prevPos/prevMoveTime + pos/lastMoveTime bracket the object's last
        # observed movement - renderPos() extrapolates from these the same
        # way Ticker dead-reckons the local player between server ticks.
        # Equal to pos/now until a second NEWTICK position arrives, so a
        # freshly spawned object starts out static rather than guessing a
        # velocity from nothing.
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
        """Smoothed position for rendering between NEWTICK packets -
        interpolates between the last two *observed* positions instead of
        extrapolating past the latest one. Extrapolating (guessing where the
        object is heading and projecting a full tick ahead) was tried first
        and reverted: real movement isn't constant-velocity (AI direction
        changes, stop-start, uneven tick spacing), so the guess rarely
        matched the next NEWTICK's actual position, producing a visible
        snap/correction every tick. Interpolating always draws a point
        between two confirmed positions, so there's nothing to correct -
        the tradeoff is rendering `dt` (the last observed tick interval)
        behind real server state, same idea as other multiplayer games'
        entity-interpolation render delay.
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
    """Owned solely by the renderer (see CLAUDE.local.md's threading architecture) -
    applies UPDATE (object/tile add-remove) and NEWTICK (stat/position deltas) in
    place. Nothing else mutates it.
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
                # A tick delta for an object we never got an UPDATE for - skip it,
                # matching the defensive-skip convention used elsewhere for
                # partial/out-of-order data.
                continue
            obj.updatePos(status.pos, now)
            for stat in status.stats:
                obj.stats[stat.statType] = stat
