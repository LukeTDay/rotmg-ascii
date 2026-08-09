import curses
import math
from typing import Tuple

from Constants import ColorPairs
from Models.Context import Context
from Models.GameState import GameState
from Models.PlayerData import PlayerData
from Models.ProjectileStore import ProjectileStore
from Models.TileManager import VIEW_RADIUS_TILES, buildVisibleTiles
from Networking.Listener import Listener

from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow

BAR_WIDTH = 20
# Roomy enough for "HP  [<20-char bar>] 9999/9999" (~36 chars) plus the
# 2-column gap between the map area and the HUD - see _drawHud's hudCol.
HUD_WIDTH_COLS = 40


def computeScale(stdscr: curses.window) -> Tuple[int, int, int]:
    """Returns (scale, mapAreaRows, mapAreaCols). `scale` is how many
    character cells each world tile is drawn as (nearest-neighbor block
    replication) - the view always shows the same fixed VIEW_RADIUS_TILES
    window of real tiles; a bigger/zoomed-in terminal just makes each tile's
    block bigger, it never shows more world.
    """
    maxY, maxX = stdscr.getmaxyx()
    mapAreaRows = maxY
    mapAreaCols = max(1, maxX - HUD_WIDTH_COLS)
    windowSize = 2 * VIEW_RADIUS_TILES + 1
    scale = max(1, min(mapAreaRows, mapAreaCols) // windowSize)
    return scale, mapAreaRows, mapAreaCols


def _drawMap(pad: curses.window, scale: int, mapAreaRows: int, mapAreaCols: int,
             visibleTiles, playerTileX: int, playerTileY: int) -> None:
    centerRow = mapAreaRows // 2
    centerCol = mapAreaCols // 2
    for (tileX, tileY), cell in visibleTiles.items():
        dx, dy = tileX - playerTileX, tileY - playerTileY
        screenRow0 = centerRow + dy * scale
        screenCol0 = centerCol + dx * scale
        pairNum = ColorPairs.MAP_COLOR_TO_PAIR.get(cell.colorName, ColorPairs.MAP_WHITE)
        attr = curses.color_pair(pairNum)
        for r in range(scale):
            row = screenRow0 + r
            if not (0 <= row < mapAreaRows):
                continue
            colStart = max(0, screenCol0)
            colEnd = min(mapAreaCols, screenCol0 + scale)
            if colEnd <= colStart:
                continue
            try:
                pad.addstr(row, colStart, cell.char * (colEnd - colStart), attr)
            except curses.error:
                # Block writes near the pad's edge are more failure-prone
                # than single-line text - drop the write, not the frame.
                pass


def _drawBar(pad: curses.window, row: int, col: int, label: str, current: int, maximum: int,
             fillPair: int, width: int = BAR_WIDTH) -> None:
    filled = 0 if maximum <= 0 else round(width * max(0, min(current, maximum)) / maximum)
    filled = max(0, min(width, filled))
    try:
        pad.addstr(row, col, f"{label:<4}[", curses.color_pair(ColorPairs.DEFAULT))
        pad.addstr(row, col + 5, "█" * filled, curses.color_pair(fillPair))
        pad.addstr(row, col + 5 + filled, "░" * (width - filled), curses.color_pair(ColorPairs.DEFAULT))
        pad.addstr(row, col + 5 + width, f"] {current}/{maximum}", curses.color_pair(ColorPairs.DEFAULT))
    except curses.error:
        pass


def _drawHud(stdscr: curses.window, pad: curses.window, player: PlayerData, mapAreaCols: int) -> None:
    maxY, _ = stdscr.getmaxyx()
    hudCol = mapAreaCols + 2
    barRows = (0, 2, 4)  # HP, MP, Fame - 2 rows apart
    hudHeight = barRows[-1] + 1
    startRow = max(0, (maxY - hudHeight) // 2)
    _drawBar(pad, startRow + barRows[0], hudCol, "HP", player.hp, player.maxHp, ColorPairs.MAP_RED)
    _drawBar(pad, startRow + barRows[1], hudCol, "MP", player.mp, player.maxMp, ColorPairs.MAP_BLUE)
    try:
        pad.addstr(startRow + barRows[2], hudCol, f"Fame  {player.fame}", curses.color_pair(ColorPairs.MAP_YELLOW))
    except curses.error:
        pass


def drawFrame(stdscr: curses.window, pad: curses.window, state: GameState, player: PlayerData,
              projectiles: ProjectileStore, listener: Listener, ctx: Context) -> None:
    """Draws one frame of the map + HUD onto the already-allocated game-screen
    pad and blits it. Called once per loop iteration from
    gameScreen.py's _connectedLoop, after that iteration's queue-drain/state-
    apply/prune - so the frame always reflects the freshest state.
    """
    if player.pos is None:
        return  # nothing to center on before the first UPDATE arrives

    playerTileX, playerTileY = math.floor(player.pos.x), math.floor(player.pos.y)
    friendsAndGuild = ctx.get("FRIENDSLIST", set()) | ctx.get("GUILDMEMBERS", set())
    visibleTiles = buildVisibleTiles(
        state, projectiles, playerTileX, playerTileY, listener.objectId, friendsAndGuild
    )

    scale, mapAreaRows, mapAreaCols = computeScale(stdscr)

    pad.erase()
    _drawMap(pad, scale, mapAreaRows, mapAreaCols, visibleTiles, playerTileX, playerTileY)
    _drawHud(stdscr, pad, player, mapAreaCols)

    determineRefreshWindow(stdscr, pad, 0)
