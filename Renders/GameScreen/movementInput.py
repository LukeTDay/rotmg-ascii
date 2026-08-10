import curses
import math
import sys
import time
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

# Windows-only: real physical key state via GetAsyncKeyState, instead of
# relying solely on the terminal's own keyboard auto-repeat cadence. Auto-
# repeat alone has two problems this works around: an OS-level initial
# "repeat delay" before a held key starts generating repeat keydown events
# (felt as a pause before movement "catches up" and starts gliding), and the
# inability to reliably detect two keys held down at once (needed for
# diagonal movement, e.g. W+D). GetAsyncKeyState itself has no concept of
# focus though (see the focus-gating comment below), so it's only trusted
# for a short window after a real getch() keystroke, not on every frame
# unconditionally - meaning releasing a key stops movement within that same
# short window rather than instantly, a deliberate trade for correct focus
# gating (see below).
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

    # GetAsyncKeyState reads global physical key state regardless of which
    # window has focus - on its own it would fire from keys typed into any
    # window, including this terminal not being focused at all. Two window-
    # ownership-based focus checks (GetForegroundWindow() vs
    # GetConsoleWindow(); separately, vs this process's own ancestry walked
    # via a Toolhelp32 snapshot) were tried and reverted: both were confirmed
    # unreliable under Windows Terminal's ConPTY hosting, where the
    # foreground window's owning process can be ApplicationFrameHost.exe (a
    # shared system host, unrelated to this process) rather than anything
    # tied to this terminal - this is a documented Windows Terminal
    # limitation, and Microsoft's own guidance is to use virtual-terminal
    # focus sequences instead of GetConsoleWindow()/GetForegroundWindow().
    #
    # Full VT focus reporting (enabling DECSET 1004 and parsing the `ESC [ I`
    # / `ESC [ O` sequences it sends back on stdin) would work but means
    # hand-parsing raw escape bytes out of curses' getch() stream, which has
    # its own ESC-timeout/sequence-recognition quirks. Instead: curses'
    # getch() can only ever return a real keystroke while this console
    # genuinely has OS keyboard focus (that's just how Windows routes input),
    # so a recent real getch() event is used as the focus proxy instead of
    # any window/process introspection. The recency window is sized off the
    # OS's own configured key-repeat delay (SPI_GETKEYBOARDDELAY) rather than
    # a guessed constant: the first physical keydown always arrives via
    # getch() instantly (no repeat-delay applies to it), which arms trust in
    # GetAsyncKeyState for slightly longer than that delay - long enough for
    # the terminal's own auto-repeat events to keep re-arming it before it
    # expires, sustaining smooth polling for as long as a key is genuinely
    # held. No keystrokes at all (unfocused) means it's never armed.
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


def handleMovementInput(pad: curses.window, ticker: Ticker, state: GameState) -> None:
    """Drains every pending keypress this frame (not just one - same "drain
    completely" convention used for the incoming network queue). On Windows,
    the actual movement direction comes from _pollHeldDirection (real
    physical key state, see above) instead of the drained keys themselves -
    the drain still has to happen every frame regardless, just to keep the
    terminal's own input buffer from backing up. Elsewhere, the last
    directional key seen in the drain is used directly, cardinal-only (4-way):
    a raw terminal can't reliably report multiple simultaneous key-down
    states for true diagonal input, only discrete keypress events, and
    RotMG's real free-angle precision isn't meaningful at 1-tile-per-cell
    ASCII resolution anyway.

    Either way this nudges the Ticker's movement target one tile further in
    the resulting direction from wherever it currently tracks the player as
    standing - unless the tile directly ahead is blocked (a wall/unwalkable
    object or a NoWalk ground type, see TileManager.isTileBlocked), in which
    case no new target is set at all and the player just glides to a stop at
    whatever target was already in flight, right at the tile boundary rather
    than through it.

    There's no key-up event in terminal input, so on non-Windows platforms
    "stopping" isn't an explicit action: release the key and the character
    just finishes walking the last commanded tile and stops there. On
    Windows, _pollHeldDirection reflects real-time key state, so releasing a
    key stops movement within its short trust window (see above) instead of
    waiting for the last commanded tile to finish.
    """
    direction: Optional[Tuple[float, float]] = None
    key = pad.getch()
    while key != -1:
        if IS_WINDOWS:
            _noteKeyEventSeen()
        if key in _DIRECTIONS:
            direction = _DIRECTIONS[key]
        key = pad.getch()

    if IS_WINDOWS:
        direction = _pollHeldDirection()

    if direction is None:
        return
    currentPos = ticker.pos
    if currentPos is None:
        return  # no authoritative position yet (before the first UPDATE/GOTO)

    dx, dy = direction
    currentTileX, currentTileY = math.floor(currentPos.x), math.floor(currentPos.y)
    stepX = 1 if dx > 0 else -1 if dx < 0 else 0
    stepY = 1 if dy > 0 else -1 if dy < 0 else 0

    # Diagonal movement is checked per axis, not as one combined corner tile,
    # so a diagonal press that's blocked along just one axis (e.g. hugging a
    # wall to the left while also pressing up) still moves along the other
    # axis instead of refusing the whole move outright - sliding along the
    # wall rather than stopping dead at it.
    blockedX = dx != 0 and isTileBlocked(state, currentTileX + stepX, currentTileY)
    blockedY = dy != 0 and isTileBlocked(state, currentTileX, currentTileY + stepY)
    effectiveDx = 0.0 if blockedX else dx
    effectiveDy = 0.0 if blockedY else dy

    if effectiveDx != 0.0 and effectiveDy != 0.0 and isTileBlocked(state, currentTileX + stepX, currentTileY + stepY):
        # Neither straight-line neighbor is blocked, but the actual diagonal
        # corner tile is (e.g. a free-standing obstacle placed exactly at the
        # corner) - don't let diagonal movement cut through it.
        return
    if effectiveDx == 0.0 and effectiveDy == 0.0:
        return  # every axis of this move is blocked - fully stuck, not sliding anywhere

    ticker.setTarget(WorldPosData(
        currentPos.x + effectiveDx * MOVE_LOOKAHEAD_TILES,
        currentPos.y + effectiveDy * MOVE_LOOKAHEAD_TILES,
    ))
