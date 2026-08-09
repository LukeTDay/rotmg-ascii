from typing import Dict, Tuple

from Data.WorldPosData import WorldPosData
from Data.StatData import StatData
from Data.GroundTileData import GroundTileData


class GameObject:
    def __init__(self, objectId: int, objectType: int, pos: WorldPosData, stats: Dict[int, StatData]):
        self.objectId = objectId
        self.objectType = objectType
        self.pos = pos
        self.stats = stats


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
        for status in packet.statuses:
            obj = self.objects.get(status.objectId)
            if obj is None:
                # A tick delta for an object we never got an UPDATE for - skip it,
                # matching the defensive-skip convention used elsewhere for
                # partial/out-of-order data.
                continue
            obj.pos = status.pos
            for stat in status.stats:
                obj.stats[stat.statType] = stat
