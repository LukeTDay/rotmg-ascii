import curses
import math
from typing import Optional, Tuple

from Data.WorldPosData import WorldPosData
from Models.GameState import GameState
from Models.TileManager import isTileBlocked
from Networking.Ticker import Ticker

# How far ahead of the current position each directional keypress nudges the
# Ticker's movement target. Small enough to stop promptly once keys stop
# coming in, large enough that terminal auto-repeat (which fires faster than
# the Ticker's own 10Hz tick) always keeps the target out ahead of the
# dead-reckoned position - that's what makes holding a key glide smoothly
# instead of stutter-stepping tile by tile.
MOVE_LOOKAHEAD_TILES = 1.0

_DIRECTIONS = {
    curses.KEY_UP: (0.0, -1.0),
    curses.KEY_DOWN: (0.0, 1.0),
    curses.KEY_LEFT: (-1.0, 0.0),
    curses.KEY_RIGHT: (1.0, 0.0),
    ord("w"): (0.0, -1.0),
    ord("W"): (0.0, -1.0),
    ord("s"): (0.0, 1.0),
    ord("S"): (0.0, 1.0),
    ord("a"): (-1.0, 0.0),
    ord("A"): (-1.0, 0.0),
    ord("d"): (1.0, 0.0),
    ord("D"): (1.0, 0.0),
}


def handleMovementInput(pad: curses.window, ticker: Ticker, state: GameState) -> None:
    """Drains every pending keypress this frame (not just one - same "drain
    completely" convention used for the incoming network queue) and, for the
    last directional key seen, nudges the Ticker's movement target one tile
    further in that direction from wherever it currently tracks the player
    as standing - unless the tile directly ahead is blocked (a wall/
    unwalkable object or a NoWalk ground type, see TileManager.isTileBlocked),
    in which case no new target is set at all and the player just glides to
    a stop at whatever target was already in flight, right at the tile
    boundary rather than through it.

    Cardinal directions only (4-way): RotMG's real movement is free-angle,
    but that precision isn't meaningful at 1-tile-per-cell ASCII resolution,
    and a raw terminal can't reliably report multiple simultaneous key-down
    states for true diagonal input anyway - only discrete keypress events.

    There's no key-up event in terminal input, so "stopping" isn't an
    explicit action: release the key and the character just finishes
    walking the last commanded tile and stops there.
    """
    direction: Optional[Tuple[float, float]] = None
    key = pad.getch()
    while key != -1:
        if key in _DIRECTIONS:
            direction = _DIRECTIONS[key]
        key = pad.getch()

    if direction is None:
        return
    currentPos = ticker.pos
    if currentPos is None:
        return  # no authoritative position yet (before the first UPDATE/GOTO)

    dx, dy = direction
    nextTileX = math.floor(currentPos.x) + int(dx)
    nextTileY = math.floor(currentPos.y) + int(dy)
    if isTileBlocked(state, nextTileX, nextTileY):
        return  # wall/unwalkable tile directly ahead - refuse to move into it

    ticker.setTarget(WorldPosData(
        currentPos.x + dx * MOVE_LOOKAHEAD_TILES,
        currentPos.y + dy * MOVE_LOOKAHEAD_TILES,
    ))
