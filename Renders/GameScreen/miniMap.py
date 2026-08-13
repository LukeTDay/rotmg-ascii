"""
Minimap drawn into chatPanel's top-left "reserved" box. Sized off the current
map's MAPINFO width/height to exactly fill the box (downsampling a big map,
magnifying a small one); colored per-cell by the most-common discovered
ground tile; '%' where a player or teleportable beacon is present, else '#'.
Clicking a '%' cell hands off to chatPanel's bottom section (see
drawTpOverrideList there) instead of drawing anything itself.
"""

import curses
import math
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from Constants import ClassIds, ColorPairs
from Constants.StatTypes import StatTypes
from Data.GroundTileData import GroundTileData
from Models.Context import Context, MinimapCache, MinimapTpOverride, TpCandidate
from Models.GameState import GameState
from Models.TileManager import _LIQUID_FALLBACK_COLOR, _NOWALK_GROUND_COLOR
from Networking.Ticker import Ticker
import Networking.PacketHelper as PacketHelper
from Utils.json.objectNameLoader import groundRenderInfo, objectRenderInfo
from Utils.XML.parseGroundTypes import groundIdToData

NO_TARGET_CHAR = "#"
TARGET_CHAR = "%"
OWN_TILE_CHAR = "@"
# Used whenever something needs to be drawn on ground whose color isn't
# known yet (the player's own '@' marker, or a '%' teleport target detected
# on ground not yet discovered - players/beacons are tracked as live objects
# independent of whether their exact tile has been individually discovered).
# Plain undiscovered ground with nothing on it is drawn blank instead (see
# drawMiniMap) rather than falling back to this.
UNKNOWN_GROUND_COLOR = "WHITE"

NOT_ALLOWED_MESSAGE = "Teleporting is not allowed on this map"


@dataclass(frozen=True)
class MinimapLayout:
    startRow: int  # screen row of the grid's first row (chat panel's topSection.startRow)
    bucketCols: int  # real tiles per bucket, X - 1 in magnify mode (bucket == exact tile)
    bucketRows: int  # real tiles per bucket, Y - 1 in magnify mode
    scaleX: int  # screen cells per bucket, X - 1 in downsample mode
    scaleY: int  # screen cells per bucket, Y - 1 in downsample mode
    bucketCountX: int  # number of buckets across
    bucketCountY: int  # number of buckets down


def computeMinimapLayout(topStartRow: int, topHeight: int, panelWidth: int,
                          mapWidth: int, mapHeight: int) -> MinimapLayout:
    """Fills the box in whichever direction is needed: downsamples a map
    bigger than the box (the common case - each cell covers bucketCols x
    bucketRows real tiles), magnifies one smaller than the box (e.g. Vault -
    each real tile drawn as a scaleX x scaleY block of cells). A map whose
    dimensions don't divide evenly into the box can leave a few trailing
    cells blank rather than distort the scale - not worth the complexity of
    a perfect-fill algorithm for a cosmetic sliver."""
    gridCols = max(1, panelWidth)
    gridRows = max(1, topHeight)
    mapWidth = max(1, mapWidth)
    mapHeight = max(1, mapHeight)

    if mapWidth <= gridCols and mapHeight <= gridRows:
        scaleX = max(1, gridCols // mapWidth)
        scaleY = max(1, gridRows // mapHeight)
        return MinimapLayout(topStartRow, 1, 1, scaleX, scaleY, mapWidth, mapHeight)

    bucketCols = max(1, math.ceil(mapWidth / gridCols))
    bucketRows = max(1, math.ceil(mapHeight / gridRows))
    bucketCountX = math.ceil(mapWidth / bucketCols)
    bucketCountY = math.ceil(mapHeight / bucketRows)
    return MinimapLayout(topStartRow, bucketCols, bucketRows, 1, 1, bucketCountX, bucketCountY)


def worldToBucket(layout: MinimapLayout, worldX: int, worldY: int) -> Tuple[int, int]:
    # Works uniformly in both modes: magnify mode always has bucketCols/Rows
    # == 1, so this reduces to (worldX, worldY) - the exact tile - with no
    # branching needed.
    return worldX // layout.bucketCols, worldY // layout.bucketRows


def _bucketToScreenCells(layout: MinimapLayout, bx: int, by: int) -> List[Tuple[int, int]]:
    """Screen (row, col) cells, relative to the grid's own (0,0), a bucket
    occupies - a single cell in downsample mode (scaleX/Y == 1)."""
    baseCol, baseRow = bx * layout.scaleX, by * layout.scaleY
    return [(baseRow + dy, baseCol + dx) for dy in range(layout.scaleY) for dx in range(layout.scaleX)]


def resolveMinimapClick(layout: MinimapLayout, mouseRow: int, mouseCol: int) -> Optional[Tuple[int, int]]:
    localRow = mouseRow - layout.startRow
    if localRow < 0 or mouseCol < 0:
        return None
    bx, by = mouseCol // layout.scaleX, localRow // layout.scaleY
    if not (0 <= bx < layout.bucketCountX and 0 <= by < layout.bucketCountY):
        return None
    return bx, by


def overrideBlockStartRow(bottomStartRow: int, bottomHeight: int, candidateCount: int) -> int:
    """Row the header sits on - the header+candidate-list block (1 header row
    + one row per candidate) is vertically centered within the bottom
    section as a whole, so a single candidate sits near-center along with
    its instructions, and the header gets pushed upward as more candidates
    are added rather than the block growing off-center. Shared between
    chatPanel.drawTpOverrideList and handleMinimapInput so draw and
    click-hit-testing always agree on where the block starts."""
    blockHeight = 1 + candidateCount
    return bottomStartRow + max(0, (bottomHeight - blockHeight) // 2)


def overrideCandidateRow(blockStartRow: int, index: int) -> int:
    """Row a given override-list candidate is drawn/clicked at, relative to
    the block's own start row (see overrideBlockStartRow)."""
    return blockStartRow + 1 + index


def _resolveTileColor(groundType: int) -> Optional[str]:
    """Mirrors Models/TileManager._resolveCell's ground color logic (NoWalk/
    sink overrides) so the minimap's colors stay consistent with the main
    map's rendering."""
    data = groundIdToData(groundType)
    if data is not None and data.noWalk:
        return _NOWALK_GROUND_COLOR
    ground = groundRenderInfo(groundType)
    if data is not None and data.sink:
        return ground.color if ground is not None else _LIQUID_FALLBACK_COLOR
    return ground.color if ground is not None else None


def resetCache(ctx: Context) -> None:
    """Dumps and rebuilds MINIMAP_CACHE - call on every MAPINFO (gameScreen.py),
    since a new map/session always starts with an empty GameState.tiles anyway."""
    ctx["MINIMAP_CACHE"] = MinimapCache()


def _rebucket(cache: MinimapCache, layout: MinimapLayout) -> None:
    """Re-derives bucketCounters/bucketColor from tileColor (already-resolved
    colors, no XML lookups) against a new MinimapLayout - only needed when a
    terminal resize changes the bucketing mid-session, not on the hot path."""
    cache.bucketCounters = {}
    cache.bucketColor = {}
    for (x, y), color in cache.tileColor.items():
        bucket = worldToBucket(layout, x, y)
        cache.bucketCounters.setdefault(bucket, Counter())[color] += 1
    for bucket, counter in cache.bucketCounters.items():
        cache.bucketColor[bucket] = counter.most_common(1)[0][0]
    cache.bucketDims = (layout.bucketCols, layout.bucketRows, layout.scaleX, layout.scaleY)


def applyTileUpdates(ctx: Context, layout: MinimapLayout, tiles: List[GroundTileData]) -> None:
    """Feeds one UPDATE packet's tiles list into the incremental per-bucket
    color cache, at the exact point tiles arrive - not by diffing
    GameState.tiles afterwards, which can't distinguish "already-known tile
    re-sent because the player doubled back" from "this tile's ground type
    actually changed" (see MinimapCache's docstring)."""
    cache = ctx.get("MINIMAP_CACHE")
    if cache is None:
        cache = MinimapCache()
        ctx["MINIMAP_CACHE"] = cache

    dims = (layout.bucketCols, layout.bucketRows, layout.scaleX, layout.scaleY)
    if cache.bucketDims != dims:
        if cache.tileColor:
            _rebucket(cache, layout)
        else:
            cache.bucketDims = dims

    for tile in tiles:
        newColor = _resolveTileColor(tile.type)
        if newColor is None:
            continue
        key = (tile.x, tile.y)
        oldColor = cache.tileColor.get(key)
        if oldColor == newColor:
            continue  # same-value re-send (doubling back) - nothing to update

        bucket = worldToBucket(layout, tile.x, tile.y)
        counter = cache.bucketCounters.setdefault(bucket, Counter())
        if oldColor is not None:
            counter[oldColor] -= 1
            if counter[oldColor] <= 0:
                del counter[oldColor]
        counter[newColor] += 1
        cache.tileColor[key] = newColor
        cache.bucketColor[bucket] = counter.most_common(1)[0][0]


def collectTpBuckets(state: GameState, layout: MinimapLayout,
                      selfObjectId: int) -> Dict[Tuple[int, int], List[TpCandidate]]:
    """Fresh every frame (players/beacons in view can change) - buckets every
    live player-class object and every isBeacon-flagged object (real
    teleportable beacons, not the visible "Active/Captured Beacon" markers -
    see the design plan) by world tile. The local player is never its own
    teleport target."""
    result: Dict[Tuple[int, int], List[TpCandidate]] = {}
    for obj in state.objects.values():
        if obj.objectId == selfObjectId:
            continue
        info = objectRenderInfo(obj.objectType)
        isPlayer = ClassIds.idToClass(obj.objectType) is not None
        isBeacon = info is not None and info.isBeacon
        if not isPlayer and not isBeacon:
            continue

        tileX, tileY = math.floor(obj.pos.x), math.floor(obj.pos.y)
        bucket = worldToBucket(layout, tileX, tileY)
        nameStat = obj.stats.get(StatTypes.NAMESTAT)
        name = nameStat.strStatValue if nameStat is not None and nameStat.strStatValue else None
        if name is None:
            name = info.name if info is not None else "Unknown"
        kind = "beacon" if isBeacon else "player"
        result.setdefault(bucket, []).append(TpCandidate(objectId=obj.objectId, name=name, kind=kind))
    return result


def _safeAddCh(pad: curses.window, row: int, col: int, char: str, attr: int) -> None:
    try:
        pad.addstr(row, col, char, attr)
    except curses.error:
        pass  # edge writes can fail - drop the write, not the frame


def drawMiniMap(pad: curses.window, ctx: Context, state: GameState, ticker: Ticker,
                 listenerObjectId: int, layout: MinimapLayout) -> None:
    cache = ctx.get("MINIMAP_CACHE")
    if cache is None:
        cache = MinimapCache()
        ctx["MINIMAP_CACHE"] = cache

    tpBuckets = collectTpBuckets(state, layout, listenerObjectId)

    ownBucket = None
    if ticker.pos is not None:
        ownBucket = worldToBucket(layout, math.floor(ticker.pos.x), math.floor(ticker.pos.y))

    for by in range(layout.bucketCountY):
        for bx in range(layout.bucketCountX):
            bucket = (bx, by)
            color = cache.bucketColor.get(bucket)
            hasTarget = bucket in tpBuckets
            if bucket == ownBucket:
                # Fixed glyph, not a reserved color - every curses color is
                # legitimately used by some real ground tile (checked against
                # renderMap.json), so only the glyph can be guaranteed unique.
                char = OWN_TILE_CHAR
                attr = curses.color_pair(ColorPairs.MAP_COLOR_TO_PAIR[color or UNKNOWN_GROUND_COLOR])
                attr |= curses.A_BOLD
            elif color is None and not hasTarget:
                # Undiscovered ground with nothing on it - draw nothing
                # rather than a colored glyph, so it reads as genuinely empty
                # instead of depending on some color pair happening to render
                # as blank (MAP_BLACK is literally black-on-black, i.e.
                # invisible - relying on that would be fragile).
                char = " "
                attr = curses.color_pair(ColorPairs.DEFAULT)
            elif color is None:
                # A player/beacon is tracked as a live object independent of
                # whether their exact tile has been individually discovered
                # yet - still worth surfacing, so it doesn't just vanish into
                # the blank-undiscovered case above.
                char = TARGET_CHAR
                attr = curses.color_pair(ColorPairs.MAP_COLOR_TO_PAIR[UNKNOWN_GROUND_COLOR])
            else:
                char = TARGET_CHAR if hasTarget else NO_TARGET_CHAR
                attr = curses.color_pair(ColorPairs.MAP_COLOR_TO_PAIR[color])
            for screenRow, screenCol in _bucketToScreenCells(layout, bx, by):
                _safeAddCh(pad, layout.startRow + screenRow, screenCol, char, attr)


def clearOverrideOnEscape(ctx: Context, keys: List[int]) -> bool:
    """ESC should back out of the teleport-target list before anything else
    (pause menu, etc.) reacts to it this frame - call this first and, if it
    returns True, skip the rest of the frame's input handling, mirroring how
    gameScreen.py's own ESC-vs-pause-menu branch already short-circuits."""
    if ctx.get("MINIMAP_TP_OVERRIDE") is None:
        return False
    if 27 not in keys:
        return False
    ctx["MINIMAP_TP_OVERRIDE"] = None
    return True


def handleMinimapInput(ctx: Context, state: GameState, listenerObjectId: int, outgoingQueue,
                        minimapLayout: MinimapLayout, bottomStartRow: int, bottomHeight: int,
                        mouseEvent: Optional[Tuple[int, int, int]]) -> None:
    if mouseEvent is None:
        return
    mouseRow, mouseCol, bstate = mouseEvent
    if not (bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED)):
        return

    override = ctx.get("MINIMAP_TP_OVERRIDE")
    if override is not None and bottomStartRow <= mouseRow < bottomStartRow + bottomHeight:
        if override.error is None and override.candidates:
            blockStart = overrideBlockStartRow(bottomStartRow, bottomHeight, len(override.candidates))
            index = mouseRow - overrideCandidateRow(blockStart, 0)
            if 0 <= index < len(override.candidates):
                packet = PacketHelper.createPacket("TELEPORT")
                packet.objectId = override.candidates[index].objectId
                outgoingQueue.put(packet)
                ctx["MINIMAP_TP_OVERRIDE"] = None
        return

    bucket = resolveMinimapClick(minimapLayout, mouseRow, mouseCol)
    if bucket is None:
        return

    candidates = collectTpBuckets(state, minimapLayout, listenerObjectId).get(bucket, [])
    if not candidates:
        ctx["MINIMAP_TP_OVERRIDE"] = None
        return

    if ctx.get("CURR_MAP_ALLOWS_TELEPORT", False):
        ctx["MINIMAP_TP_OVERRIDE"] = MinimapTpOverride(bucket=bucket, candidates=candidates, error=None)
    else:
        ctx["MINIMAP_TP_OVERRIDE"] = MinimapTpOverride(bucket=bucket, candidates=[], error=NOT_ALLOWED_MESSAGE)
