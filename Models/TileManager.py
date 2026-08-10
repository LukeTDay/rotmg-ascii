import math
import random
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

VIEW_RADIUS_TILES = 15  # cap on world tiles rendered per side of the player, regardless of terminal
                         # size (see mapRenderer.computeScale) - bounds per-frame rebuild cost

_PROJECTILE_CHAR = "+"
_PROJECTILE_FALLBACK_COLOR = "WHITE"

_SELF_CHAR = "@"
_SELF_FALLBACK_COLOR = "WHITE"

# Other players render as '@' colored by relationship, not class sprite,
# so guild/friend/locked accounts are recognizable at a glance.
_OTHER_PLAYER_CHAR = "@"
_GUILD_COLOR = "GREEN"
_FRIEND_COLOR = "YELLOW"
_LOCKED_FALLBACK_COLOR = "MAGENTA"

# NoWalk ground (GroundTypeData.noWalk, not renderMap's chars/color) renders
# as a wall glyph so it reads as impassable instead of ordinary floor.
_NOWALK_GROUND_CHAR = "#"
_NOWALK_GROUND_COLOR = "WHITE"

# Sink ground (GroundTypeData.sink - water/lava/similar hazards) renders as
# a wave glyph. Checked after NoWalk since some deep-water ids are flagged
# both, and impassability is the more critical signal.
_LIQUID_GROUND_CHAR = "~"
_LIQUID_FALLBACK_COLOR = "CYAN"


class Tier(Enum):
    SELF = auto()
    ENEMY = auto()
    PROJECTILE = auto()
    WALL = auto()
    PORTAL = auto()
    INTERACTIVE_NPC = auto()
    OTHER_PLAYER = auto()
    LOOT_BAG = auto()


# Highest priority first - matches the render hierarchy exactly.
_TIER_PRIORITY = (
    Tier.SELF, Tier.ENEMY, Tier.LOOT_BAG, Tier.PROJECTILE, Tier.WALL, Tier.PORTAL, Tier.INTERACTIVE_NPC,
    Tier.OTHER_PLAYER,
)


@dataclass(frozen=True)
class RenderCell:
    char: str
    colorName: str


def otherPlayerRelationship(obj: GameObject, friendsList: Set[str], guildMembers: Set[str],
                             lockedAccounts: Set[str]) -> Optional[str]:
    """Which relationship makes a player-class object render: GUILD, FRIEND,
    or LOCKED, in that priority order. None means excluded, not a lower tier.
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
    """Single-pass tier precedence matching the render hierarchy: self ->
    enemy -> wall -> portal -> interactive NPC -> other-player (friend/
    guild/locked only) -> loot bag -> excluded. Non-matches are excluded
    entirely, not downgraded to a lower tier.
    """
    if obj.objectId == listenerObjectId:
        return Tier.SELF
    if info is not None and info.isEnemy:
        return Tier.ENEMY
    if info is not None and info.blocksMovement:
        return Tier.WALL
    if info is not None and info.isPortal:
        return Tier.PORTAL
    if info is not None and info.isInteractiveNpc:
        return Tier.INTERACTIVE_NPC
    if ClassIds.idToClass(obj.objectType) is not None:
        if otherPlayerRelationship(obj, friendsList, guildMembers, lockedAccounts) is not None:
            return Tier.OTHER_PLAYER
        return None  # not a friend/guildmate/locked account: excluded
    if info is not None and info.isLootBag:
        return Tier.LOOT_BAG
    return None


BlockedTileIndex = Set[Tuple[int, int]]


def buildBlockedTileIndex(state: GameState) -> BlockedTileIndex:
    """Tile coords occupied by a wall/unwalkable object (`blocksMovement`).
    Built once per movement-input frame so isTileBlocked's per-frame queries
    don't each rescan state.objects from scratch.
    """
    blocked: BlockedTileIndex = set()
    for obj in state.objects.values():
        info = objectRenderInfo(obj.objectType)
        if info is not None and info.blocksMovement:
            blocked.add((math.floor(obj.pos.x), math.floor(obj.pos.y)))
    return blocked


def isTileBlocked(state: GameState, blockedTiles: BlockedTileIndex, tileX: int, tileY: int) -> bool:
    """Whether a tile is impassable: occupied in `blockedTiles`, or its
    ground is flagged NoWalk. Missing ground data fails open (passable).
    """
    if (tileX, tileY) in blockedTiles:
        return True

    tile = state.tiles.get((tileX, tileY))
    if tile is not None:
        ground = groundIdToData(tile.type)
        if ground is not None and ground.noWalk:
            return True

    return False


def _pickChar(chars: List[str], rng: random.Random, charCache: Dict[Tuple[str, int, int, int], str],
              category: str, tileX: int, tileY: int, entityId: int) -> str:
    """Multi-glyph entries pick a random variant once per (category, tile,
    entity) and cache it, so the tile doesn't flicker between variants every
    frame (buildVisibleTiles reruns fully each frame). `charCache`/`rng` are
    caller-owned so they persist across frames instead of resetting.
    """
    if len(chars) == 1:
        return chars[0]
    key = (category, tileX, tileY, entityId)
    choice = charCache.get(key)
    if choice is None:
        choice = rng.choice(chars)
        charCache[key] = choice
    return choice


def buildVisibleTiles(state: GameState, projectiles: ProjectileStore, playerTileX: int, playerTileY: int,
                       listenerObjectId: int, friendsList: Set[str], guildMembers: Set[str],
                       lockedAccounts: Set[str], rng: random.Random,
                       charCache: Dict[Tuple[str, int, int, int], str],
                       viewRadius: int = VIEW_RADIUS_TILES) -> Dict[Tuple[int, int], RenderCell]:
    """Rebuilt fresh every frame from GameState/ProjectileStore rather than
    incrementally synced, to avoid duplicating GameState's own bookkeeping
    and risking drift. Cheap since `viewRadius` keeps the window small.
    """
    minX, maxX = playerTileX - viewRadius, playerTileX + viewRadius
    minY, maxY = playerTileY - viewRadius, playerTileY + viewRadius

    perTile: Dict[Tier, Dict[Tuple[int, int], List[Union[GameObject, Projectile]]]] = {
        tier: {} for tier in Tier
    }

    now = time.time()
    for obj in state.objects.values():
        # Local player's entry is already smoothed to ticker.pos by the
        # caller; only other objects need dead-reckoning.
        pos = obj.pos if obj.objectId == listenerObjectId else obj.renderPos(now)
        tileX, tileY = math.floor(pos.x), math.floor(pos.y)
        if not (minX <= tileX <= maxX and minY <= tileY <= maxY):
            continue
        info = objectRenderInfo(obj.objectType)
        tier = classifyObject(obj, listenerObjectId, info, friendsList, guildMembers, lockedAccounts)
        if tier is None:
            continue
        perTile[tier].setdefault((tileX, tileY), []).append(obj)

    for proj in projectiles.projectiles.values():
        # Only enemy or our own bullets matter - not another player's (e.g.
        # cosmetic Nexus shooting, where the packets go out but there's no combat).
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
            cell = _resolveCell(key, perTile, state, friendsList, guildMembers, lockedAccounts, rng, charCache)
            if cell is not None:
                visible[key] = cell
    return visible


def _resolveCell(key: Tuple[int, int],
                  perTile: Dict[Tier, Dict[Tuple[int, int], List[Union[GameObject, Projectile]]]],
                  state: GameState, friendsList: Set[str], guildMembers: Set[str],
                  lockedAccounts: Set[str], rng: random.Random,
                  charCache: Dict[Tuple[str, int, int, int], str]) -> Optional[RenderCell]:
    for tier in _TIER_PRIORITY:
        occupants = perTile[tier].get(key)
        if not occupants:
            continue
        if tier == Tier.PROJECTILE:
            # Highest-damage projectile on the tile wins. Color resolves via
            # its own renderMap entry (visualObjectType), else a fallback.
            winner = max(occupants, key=lambda p: p.damage)
            info = objectRenderInfo(winner.visualObjectType) if winner.visualObjectType is not None else None
            color = info.color if info is not None else _PROJECTILE_FALLBACK_COLOR
            return RenderCell(char=_PROJECTILE_CHAR, colorName=color)
        winnerObj = occupants[0]
        if tier == Tier.SELF:
            # Fixed '@' regardless of class sprite - always screen-center, reads as "you".
            info = objectRenderInfo(winnerObj.objectType)
            return RenderCell(char=_SELF_CHAR, colorName=info.color if info is not None else _SELF_FALLBACK_COLOR)
        if tier == Tier.OTHER_PLAYER:
            # Fixed '@' colored by relationship, not class sprite.
            relationship = otherPlayerRelationship(winnerObj, friendsList, guildMembers, lockedAccounts)
            color = {
                "GUILD": _GUILD_COLOR,
                "FRIEND": _FRIEND_COLOR,
            }.get(relationship, _LOCKED_FALLBACK_COLOR)
            return RenderCell(char=_OTHER_PLAYER_CHAR, colorName=color)
        info = objectRenderInfo(winnerObj.objectType)
        if info is None or not info.chars:
            return None
        char = _pickChar(info.chars, rng, charCache, "obj", key[0], key[1], winnerObj.objectType)
        return RenderCell(char=char, colorName=info.color)

    tile = state.tiles.get(key)
    if tile is None:
        return None
    groundType = groundIdToData(tile.type)
    if groundType is not None and groundType.noWalk:
        return RenderCell(char=_NOWALK_GROUND_CHAR, colorName=_NOWALK_GROUND_COLOR)
    ground = groundRenderInfo(tile.type)
    if groundType is not None and groundType.sink:
        color = ground.color if ground is not None else _LIQUID_FALLBACK_COLOR
        return RenderCell(char=_LIQUID_GROUND_CHAR, colorName=color)
    if ground is None or not ground.chars:
        return None
    char = _pickChar(ground.chars, rng, charCache, "ground", key[0], key[1], tile.type)
    return RenderCell(char=char, colorName=ground.color)
