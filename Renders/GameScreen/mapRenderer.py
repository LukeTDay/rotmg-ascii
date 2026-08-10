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

from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow

BAR_WIDTH = 20
# BAR_WIDTH plus the gap before the HUD (see _drawHud's hudCol) plus margin.
HUD_WIDTH_COLS = BAR_WIDTH + 4

# Terminal character cells are ~2x taller than wide; scaleX vs scaleY uses
# this ratio so a world tile renders visually square, not stretched.
CHAR_ASPECT_RATIO = 2.0


MIN_SCALE_Y = 1  # Smallest per-tile size; growing view radius takes priority over this.


def computeScale(stdscr: curses.window) -> Tuple[int, int, int, int, int]:
    """Returns (scaleX, scaleY, mapAreaRows, mapAreaCols, viewRadius).

    A bigger terminal grows `viewRadius` (more world visible) first, up to
    VIEW_RADIUS_TILES; only once that cap is hit does leftover space go
    toward magnifying each tile's block size instead.
    """
    maxY, maxX = stdscr.getmaxyx()
    mapAreaRows = maxY
    mapAreaCols = max(1, maxX - HUD_WIDTH_COLS)

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
    """Inverse of _drawMap's tile placement: converts a mouse screen row/col
    (the game pad has no scroll offset) into a world (x, y) position. Returns
    None if outside the map area."""
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
                # Edge writes can fail; drop the write, not the frame.
                pass


def _drawBar(pad: curses.window, row: int, col: int, label: str, current: int, maximum: int,
             fillPair: int, emptyPair: int, width: int = BAR_WIDTH) -> None:
    """RPG-style bar with label/numbers centered inside it: `fillPair` (black
    on color) for the filled portion, `emptyPair` for the rest."""
    filled = 0 if maximum <= 0 else round(width * max(0, min(current, maximum)) / maximum)
    filled = max(0, min(width, filled))
    text = f"{label} {current}/{maximum}"[:width].center(width)
    try:
        if filled > 0:
            pad.addstr(row, col, text[:filled], curses.color_pair(fillPair))
        if filled < width:
            pad.addstr(row, col + filled, text[filled:], curses.color_pair(emptyPair))
    except curses.error:
        pass


def _drawSolidBar(pad: curses.window, row: int, col: int, value: int,
                   fillPair: int, width: int = BAR_WIDTH) -> None:
    """Same look as _drawBar but always fully filled, for a stat (fame) with
    no reliable max to be proportional against."""
    text = str(value)[:width].center(width)
    try:
        pad.addstr(row, col, text, curses.color_pair(fillPair))
    except curses.error:
        pass


def _drawHud(stdscr: curses.window, pad: curses.window, player: PlayerData, mapAreaCols: int) -> None:
    maxY, _ = stdscr.getmaxyx()
    hudCol = mapAreaCols + 2
    barRows = (0, 2, 4)  # Fame, HP, MP - 2 rows apart
    hudHeight = barRows[-1] + 1
    startRow = max(0, (maxY - hudHeight) // 2)
    # nextClassQuestFame is -1 when a class has no further quest reward, so
    # fame can't be a proportional bar - draw it as a solid box instead.
    _drawSolidBar(pad, startRow + barRows[0], hudCol, player.fame, ColorPairs.FILL_YELLOW)
    _drawBar(pad, startRow + barRows[1], hudCol, "HP", player.hp, player.maxHp,
             ColorPairs.FILL_RED, ColorPairs.MAP_RED)
    _drawBar(pad, startRow + barRows[2], hudCol, "MP", player.mp, player.maxMp,
             ColorPairs.FILL_BLUE, ColorPairs.MAP_BLUE)


def drawFrame(stdscr: curses.window, pad: curses.window, state: GameState, player: PlayerData,
              projectiles: ProjectileStore, listener: Listener, ticker: Ticker, ctx: Context) -> None:
    """Draws one frame of the map + HUD onto the game-screen pad and blits it.

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
    # Owned by ctx, not recreated per-frame: TILE_CHAR_CACHE remembers each
    # multi-glyph tile's picked variant so it doesn't re-roll every redraw.
    rng = ctx.setdefault("RNG", random.Random())
    charCache = ctx.setdefault("TILE_CHAR_CACHE", {})

    scaleX, scaleY, mapAreaRows, mapAreaCols, viewRadius = computeScale(stdscr)
    visibleTiles = buildVisibleTiles(
        state, projectiles, playerTileX, playerTileY, listener.objectId, friendsList, guildMembers, lockedAccounts,
        rng, charCache, viewRadius,
    )

    pad.erase()
    _drawMap(pad, scaleX, scaleY, mapAreaRows, mapAreaCols, visibleTiles, playerTileX, playerTileY)
    _drawHud(stdscr, pad, player, mapAreaCols)

    determineRefreshWindow(stdscr, pad, 0)
