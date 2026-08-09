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
from Utils.XML.parseGroundTypes import groundIdToData

VIEW_RADIUS_TILES = 15  # tunable: number of real world tiles rendered on each side of the player

_PLACEHOLDER_PROJECTILE_CHAR = "*"
_PLACEHOLDER_PROJECTILE_COLOR = "WHITE"

_SELF_CHAR = "@"
_SELF_FALLBACK_COLOR = "WHITE"

# Other players render as the same '@' glyph as self, colored by
# relationship rather than by their class's sprite color - guildmates and
# friends should be recognizable as such at a glance. A locked-only account
# (see AccountListPacket) that's neither a guildmate nor a friend gets a
# third, distinct fallback color.
_OTHER_PLAYER_CHAR = "@"
_GUILD_COLOR = "GREEN"
_FRIEND_COLOR = "YELLOW"
_LOCKED_FALLBACK_COLOR = "MAGENTA"

# Ground tiles flagged NoWalk (chasms, deep water, etc. - GroundTypeData.
# noWalk, not renderMap.json's chars/color, which don't distinguish walkable
# from unwalkable floor) render as a wall glyph instead of their normal
# floor glyph, so they read as impassable at a glance instead of looking
# like ordinary floor.
_NOWALK_GROUND_CHAR = "#"
_NOWALK_GROUND_COLOR = "WHITE"


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


def otherPlayerRelationship(obj: GameObject, friendsList: Set[str], guildMembers: Set[str],
                             lockedAccounts: Set[str]) -> Optional[str]:
    """Which relationship (if any) makes this player-class object render at
    all: "GUILD", "FRIEND", or "LOCKED" (an AccountListPacket-locked account
    that's neither), in that priority order if more than one applies. None
    means excluded entirely - not a lower render tier, just not drawn.
    """
    nameStat = obj.stats.get(StatTypes.NAMESTAT)
    name = nameStat.strStatValue if nameStat is not None else None
    if name is not None and name in guildMembers:
        return "GUILD"
    if name is not None and name in friendsList:
        return "FRIEND"
    accountIdStat = obj.stats.get(StatTypes.ACCOUNTIDSTAT)
    accountId = accountIdStat.strStatValue if accountIdStat is not None else None
    if accountId is not None and accountId in lockedAccounts:
        return "LOCKED"
    return None


def classifyObject(obj: GameObject, listenerObjectId: int, info: Optional[ObjectRenderInfo],
                    friendsList: Set[str], guildMembers: Set[str], lockedAccounts: Set[str]) -> Optional[Tier]:
    """Single-pass precedence matching the render hierarchy exactly: self ->
    enemy -> wall -> other-player (friend/guild/locked only) -> loot bag ->
    excluded. Anything that doesn't match one of these tiers (pets, quest
    NPCs, decorative summons, unclassified objects) is deliberately excluded
    from rendering rather than falling through to a lower tier.
    """
    if obj.objectId == listenerObjectId:
        return Tier.SELF
    if info is not None and info.isEnemy:
        return Tier.ENEMY
    if info is not None and info.blocksMovement:
        return Tier.WALL
    if ClassIds.idToClass(obj.objectType) is not None:
        if otherPlayerRelationship(obj, friendsList, guildMembers, lockedAccounts) is not None:
            return Tier.OTHER_PLAYER
        return None  # a player-class object that's not a friend/guildmate/locked account: excluded
    if info is not None and info.isLootBag:
        return Tier.LOOT_BAG
    return None


def isTileBlocked(state: GameState, tileX: int, tileY: int) -> bool:
    """Whether a world tile is impassable - either a wall/unwalkable object
    occupying it (same `blocksMovement` flag the WALL render tier uses), or
    its ground type is flagged NoWalk in the game's own XML (`GroundTypeData.
    noWalk`, distinct from `groundRenderInfo`'s chars/color - that one only
    covers rendering). Used by movement-input collision checks, not just
    rendering; a tile with no known ground data is treated as passable
    (fail-open on missing info, matching this codebase's convention
    elsewhere) rather than blocked.
    """
    for obj in state.objects.values():
        if math.floor(obj.pos.x) != tileX or math.floor(obj.pos.y) != tileY:
            continue
        info = objectRenderInfo(obj.objectType)
        if info is not None and info.blocksMovement:
            return True

    tile = state.tiles.get((tileX, tileY))
    if tile is not None:
        ground = groundIdToData(tile.type)
        if ground is not None and ground.noWalk:
            return True

    return False


def buildVisibleTiles(state: GameState, projectiles: ProjectileStore, playerTileX: int, playerTileY: int,
                       listenerObjectId: int, friendsList: Set[str], guildMembers: Set[str],
                       lockedAccounts: Set[str]) -> Dict[Tuple[int, int], RenderCell]:
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
        tier = classifyObject(obj, listenerObjectId, info, friendsList, guildMembers, lockedAccounts)
        if tier is None:
            continue
        perTile[tier].setdefault((tileX, tileY), []).append(obj)

    now = time.time()
    for proj in projectiles.projectiles.values():
        # A bullet only matters if it's dangerous to us (an enemy's) or is
        # our own - not another player's, friend/guild or otherwise (e.g. a
        # stranger cosmetically shooting their bow in the Nexus, where
        # there's no combat but the shoot packets still go out anyway).
        owner = state.objects.get(proj.ownerId)
        if owner is None:
            continue
        ownerInfo = objectRenderInfo(owner.objectType)
        ownerTier = classifyObject(owner, listenerObjectId, ownerInfo, friendsList, guildMembers, lockedAccounts)
        if ownerTier not in (Tier.SELF, Tier.ENEMY):
            continue
        pos = proj.posAt(now)
        tileX, tileY = math.floor(pos.x), math.floor(pos.y)
        if not (minX <= tileX <= maxX and minY <= tileY <= maxY):
            continue
        perTile[Tier.PROJECTILE].setdefault((tileX, tileY), []).append(proj)

    visible: Dict[Tuple[int, int], RenderCell] = {}
    for tileX in range(minX, maxX + 1):
        for tileY in range(minY, maxY + 1):
            key = (tileX, tileY)
            cell = _resolveCell(key, perTile, state, friendsList, guildMembers, lockedAccounts)
            if cell is not None:
                visible[key] = cell
    return visible


def _resolveCell(key: Tuple[int, int],
                  perTile: Dict[Tier, Dict[Tuple[int, int], List[Union[GameObject, Projectile]]]],
                  state: GameState, friendsList: Set[str], guildMembers: Set[str],
                  lockedAccounts: Set[str]) -> Optional[RenderCell]:
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
        if tier == Tier.SELF:
            # Always a fixed '@' regardless of class sprite - the player is
            # always screen-center, so it needs to read as "you" at a glance.
            info = objectRenderInfo(winnerObj.objectType)
            return RenderCell(char=_SELF_CHAR, colorName=info.color if info is not None else _SELF_FALLBACK_COLOR)
        if tier == Tier.OTHER_PLAYER:
            # Fixed '@' colored by relationship, not by class sprite - a
            # guildmate/friend should be recognizable as such at a glance.
            relationship = otherPlayerRelationship(winnerObj, friendsList, guildMembers, lockedAccounts)
            color = {
                "GUILD": _GUILD_COLOR,
                "FRIEND": _FRIEND_COLOR,
            }.get(relationship, _LOCKED_FALLBACK_COLOR)
            return RenderCell(char=_OTHER_PLAYER_CHAR, colorName=color)
        info = objectRenderInfo(winnerObj.objectType)
        if info is None or not info.chars:
            return None
        return RenderCell(char=info.chars[0], colorName=info.color)

    tile = state.tiles.get(key)
    if tile is None:
        return None
    groundType = groundIdToData(tile.type)
    if groundType is not None and groundType.noWalk:
        return RenderCell(char=_NOWALK_GROUND_CHAR, colorName=_NOWALK_GROUND_COLOR)
    ground = groundRenderInfo(tile.type)
    if ground is None or not ground.chars:
        return None
    return RenderCell(char=ground.chars[0], colorName=ground.color)
