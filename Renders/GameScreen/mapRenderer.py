import curses
import math
import random
import time
from typing import Optional, Tuple

from Constants import ColorPairs
from Models.AoeStore import AoeStore
from Models.Context import Context, required
from Models.GameState import GameState
from Models.MeteorWarningStore import MeteorWarningStore
from Models.PlayerData import PlayerData
from Models.ProjectileStore import ProjectileStore
from Models.TileManager import VIEW_RADIUS_TILES, buildVisibleTiles, getPlayerVisibility, newPerTileIndex
from Networking.Listener import Listener
from Networking.Ticker import Ticker

from Renders.GameScreen.chatPanel import CHAT_PANEL_WIDTH_FRACTION
from Renders.GameScreen.uiPanel import PANEL_WIDTH_FRACTION

# Terminal character cells are ~2x taller than wide; scaleX vs scaleY uses
# this ratio so a world tile renders visually square, not stretched.
CHAR_ASPECT_RATIO = 2.0


MIN_SCALE_Y = 1  # Smallest per-tile size; growing view radius takes priority over this.

# Mirrors gameScreen.FRAME_INTERVAL_SECONDS's ~16.7ms budget - drawFrame alone
# eating the whole frame budget is worth a breakdown in debug.txt.
_SLOW_DRAW_FRAME_THRESHOLD_MS = 16.7


def computeScale(stdscr: curses.window) -> Tuple[int, int, int, int, int, int]:
    """Returns (scaleX, scaleY, mapAreaRows, mapAreaCols, viewRadius, mapStartCol).

    A bigger terminal grows `viewRadius` (more world visible) first, up to
    VIEW_RADIUS_TILES; only once that cap is hit does leftover space go
    toward magnifying each tile's block size instead.
    """
    maxY, maxX = stdscr.getmaxyx()
    mapAreaRows = maxY
    # Matches chatPanel.computeChatLayout's mapStartCol and
    # uiPanel.computePanelLayout's dividerCol formulas exactly, so the map
    # area and both side panels always agree on where their boundaries are.
    leftPanelWidth = max(1, round(maxX * CHAT_PANEL_WIDTH_FRACTION) - 1)
    mapStartCol = leftPanelWidth + 1
    rightDividerCol = maxX - round(maxX * PANEL_WIDTH_FRACTION)
    mapAreaCols = max(1, rightDividerCol - mapStartCol)

    minScaleX = max(1, round(MIN_SCALE_Y * CHAR_ASPECT_RATIO))
    radiusFromRows = max(0, mapAreaRows // MIN_SCALE_Y - 1) // 2
    radiusFromCols = max(0, mapAreaCols // minScaleX - 1) // 2
    viewRadius = max(1, min(VIEW_RADIUS_TILES, radiusFromRows, radiusFromCols))

    windowSize = 2 * viewRadius + 1
    maxScaleYFromRows = mapAreaRows // windowSize
    maxScaleYFromCols = int(mapAreaCols // (windowSize * CHAR_ASPECT_RATIO))
    scaleY = max(1, min(maxScaleYFromRows, maxScaleYFromCols))
    scaleX = max(1, round(scaleY * CHAR_ASPECT_RATIO))
    return scaleX, scaleY, mapAreaRows, mapAreaCols, viewRadius, mapStartCol


def screenToWorld(stdscr: curses.window, ticker: Ticker, screenRow: int, screenCol: int) -> Optional[Tuple[float, float]]:
    """Inverse of _drawMap's tile placement: converts a mouse screen row/col
    (the game pad has no scroll offset) into a world (x, y) position. Returns
    None if outside the map area (including inside either side panel)."""
    if ticker.pos is None:
        return None
    scaleX, scaleY, mapAreaRows, mapAreaCols, _, mapStartCol = computeScale(stdscr)
    relCol = screenCol - mapStartCol
    if not (0 <= screenRow < mapAreaRows and 0 <= relCol < mapAreaCols):
        return None
    playerTileX, playerTileY = math.floor(ticker.pos.x), math.floor(ticker.pos.y)
    worldX = playerTileX + (relCol - mapAreaCols // 2) / scaleX
    worldY = playerTileY + (screenRow - mapAreaRows // 2) / scaleY
    return worldX, worldY


def _drawMap(pad: curses.window, scaleX: int, scaleY: int, mapAreaRows: int, mapAreaCols: int,
             visibleTiles, playerTileX: int, playerTileY: int, mapStartCol: int) -> None:
    centerRow = mapAreaRows // 2
    centerCol = mapAreaCols // 2
    for (tileX, tileY), cell in visibleTiles.items():
        dx, dy = tileX - playerTileX, tileY - playerTileY
        screenRow0 = centerRow + dy * scaleY
        screenCol0 = mapStartCol + centerCol + dx * scaleX
        pairNum = ColorPairs.MAP_COLOR_TO_PAIR.get(cell.colorName, ColorPairs.MAP_WHITE)
        attr = curses.color_pair(pairNum)
        if cell.bold:
            attr |= curses.A_BOLD
        for r in range(scaleY):
            row = screenRow0 + r
            if not (0 <= row < mapAreaRows):
                continue
            colStart = max(mapStartCol, screenCol0)
            colEnd = min(mapStartCol + mapAreaCols, screenCol0 + scaleX)
            if colEnd <= colStart:
                continue
            try:
                pad.addstr(row, colStart, cell.char * (colEnd - colStart), attr)
            except curses.error:
                # Edge writes can fail; drop the write, not the frame.
                pass


def drawFrame(stdscr: curses.window, pad: curses.window, state: GameState, player: PlayerData,
              projectiles: ProjectileStore, aoeStore: AoeStore, meteorWarnings: MeteorWarningStore,
              listener: Listener, ticker: Ticker, ctx: Context) -> None:
    """Draws one frame of the map onto the game-screen pad - does NOT blit it
    (gameScreen.py's _connectedLoop draws the panel frame and inventory
    panel on top of this same pad afterward, then blits once at the end -
    see uiPanel.drawPanelFrame/inventoryPanel.drawBars/drawInventoryGrid).

    Centers on `ticker.pos`, not `player.pos`: `player.pos` only updates on
    a server NEWTICK, so centering on it would redraw the same stale spot
    between ticks. `ticker.pos` is dead-reckoned locally for smooth motion.
    The local player's GameState entry is nudged to match for the same
    reason, so the '@' glyph doesn't drift off-center between ticks.
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
    playerVisibility = getPlayerVisibility(ctx.get("KEYBINDS", {}))
    # Owned by ctx, not recreated per-frame: TILE_CHAR_CACHE remembers each
    # multi-glyph tile's picked variant so it doesn't re-roll every redraw;
    # PER_TILE_INDEX/VISIBLE_TILES_BUFFER are buildVisibleTiles's reusable
    # scratch containers (see its docstring) - cleared and refilled each call
    # instead of reallocated, to cut per-frame GC pressure.
    rng = ctx.setdefault("RNG", random.Random())
    charCache = ctx.setdefault("TILE_CHAR_CACHE", {})
    perTileIndex = ctx.setdefault("PER_TILE_INDEX", newPerTileIndex())
    visibleTilesBuffer = ctx.setdefault("VISIBLE_TILES_BUFFER", {})

    scaleX, scaleY, mapAreaRows, mapAreaCols, viewRadius, mapStartCol = computeScale(stdscr)

    frameStart = time.perf_counter()
    visibleTiles = buildVisibleTiles(
        state, projectiles, aoeStore, meteorWarnings, playerTileX, playerTileY, listener.objectId, friendsList,
        guildMembers, lockedAccounts, rng, charCache, perTileIndex, visibleTilesBuffer, viewRadius, playerVisibility,
    )
    buildMs = (time.perf_counter() - frameStart) * 1000

    eraseStart = time.perf_counter()
    pad.erase()
    eraseMs = (time.perf_counter() - eraseStart) * 1000

    drawStart = time.perf_counter()
    _drawMap(pad, scaleX, scaleY, mapAreaRows, mapAreaCols, visibleTiles, playerTileX, playerTileY, mapStartCol)
    drawMs = (time.perf_counter() - drawStart) * 1000

    totalMs = (time.perf_counter() - frameStart) * 1000
    if totalMs > _SLOW_DRAW_FRAME_THRESHOLD_MS:
        # Only logged over threshold, not every frame - mirrors gameScreen's
        # own "Frame took..." overrun breakdown, one level down.
        required(ctx.get("DEBUGGER"), "DEBUGGER").warning(
            f"drawFrame took {totalMs:.1f}ms (buildVisibleTiles={buildMs:.1f}ms erase={eraseMs:.1f}ms "
            f"drawMap={drawMs:.1f}ms, {len(visibleTiles)} visible tiles)"
        )
