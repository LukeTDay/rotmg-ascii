import curses
import math
import sys
import time
from typing import List, Optional, Tuple

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
    # any window/process introspection. The recency window has to comfortably
    # outlast the GAP BETWEEN CONSECUTIVE REPEAT EVENTS for a genuinely-held
    # key (that's what "re-arms trust before it expires" actually depends on
    # once the first keydown has armed it) - sized off two OS settings, not
    # one: SPI_GETKEYBOARDDELAY (time before repeat starts - only matters for
    # the very first press, which arms trust instantly via getch() anyway)
    # and SPI_GETKEYBOARDSPEED (the repeat RATE once repeating - this is the
    # steady-state interval that actually matters for a held key, and a
    # user with a slow repeat-rate setting has a much bigger gap here than
    # the delay alone would suggest). An earlier version of this sized the
    # window off delay alone, which mismatched its own stated intent and
    # left too little margin for slow-repeat-rate users (or any extra
    # delivery jitter, e.g. a burst of mouse-motion KEY_MOUSE events sharing
    # the same input pipeline) - symptom was movement intermittently
    # stopping mid-hold until the key was released and re-pressed.
    _SPI_GETKEYBOARDDELAY = 0x0016
    _SPI_GETKEYBOARDSPEED = 0x000A
    _delayIndex = ctypes.c_int(1)  # Windows default index if the query fails
    _speedIndex = ctypes.c_int(31)  # Windows default (fastest) if the query fails - safest fallback, see below
    _user32.SystemParametersInfoW(_SPI_GETKEYBOARDDELAY, 0, ctypes.byref(_delayIndex), 0)
    _user32.SystemParametersInfoW(_SPI_GETKEYBOARDSPEED, 0, ctypes.byref(_speedIndex), 0)
    # index 0-3 => roughly 250ms-1000ms.
    _delayBasedWindow = ((_delayIndex.value + 1) * 0.25) + 0.15
    # index 0-31 => roughly 2.5-30 repeats/sec (Windows' own documented
    # range); a LOWER speed index means a WIDER gap between repeats, so the
    # fallback above (31, fastest/narrowest gap) is the safe default if the
    # query fails - it errs toward too-short a window, same failure mode the
    # old delay-only code already had, rather than silently trusting forever.
    # 3x margin over the raw interval absorbs jitter (delivery delay from a
    # busy input pipeline, occasional dropped repeat) without materially
    # delaying how fast a genuine key release is detected.
    _repeatIntervalSeconds = 1.0 / (2.5 + (_speedIndex.value / 31.0) * 27.5)
    _speedBasedWindow = (_repeatIntervalSeconds * 3.0) + 0.15
    _HOLD_TRUST_WINDOW_SECONDS = max(_delayBasedWindow, _speedBasedWindow)

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
        # Deliberately NOT normalized here - handleMovementInput normalizes
        # after collision-blocking is applied, not before (see its comment),
        # since one axis of a diagonal press can get blocked by a wall and
        # the surviving single axis needs to move at full speed, not the
        # diagonal's scaled-down 1/sqrt(2).
        return dx, dy


def drainKeys(pad: curses.window) -> List[int]:
    """Drains every pending keypress/input event this frame into a list (not
    just one - same "drain completely" convention used for the incoming
    network queue), so the terminal's own input buffer never backs up.

    Pulled out as its own function so a single frame's drain can be shared
    between handleMovementInput and shootInput.handleShootInput - each
    previously called pad.getch() in its own loop, which meant whichever ran
    first (handleMovementInput) silently ate every key before the other ever
    saw one, since curses' input buffer only yields each keystroke once.
    """
    keys: List[int] = []
    key = pad.getch()
    while key != -1:
        if IS_WINDOWS:
            _noteKeyEventSeen()
        keys.append(key)
        key = pad.getch()
    return keys


def getFrameMouseEvent(keys: List[int]) -> Optional[Tuple[int, int, int]]:
    """The one place per frame curses.getmouse() may be called - shared by
    every per-frame mouse consumer (shootInput.handleShootInput,
    panelInput.handlePanelInput). Every caller needing mouse input must
    consume this same pre-fetched result instead of calling
    curses.getmouse() itself.

    Calls curses.getmouse() once per queued curses.KEY_MOUSE entry in `keys`
    (bounded by however many are actually present - not unbounded, and not
    the expensive per-event work like screenToWorld, just the cheap
    dequeue+bstate check below), not just once total. A single call was
    tried first and caused a real click-loss bug: REPORT_MOUSE_POSITION
    (enabled in main.py) can queue a plain-motion KEY_MOUSE event right
    after a genuine click's own KEY_MOUSE (the hand naturally jitters even
    during a deliberate click), and curses.getmouse() only ever returns the
    single most-recently-queued event - calling it once returned that
    trailing motion event (bstate with no click bits set) instead of the
    click, silently dropping it. Draining every queued event and preferring
    the first one with an actual button bit set fixes that; the original
    perf regression this single-call design was built to avoid (see prior
    git history) was from doing the expensive per-event *post-processing*
    (screenToWorld/computeScale) for every queued motion event, not from
    calling getmouse() itself, which is cheap - so this keeps that cost at
    one call's worth of post-processing per frame, same as before.

    Returns (mouseRow, mouseCol, bstate) or None if no mouse event was
    queued this frame (or every fetch attempt failed).
    """
    mouseEventCount = keys.count(curses.KEY_MOUSE)
    if mouseEventCount == 0:
        return None

    lastEvent: Optional[Tuple[int, int, int]] = None
    for _ in range(mouseEventCount):
        try:
            _, mouseCol, mouseRow, _, bstate = curses.getmouse()
        except curses.error:
            continue
        lastEvent = (mouseRow, mouseCol, bstate)
        if bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED | curses.BUTTON1_CLICKED):
            return lastEvent
    return lastEvent


def handleMovementInput(keys: List[int], ticker: Ticker, state: GameState) -> Optional[Tuple[float, float]]:
    """On Windows, the actual movement direction comes from
    _pollHeldDirection (real physical key state, see above) instead of the
    drained keys themselves - `keys` is only consulted here on non-Windows.
    There, the last directional key seen in `keys` is used directly,
    cardinal-only (4-way): a raw terminal can't reliably report multiple
    simultaneous key-down states for true diagonal input, only discrete
    keypress events, and RotMG's real free-angle precision isn't meaningful
    at 1-tile-per-cell ASCII resolution anyway.

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

    Returns the direction actually resolved this frame (or None) so callers
    (gameScreen.py's shoot-aim fallback) can track the player's last-moved
    facing without re-deriving it themselves.
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
        return None
    if effectiveDx == 0.0 and effectiveDy == 0.0:
        return None  # every axis of this move is blocked - fully stuck, not sliding anywhere

    if effectiveDx != 0.0 and effectiveDy != 0.0:
        # Normalized HERE - after collision-blocking, not on the raw input
        # direction - so a true diagonal (both axes still free) moves at
        # 1/sqrt(2) per axis (same total speed as a cardinal move, not
        # sqrt(2) faster), while a diagonal press that got wall-slid down to
        # a single surviving axis moves at that axis's full speed instead of
        # incorrectly inheriting the diagonal's scaled-down magnitude.
        norm = math.sqrt(effectiveDx * effectiveDx + effectiveDy * effectiveDy)
        effectiveDx /= norm
        effectiveDy /= norm

    ticker.setTarget(WorldPosData(
        currentPos.x + effectiveDx * MOVE_LOOKAHEAD_TILES,
        currentPos.y + effectiveDy * MOVE_LOOKAHEAD_TILES,
    ))
    return direction
