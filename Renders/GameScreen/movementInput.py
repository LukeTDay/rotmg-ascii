import curses
import math
import sys
import time
from typing import List, Optional, Tuple

from Data.WorldPosData import WorldPosData
from Models.GameState import GameState
from Models.TileManager import buildBlockedTileIndex, isTileBlocked
from Networking.Ticker import Ticker

# How far ahead each keypress nudges Ticker's target - large enough that
# auto-repeat keeps it ahead of the dead-reckoned position, so holding a key
# glides instead of stutter-stepping.
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

# Windows-only: real physical key state via GetAsyncKeyState, which sidesteps
# terminal auto-repeat's initial delay and can detect two keys held at once
# (needed for diagonal movement). Has no concept of focus, so it's only
# trusted briefly after a real getch() keystroke - see the focus-gating note
# below.
IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes

    _user32 = ctypes.windll.user32
    # Each direction backed by both its arrow key and its WASD key.
    _VK_BY_DIRECTION: Tuple[Tuple[Tuple[float, float], Tuple[int, int]], ...] = (
        ((0.0, -1.0), (0x26, 0x57)),  # up: VK_UP, 'W'
        ((0.0, 1.0), (0x28, 0x53)),   # down: VK_DOWN, 'S'
        ((-1.0, 0.0), (0x25, 0x41)),  # left: VK_LEFT, 'A'
        ((1.0, 0.0), (0x27, 0x44)),   # right: VK_RIGHT, 'D'
    )

    # GetAsyncKeyState ignores window focus entirely, so it would fire from
    # any window. Two focus checks (GetForegroundWindow vs GetConsoleWindow;
    # process-ancestry via Toolhelp32) were tried and reverted - both
    # unreliable under Windows Terminal's ConPTY, where the foreground window
    # is owned by the unrelated ApplicationFrameHost.exe. Full VT focus
    # reporting (DECSET 1004) would work but needs hand-parsing escape bytes
    # out of curses' getch() stream. Instead: getch() only ever returns a
    # keystroke while this console has real OS focus, so a recent getch()
    # event is used as a focus proxy. The trust window is sized off the OS's
    # own key-repeat delay (SPI_GETKEYBOARDDELAY) so terminal auto-repeat
    # keeps re-arming it for as long as a key is genuinely held.
    _SPI_GETKEYBOARDDELAY = 0x0016
    _delayIndex = ctypes.c_int(1)  # Windows default index if the query fails
    _user32.SystemParametersInfoW(_SPI_GETKEYBOARDDELAY, 0, ctypes.byref(_delayIndex), 0)
    # index 0-3 => roughly 250ms-1000ms; +150ms buffer over the raw delay.
    _HOLD_TRUST_WINDOW_SECONDS = ((_delayIndex.value + 1) * 0.25) + 0.15

    _lastKeyEventTime: Optional[float] = None

    def _noteKeyEventSeen() -> None:
        global _lastKeyEventTime
        _lastKeyEventTime = time.monotonic()

    def _pollHeldDirection() -> Optional[Tuple[float, float]]:
        if _lastKeyEventTime is None:
            return None
        if time.monotonic() - _lastKeyEventTime > _HOLD_TRUST_WINDOW_SECONDS:
            return None
        dx = dy = 0.0
        for (vx, vy), vks in _VK_BY_DIRECTION:
            if any(_user32.GetAsyncKeyState(vk) & 0x8000 for vk in vks):
                dx += vx
                dy += vy
        if dx == 0.0 and dy == 0.0:
            return None
        if dx != 0.0 and dy != 0.0:
            norm = math.sqrt(dx * dx + dy * dy)
            dx /= norm
            dy /= norm
        return dx, dy


def drainKeys(pad: curses.window) -> List[int]:
    """Drains every pending keypress this frame into a list, so the terminal's
    input buffer never backs up. Shared between handleMovementInput and
    shootInput.handleShootInput - curses only yields each keystroke once, so
    only one caller can ever drain the pad."""
    keys: List[int] = []
    key = pad.getch()
    while key != -1:
        if IS_WINDOWS:
            _noteKeyEventSeen()
        keys.append(key)
        key = pad.getch()
    return keys


def handleMovementInput(keys: List[int], ticker: Ticker, state: GameState) -> Optional[Tuple[float, float]]:
    """Resolves this frame's direction - real key state via _pollHeldDirection
    on Windows (true diagonals), else the last directional key in `keys`
    (cardinal-only; a terminal can't reliably report simultaneous keys).
    Nudges Ticker's target one tile further unless blocked (TileManager.
    isTileBlocked), in which case no new target is set and the player glides
    to a stop at the tile boundary. No key-up event on non-Windows, so
    stopping just means the last commanded tile finishes and movement halts
    there; Windows stops within _pollHeldDirection's trust window instead.
    Returns the resolved direction (or None) so callers (gameScreen.py's
    shoot-aim fallback) can track last-moved facing.
    """
    direction: Optional[Tuple[float, float]] = None
    for key in keys:
        if key in _DIRECTIONS:
            direction = _DIRECTIONS[key]

    if IS_WINDOWS:
        direction = _pollHeldDirection()

    if direction is None:
        return None
    currentPos = ticker.pos
    if currentPos is None:
        return None  # no authoritative position yet (before the first UPDATE/GOTO)

    dx, dy = direction
    currentTileX, currentTileY = math.floor(currentPos.x), math.floor(currentPos.y)
    stepX = 1 if dx > 0 else -1 if dx < 0 else 0
    stepY = 1 if dy > 0 else -1 if dy < 0 else 0

    # Built once, not once per isTileBlocked call below - avoids rescanning
    # state.objects from scratch up to 3x this frame.
    blockedTiles = buildBlockedTileIndex(state)

    # Checked per axis, not as one corner tile, so a diagonal blocked on just
    # one axis still slides along the other instead of stopping dead.
    blockedX = dx != 0 and isTileBlocked(state, blockedTiles, currentTileX + stepX, currentTileY)
    blockedY = dy != 0 and isTileBlocked(state, blockedTiles, currentTileX, currentTileY + stepY)
    effectiveDx = 0.0 if blockedX else dx
    effectiveDy = 0.0 if blockedY else dy

    if effectiveDx != 0.0 and effectiveDy != 0.0 and isTileBlocked(
        state, blockedTiles, currentTileX + stepX, currentTileY + stepY
    ):
        # Neither straight-line neighbor is blocked, but the corner tile is -
        # don't let diagonal movement cut through it.
        return None
    if effectiveDx == 0.0 and effectiveDy == 0.0:
        return None  # every axis of this move is blocked - fully stuck, not sliding anywhere

    ticker.setTarget(WorldPosData(
        currentPos.x + effectiveDx * MOVE_LOOKAHEAD_TILES,
        currentPos.y + effectiveDy * MOVE_LOOKAHEAD_TILES,
    ))
    return direction
