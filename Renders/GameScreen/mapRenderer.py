import curses
import math
import random
from typing import Optional, Tuple

from Constants import ColorPairs
from Models.Context import Context
from Models.GameState import GameState
from Models.PlayerData import PlayerData
from Models.ProjectileStore import ProjectileStore
from Models.TileManager import VIEW_RADIUS_TILES, buildVisibleTiles
from Networking.Listener import Listener
from Networking.Ticker import Ticker

from Renders.GameScreen.uiPanel import PANEL_WIDTH_FRACTION

# A monospace terminal character cell is roughly this many times taller than
# it is wide (a common approximation - most terminal fonts are close to a
# 1:2 width:height ratio). Without compensating for this, a world tile drawn
# as an NxN block of character cells looks visually taller than it is wide,
# so equal X/Y world distances look uneven on screen. Compensated for by
# using twice as many character columns as rows per tile (scaleX vs scaleY
# below) rather than a single uniform scale.
CHAR_ASPECT_RATIO = 2.0


MIN_SCALE_Y = 1  # smallest per-tile block size - growing the view radius (more world) takes priority over this


def computeScale(stdscr: curses.window) -> Tuple[int, int, int, int, int]:
    """Returns (scaleX, scaleY, mapAreaRows, mapAreaCols, viewRadius). `scaleX`/
    `scaleY` are how many character columns/rows each world tile is drawn as
    (nearest-neighbor block replication, scaleX ~= scaleY * CHAR_ASPECT_RATIO
    so a world-square actually looks square on screen).

    A bigger/zoomed-out terminal (smaller font, so more rows/cols report as
    available) shows more of the world first: `viewRadius` (world tiles
    rendered on each side of the player) grows to fill the available space
    at the smallest per-tile size, capped at VIEW_RADIUS_TILES. Only once
    that cap is reached does any further leftover space go toward
    magnifying each tile's block size instead - the reverse of growing
    scale at a fixed radius, which just drew the same window bigger without
    ever revealing more world.
    """
    maxY, maxX = stdscr.getmaxyx()
    mapAreaRows = maxY
    # Matches uiPanel.computePanelLayout's dividerCol formula exactly, so the
    # map area and the panel always agree on where the boundary column is.
    mapAreaCols = max(1, maxX - round(maxX * PANEL_WIDTH_FRACTION))

    minScaleX = max(1, round(MIN_SCALE_Y * CHAR_ASPECT_RATIO))
    radiusFromRows = max(0, mapAreaRows // MIN_SCALE_Y - 1) // 2
    radiusFromCols = max(0, mapAreaCols // minScaleX - 1) // 2
    viewRadius = max(1, min(VIEW_RADIUS_TILES, radiusFromRows, radiusFromCols))

    windowSize = 2 * viewRadius + 1
    maxScaleYFromRows = mapAreaRows // windowSize
    maxScaleYFromCols = int(mapAreaCols // (windowSize * CHAR_ASPECT_RATIO))
    scaleY = max(1, min(maxScaleYFromRows, maxScaleYFromCols))
    scaleX = max(1, round(scaleY * CHAR_ASPECT_RATIO))
    return scaleX, scaleY, mapAreaRows, mapAreaCols, viewRadius


def screenToWorld(stdscr: curses.window, ticker: Ticker, screenRow: int, screenCol: int) -> Optional[Tuple[float, float]]:
    """Inverse of _drawMap's tile placement: converts a mouse event's screen
    row/col (curses.getmouse()'s y/x - the game pad has no scroll offset, see
    CLAUDE.local.md) into a world (x, y) position. Returns None if the
    position falls outside the map area (e.g. it's over the HUD instead)."""
    if ticker.pos is None:
        return None
    scaleX, scaleY, mapAreaRows, mapAreaCols, _ = computeScale(stdscr)
    if not (0 <= screenRow < mapAreaRows and 0 <= screenCol < mapAreaCols):
        return None
    playerTileX, playerTileY = math.floor(ticker.pos.x), math.floor(ticker.pos.y)
    worldX = playerTileX + (screenCol - mapAreaCols // 2) / scaleX
    worldY = playerTileY + (screenRow - mapAreaRows // 2) / scaleY
    return worldX, worldY


def _drawMap(pad: curses.window, scaleX: int, scaleY: int, mapAreaRows: int, mapAreaCols: int,
             visibleTiles, playerTileX: int, playerTileY: int) -> None:
    centerRow = mapAreaRows // 2
    centerCol = mapAreaCols // 2
    for (tileX, tileY), cell in visibleTiles.items():
        dx, dy = tileX - playerTileX, tileY - playerTileY
        screenRow0 = centerRow + dy * scaleY
        screenCol0 = centerCol + dx * scaleX
        pairNum = ColorPairs.MAP_COLOR_TO_PAIR.get(cell.colorName, ColorPairs.MAP_WHITE)
        attr = curses.color_pair(pairNum)
        for r in range(scaleY):
            row = screenRow0 + r
            if not (0 <= row < mapAreaRows):
                continue
            colStart = max(0, screenCol0)
            colEnd = min(mapAreaCols, screenCol0 + scaleX)
            if colEnd <= colStart:
                continue
            try:
                pad.addstr(row, colStart, cell.char * (colEnd - colStart), attr)
            except curses.error:
                # Block writes near the pad's edge are more failure-prone
                # than single-line text - drop the write, not the frame.
                pass


def drawFrame(stdscr: curses.window, pad: curses.window, state: GameState, player: PlayerData,
              projectiles: ProjectileStore, listener: Listener, ticker: Ticker, ctx: Context) -> None:
    """Draws one frame of the map onto the already-allocated game-screen pad -
    does NOT blit it (gameScreen.py's _connectedLoop draws the panel frame
    and inventory panel on top of this same pad afterward, then blits once
    at the very end - see uiPanel.drawPanelFrame/inventoryPanel.drawBars/
    drawInventoryGrid). Called once per loop iteration from _connectedLoop,
    after that iteration's queue-drain/state-apply/prune - so the frame
    always reflects the freshest state.

    Centers on `ticker.pos`, not `player.pos` - `player.pos` only updates
    when a server NEWTICK arrives, so the render loop would just be
    redrawing the same stale position between ticks no matter how fast it
    runs. `ticker.pos` is dead-reckoned locally on Ticker's own steady clock
    (see Networking/Ticker.py), giving genuinely smooth motion between
    server ticks. The local player's own GameState entry is nudged to match
    for the same reason - otherwise the '@' glyph (placed via that entry's
    tracked position) would visibly drift off-center between ticks even
    though the camera itself is smoothly centered.
    """
    if ticker.pos is None:
        return  # nothing to center on before the first UPDATE/GOTO arrives

    selfObj = state.objects.get(listener.objectId)
    if selfObj is not None:
        selfObj.pos = ticker.pos

    playerTileX, playerTileY = math.floor(ticker.pos.x), math.floor(ticker.pos.y)
    friendsList = ctx.get("FRIENDSLIST", set())
    guildMembers = ctx.get("GUILDMEMBERS", set())
    lockedAccounts = ctx.get("LOCKEDACCOUNTS", set())
    # Both owned by ctx (not recreated per-frame): `RNG`'s state keeps
    # advancing across the whole session instead of restarting every frame,
    # and `TILE_CHAR_CACHE` remembers each multi-glyph tile's already-picked
    # variant so it stays put instead of re-rolling (and visibly flickering
    # between variants) on every redraw - see TileManager._pickChar.
    rng = ctx.setdefault("RNG", random.Random())
    charCache = ctx.setdefault("TILE_CHAR_CACHE", {})

    scaleX, scaleY, mapAreaRows, mapAreaCols, viewRadius = computeScale(stdscr)
    visibleTiles = buildVisibleTiles(
        state, projectiles, playerTileX, playerTileY, listener.objectId, friendsList, guildMembers, lockedAccounts,
        rng, charCache, viewRadius,
    )

    pad.erase()
    _drawMap(pad, scaleX, scaleY, mapAreaRows, mapAreaCols, visibleTiles, playerTileX, playerTileY)
