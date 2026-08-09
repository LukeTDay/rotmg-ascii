import math
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple, Union

from Constants import ClassIds
from Constants.StatTypes import StatTypes
from Models.GameState import GameObject, GameState
from Models.ProjectileStore import Projectile, ProjectileStore
from Utils.json.objectNameLoader import ObjectRenderInfo, groundRenderInfo, objectRenderInfo

VIEW_RADIUS_TILES = 15  # tunable: number of real world tiles rendered on each side of the player

_PLACEHOLDER_PROJECTILE_CHAR = "*"
_PLACEHOLDER_PROJECTILE_COLOR = "WHITE"


class Tier(Enum):
    SELF = auto()
    ENEMY = auto()
    PROJECTILE = auto()
    WALL = auto()
    OTHER_PLAYER = auto()
    LOOT_BAG = auto()


# Highest-priority tier first - the render hierarchy's exact order.
_TIER_PRIORITY = (Tier.SELF, Tier.ENEMY, Tier.PROJECTILE, Tier.WALL, Tier.OTHER_PLAYER, Tier.LOOT_BAG)


@dataclass(frozen=True)
class RenderCell:
    char: str
    colorName: str


def classifyObject(obj: GameObject, listenerObjectId: int, info: Optional[ObjectRenderInfo],
                    friendsAndGuild: Set[str]) -> Optional[Tier]:
    """Single-pass precedence matching the render hierarchy exactly: self ->
    enemy -> wall -> other-player (friend/guild only) -> loot bag -> excluded.
    Anything that doesn't match one of these tiers (pets, quest NPCs,
    decorative summons, unclassified objects) is deliberately excluded from
    rendering rather than falling through to a lower tier.
    """
    if obj.objectId == listenerObjectId:
        return Tier.SELF
    if info is not None and info.isEnemy:
        return Tier.ENEMY
    if info is not None and info.blocksMovement:
        return Tier.WALL
    if ClassIds.idToClass(obj.objectType) is not None:
        nameStat = obj.stats.get(StatTypes.NAMESTAT)
        if nameStat is not None and nameStat.strStatValue in friendsAndGuild:
            return Tier.OTHER_PLAYER
        return None  # a player-class object that isn't a friend/guildmate: excluded
    if info is not None and info.isLootBag:
        return Tier.LOOT_BAG
    return None


def buildVisibleTiles(state: GameState, projectiles: ProjectileStore, playerTileX: int, playerTileY: int,
                       listenerObjectId: int, friendsAndGuild: Set[str]) -> Dict[Tuple[int, int], RenderCell]:
    """Rebuilt fresh every frame - a pure derived view over GameState/
    ProjectileStore, not an incrementally-synced structure. GameState is
    already the single incrementally-updated source of truth; a second
    mutation-tracked structure on top of it would duplicate that bookkeeping
    (e.g. moving an enemy between tile-buckets on every position update) and
    risk drift bugs. The window is small (about (2*VIEW_RADIUS_TILES+1)^2
    tiles), so a full rebuild every frame is cheap.
    """
    minX, maxX = playerTileX - VIEW_RADIUS_TILES, playerTileX + VIEW_RADIUS_TILES
    minY, maxY = playerTileY - VIEW_RADIUS_TILES, playerTileY + VIEW_RADIUS_TILES

    perTile: Dict[Tier, Dict[Tuple[int, int], List[Union[GameObject, Projectile]]]] = {
        tier: {} for tier in Tier
    }

    for obj in state.objects.values():
        tileX, tileY = math.floor(obj.pos.x), math.floor(obj.pos.y)
        if not (minX <= tileX <= maxX and minY <= tileY <= maxY):
            continue
        info = objectRenderInfo(obj.objectType)
        tier = classifyObject(obj, listenerObjectId, info, friendsAndGuild)
        if tier is None:
            continue
        perTile[tier].setdefault((tileX, tileY), []).append(obj)

    now = time.time()
    for proj in projectiles.projectiles.values():
        pos = proj.posAt(now)
        tileX, tileY = math.floor(pos.x), math.floor(pos.y)
        if not (minX <= tileX <= maxX and minY <= tileY <= maxY):
            continue
        perTile[Tier.PROJECTILE].setdefault((tileX, tileY), []).append(proj)

    visible: Dict[Tuple[int, int], RenderCell] = {}
    for tileX in range(minX, maxX + 1):
        for tileY in range(minY, maxY + 1):
            key = (tileX, tileY)
            cell = _resolveCell(key, perTile, state)
            if cell is not None:
                visible[key] = cell
    return visible


def _resolveCell(key: Tuple[int, int],
                  perTile: Dict[Tier, Dict[Tuple[int, int], List[Union[GameObject, Projectile]]]],
                  state: GameState) -> Optional[RenderCell]:
    for tier in _TIER_PRIORITY:
        occupants = perTile[tier].get(key)
        if not occupants:
            continue
        if tier == Tier.PROJECTILE:
            # Highest-damage projectile currently over this tile wins - no
            # renderMap entry exists for bullets today, so a fixed
            # placeholder glyph/color stands in until per-projectile visuals
            # are added to the asset pipeline.
            max(occupants, key=lambda p: p.damage)
            return RenderCell(char=_PLACEHOLDER_PROJECTILE_CHAR, colorName=_PLACEHOLDER_PROJECTILE_COLOR)
        winnerObj = occupants[0]
        info = objectRenderInfo(winnerObj.objectType)
        if info is None or not info.chars:
            return None
        return RenderCell(char=info.chars[0], colorName=info.color)

    tile = state.tiles.get(key)
    if tile is None:
        return None
    ground = groundRenderInfo(tile.type)
    if ground is None or not ground.chars:
        return None
    return RenderCell(char=ground.chars[0], colorName=ground.color)
