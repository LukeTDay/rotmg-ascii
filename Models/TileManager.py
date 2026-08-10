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

VIEW_RADIUS_TILES = 15  # tunable cap: the most world tiles ever rendered on each side of the player,
                         # regardless of how much terminal space is available (see mapRenderer.computeScale -
                         # a bigger/zoomed-out terminal shows more world up to this cap, not bigger tiles,
                         # so this bounds the per-frame rebuild cost rather than fixing the window size)

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

# Ground tiles flagged Sink (GroundTypeData.sink - RotMG's real gameplay
# flag for "you sink into this": every water and lava type in the game XML,
# plus a handful of similar liquid hazards like whirlpools/vats/oil slicks -
# confirmed by cross-checking every <Sink/>-flagged ground id) render as a
# wave glyph instead of their normal (renderMap-derived) floor glyph, so
# liquid reads as liquid at a glance. Checked after NoWalk, not before -
# some deep-water ids are flagged both, and "impassable" is the more
# critical signal to preserve there than "this is liquid".
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


# Highest-priority tier first - the render hierarchy's exact order.
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
    enemy -> wall -> portal -> interactive NPC -> other-player (friend/
    guild/locked only) -> loot bag -> excluded. Anything that doesn't match
    one of these tiers (pets, quest NPCs, decorative summons, unclassified
    objects) is deliberately excluded from rendering rather than falling
    through to a lower tier.
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


def _pickChar(chars: List[str], rng: random.Random, charCache: Dict[Tuple[str, int, int, int], str],
              category: str, tileX: int, tileY: int, entityId: int) -> str:
    """Multi-glyph entries (e.g. a floor tile with several texture variants -
    see renderMapOverrides.jsonEXAMPLE) pick one at random the first time a
    given (category, tile, entity) combination is drawn, then keep returning
    that same choice - `buildVisibleTiles` reruns every frame (see below), so
    without caching, a fresh `rng.choice()` every frame would flicker between
    variants instead of the tile settling on one. `charCache` is caller-owned
    (see mapRenderer.drawFrame) so it persists across frames instead of
    resetting; `rng` is caller-owned for the same reason, so its state
    advances across the whole session instead of restarting every call.
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
    """Rebuilt fresh every frame - a pure derived view over GameState/
    ProjectileStore, not an incrementally-synced structure. GameState is
    already the single incrementally-updated source of truth; a second
    mutation-tracked structure on top of it would duplicate that bookkeeping
    (e.g. moving an enemy between tile-buckets on every position update) and
    risk drift bugs. The window is small (`viewRadius` is capped at
    VIEW_RADIUS_TILES by the caller - see mapRenderer.computeScale), so a
    full rebuild every frame is cheap.
    """
    minX, maxX = playerTileX - viewRadius, playerTileX + viewRadius
    minY, maxY = playerTileY - viewRadius, playerTileY + viewRadius

    perTile: Dict[Tier, Dict[Tuple[int, int], List[Union[GameObject, Projectile]]]] = {
        tier: {} for tier in Tier
    }

    now = time.time()
    for obj in state.objects.values():
        # The local player's own entry is already smoothed to ticker.pos by
        # the caller each frame (see mapRenderer.drawFrame) - only other
        # objects need dead-reckoning between NEWTICK packets.
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
