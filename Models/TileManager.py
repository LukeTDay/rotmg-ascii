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
_STRANGER_COLOR = "CYAN"

# ctx["KEYBINDS"] field controlling which other players classifyObject lets
# through - not a keybind, but stored/persisted alongside them (see
# Utils/json/keybindLoader.py) the same way inputRouter.NEXUS_MODE_FIELD is.
PLAYER_VISIBILITY_FIELD = "playerVisibility"
PLAYER_VISIBILITY_SELF = "self"
PLAYER_VISIBILITY_FRIENDS_GUILD_LOCKED = "friendsGuildLocked"
PLAYER_VISIBILITY_EVERYONE = "everyone"
_PLAYER_VISIBILITY_MODES = (
    PLAYER_VISIBILITY_SELF, PLAYER_VISIBILITY_FRIENDS_GUILD_LOCKED, PLAYER_VISIBILITY_EVERYONE,
)

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


def getPlayerVisibility(keybinds: Dict[str, str]) -> str:
    mode = keybinds.get(PLAYER_VISIBILITY_FIELD, PLAYER_VISIBILITY_FRIENDS_GUILD_LOCKED)
    return mode if mode in _PLAYER_VISIBILITY_MODES else PLAYER_VISIBILITY_FRIENDS_GUILD_LOCKED


def cyclePlayerVisibility(keybinds: Dict[str, str]) -> str:
    """Cycles Self -> Friends/Guild/Locked -> Everyone -> Self, mirroring
    inputRouter.toggleNexusMode's 2-value flip but for 3 values."""
    current = getPlayerVisibility(keybinds)
    nextMode = _PLAYER_VISIBILITY_MODES[(_PLAYER_VISIBILITY_MODES.index(current) + 1) % len(_PLAYER_VISIBILITY_MODES)]
    keybinds[PLAYER_VISIBILITY_FIELD] = nextMode
    return nextMode


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
                    friendsList: Set[str], guildMembers: Set[str], lockedAccounts: Set[str],
                    playerVisibility: str = PLAYER_VISIBILITY_FRIENDS_GUILD_LOCKED) -> Optional[Tier]:
    """Single-pass tier precedence matching the render hierarchy: self ->
    enemy -> wall -> portal -> interactive NPC -> other-player (gated by
    playerVisibility - see PLAYER_VISIBILITY_* above) -> loot bag ->
    excluded. Non-matches are excluded entirely, not downgraded to a lower
    tier.
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
        if playerVisibility == PLAYER_VISIBILITY_SELF:
            return None
        if playerVisibility == PLAYER_VISIBILITY_EVERYONE:
            return Tier.OTHER_PLAYER
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


PerTileIndex = Dict[Tier, Dict[Tuple[int, int], List[Union[GameObject, Projectile]]]]


def newPerTileIndex() -> PerTileIndex:
    """Caller-owned buffer for buildVisibleTiles's `perTile` param - build once,
    reuse every frame (see buildVisibleTiles's docstring for why)."""
    return {tier: {} for tier in Tier}


def buildVisibleTiles(state: GameState, projectiles: ProjectileStore, playerTileX: int, playerTileY: int,
                       listenerObjectId: int, friendsList: Set[str], guildMembers: Set[str],
                       lockedAccounts: Set[str], rng: random.Random,
                       charCache: Dict[Tuple[str, int, int, int], str],
                       perTile: PerTileIndex, visible: Dict[Tuple[int, int], RenderCell],
                       viewRadius: int = VIEW_RADIUS_TILES,
                       playerVisibility: str = PLAYER_VISIBILITY_FRIENDS_GUILD_LOCKED) -> Dict[Tuple[int, int], RenderCell]:
    """Rebuilt fresh every frame from GameState/ProjectileStore rather than
    incrementally synced, to avoid duplicating GameState's own bookkeeping
    and risking drift. Cheap since `viewRadius` keeps the window small.

    `perTile`/`visible` are caller-owned (see newPerTileIndex) and cleared
    in place rather than reallocated - the view window's tile keys shift
    every frame as the player moves, so reusing entries key-for-key isn't
    possible, but reusing the container objects themselves still avoids
    re-allocating 8 dicts + a result dict 60x/sec. The bigger allocation
    source, one RenderCell per visible tile, is deduplicated separately in
    _resolveCell via _internRenderCell instead, since most tiles repeat the
    same handful of floor glyphs.
    """
    minX, maxX = playerTileX - viewRadius, playerTileX + viewRadius
    minY, maxY = playerTileY - viewRadius, playerTileY + viewRadius

    for tierDict in perTile.values():
        tierDict.clear()
    visible.clear()

    now = time.time()
    for obj in state.objects.values():
        # Local player's entry is already smoothed to ticker.pos by the
        # caller; only other objects need dead-reckoning.
        pos = obj.pos if obj.objectId == listenerObjectId else obj.renderPos(now)
        tileX, tileY = math.floor(pos.x), math.floor(pos.y)
        if not (minX <= tileX <= maxX and minY <= tileY <= maxY):
            continue
        info = objectRenderInfo(obj.objectType)
        tier = classifyObject(obj, listenerObjectId, info, friendsList, guildMembers, lockedAccounts, playerVisibility)
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
        ownerTier = classifyObject(
            owner, listenerObjectId, ownerInfo, friendsList, guildMembers, lockedAccounts, playerVisibility,
        )
        if ownerTier not in (Tier.SELF, Tier.ENEMY):
            continue
        pos = proj.posAt(now)
        tileX, tileY = math.floor(pos.x), math.floor(pos.y)
        if not (minX <= tileX <= maxX and minY <= tileY <= maxY):
            continue
        perTile[Tier.PROJECTILE].setdefault((tileX, tileY), []).append(proj)

    for tileX in range(minX, maxX + 1):
        for tileY in range(minY, maxY + 1):
            key = (tileX, tileY)
            cell = _resolveCell(key, perTile, state, friendsList, guildMembers, lockedAccounts, rng, charCache)
            if cell is not None:
                visible[key] = cell
    return visible


_renderCellCache: Dict[Tuple[str, str], RenderCell] = {}


def _internRenderCell(char: str, colorName: str) -> RenderCell:
    """RenderCell is frozen/immutable and its value space is small (bounded by
    renderMap.json's distinct char/color pairs) - interning avoids allocating
    a fresh instance for every one of a frame's ~900 tiles when the
    overwhelming majority repeat the same handful of floor glyphs."""
    key = (char, colorName)
    cell = _renderCellCache.get(key)
    if cell is None:
        cell = RenderCell(char=char, colorName=colorName)
        _renderCellCache[key] = cell
    return cell


def _resolveCell(key: Tuple[int, int],
                  perTile: PerTileIndex,
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
            return _internRenderCell(_PROJECTILE_CHAR, color)
        winnerObj = occupants[0]
        if tier == Tier.SELF:
            # Fixed '@' regardless of class sprite - always screen-center, reads as "you".
            info = objectRenderInfo(winnerObj.objectType)
            return _internRenderCell(_SELF_CHAR, info.color if info is not None else _SELF_FALLBACK_COLOR)
        if tier == Tier.OTHER_PLAYER:
            # Fixed '@' colored by relationship, not class sprite. None
            # (a stranger, only reachable in PLAYER_VISIBILITY_EVERYONE mode)
            # gets its own color rather than falling into the locked default.
            relationship = otherPlayerRelationship(winnerObj, friendsList, guildMembers, lockedAccounts)
            color = {
                "GUILD": _GUILD_COLOR,
                "FRIEND": _FRIEND_COLOR,
                "LOCKED": _LOCKED_FALLBACK_COLOR,
            }.get(relationship, _STRANGER_COLOR)
            return _internRenderCell(_OTHER_PLAYER_CHAR, color)
        info = objectRenderInfo(winnerObj.objectType)
        if info is None or not info.chars:
            return None
        char = _pickChar(info.chars, rng, charCache, "obj", key[0], key[1], winnerObj.objectType)
        return _internRenderCell(char, info.color)

    tile = state.tiles.get(key)
    if tile is None:
        return None
    groundType = groundIdToData(tile.type)
    if groundType is not None and groundType.noWalk:
        return _internRenderCell(_NOWALK_GROUND_CHAR, _NOWALK_GROUND_COLOR)
    ground = groundRenderInfo(tile.type)
    if groundType is not None and groundType.sink:
        color = ground.color if ground is not None else _LIQUID_FALLBACK_COLOR
        return _internRenderCell(_LIQUID_GROUND_CHAR, color)
    if ground is None or not ground.chars:
        return None
    char = _pickChar(ground.chars, rng, charCache, "ground", key[0], key[1], tile.type)
    return _internRenderCell(char, ground.color)
