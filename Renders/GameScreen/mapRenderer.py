import curses
import math
import random
from typing import Tuple

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
# The bar itself (BAR_WIDTH) plus the 2-column gap between the map area and
# the HUD - see _drawHud's hudCol - and a little right-side margin.
HUD_WIDTH_COLS = BAR_WIDTH + 4

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


def _drawBar(pad: curses.window, row: int, col: int, label: str, current: int, maximum: int,
             fillPair: int, emptyPair: int, width: int = BAR_WIDTH) -> None:
    """Old-school RPG bar: the label/numbers are centered *inside* the bar
    itself rather than beside it - black text over a solid color background
    where the bar is filled (`fillPair`), the same stat color as plain text
    on the default background where it isn't (`emptyPair`)."""
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
    """Same box look as _drawBar, but always fully "filled" - for a stat like
    fame that has no reliable max to be proportional against. Black text
    (just the number, no label/max) over a solid color background across
    the whole box."""
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
    # nextClassQuestFame is -1 whenever a class has no further quest reward
    # (e.g. already at max legendary rank), so it can't reliably be used as
    # a bar's max - draw fame as a solid box (same look as HP/MP) instead of
    # a proportional fill.
    _drawSolidBar(pad, startRow + barRows[0], hudCol, player.fame, ColorPairs.FILL_YELLOW)
    _drawBar(pad, startRow + barRows[1], hudCol, "HP", player.hp, player.maxHp,
             ColorPairs.FILL_RED, ColorPairs.MAP_RED)
    _drawBar(pad, startRow + barRows[2], hudCol, "MP", player.mp, player.maxMp,
             ColorPairs.FILL_BLUE, ColorPairs.MAP_BLUE)


def drawFrame(stdscr: curses.window, pad: curses.window, state: GameState, player: PlayerData,
              projectiles: ProjectileStore, listener: Listener, ticker: Ticker, ctx: Context) -> None:
    """Draws one frame of the map + HUD onto the already-allocated game-screen
    pad and blits it. Called once per loop iteration from
    gameScreen.py's _connectedLoop, after that iteration's queue-drain/state-
    apply/prune - so the frame always reflects the freshest state.

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
    _drawHud(stdscr, pad, player, mapAreaCols)

    determineRefreshWindow(stdscr, pad, 0)
