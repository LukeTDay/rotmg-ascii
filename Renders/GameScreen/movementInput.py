import curses
import math
import sys
import time
from typing import Dict, List, Optional, Tuple

from Data.WorldPosData import WorldPosData
from Models.GameState import GameState
from Models.TileManager import buildBlockedTileIndex, isTileBlocked
from Networking.Ticker import Ticker
from Renders.GameScreen.inputRouter import resolveDirection, resolveVkByDirection

# How far ahead each keypress nudges Ticker's target - large enough that
# auto-repeat keeps it ahead of the dead-reckoned position, so holding a key
# glides instead of stutter-stepping.
MOVE_LOOKAHEAD_TILES = 1.0

# Windows-only: real physical key state via GetAsyncKeyState, which sidesteps
# terminal auto-repeat's initial delay and can detect two keys held at once
# (needed for diagonal movement). Has no concept of focus, so it's only
# trusted briefly after a real getch() keystroke - see the focus-gating note
# below.
IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes

    _user32 = ctypes.windll.user32

    # GetAsyncKeyState ignores window focus entirely, so it would fire from
    # any window. Two focus checks (GetForegroundWindow vs GetConsoleWindow;
    # process-ancestry via Toolhelp32) were tried and reverted - both
    # unreliable under Windows Terminal's ConPTY, where the foreground window
    # is owned by the unrelated ApplicationFrameHost.exe. Full VT focus
    # reporting (DECSET 1004) would work but needs hand-parsing escape bytes
    # out of curses' getch() stream. Instead: getch() only ever returns a
    # keystroke while this console has real OS focus, so a recent getch()
    # event is used as a focus proxy. The trust window is sized off both
    # SPI_GETKEYBOARDDELAY and SPI_GETKEYBOARDSPEED (not delay alone - a slow
    # repeat-rate setting can leave a bigger gap between repeats than the
    # delay implies, which was intermittently dropping trust mid-hold).
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

    def _pollHeldDirection(
        vkByDirection: Tuple[Tuple[Tuple[float, float], Tuple[int, ...]], ...]
    ) -> Optional[Tuple[float, float]]:
        if _lastKeyEventTime is None:
            return None
        if time.monotonic() - _lastKeyEventTime > _HOLD_TRUST_WINDOW_SECONDS:
            return None
        dx = dy = 0.0
        for (vx, vy), vks in vkByDirection:
            if any(_user32.GetAsyncKeyState(vk) & 0x8000 for vk in vks):
                dx += vx
                dy += vy
        if dx == 0.0 and dy == 0.0:
            return None
        # Self-refresh: a still-held key keeps trust armed even if curses never
        # delivers another repeat event for it (e.g. auto-repeat got handed to
        # a second key pressed mid-hold, like the autofire toggle).
        _noteKeyEventSeen()
        # Not normalized here - handleMovementInput normalizes after collision, see its comment.
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


def getFrameMouseEvent(keys: List[int]) -> Optional[Tuple[int, int, int]]:
    """The one place per frame curses.getmouse() may be called - every mouse
    consumer (shootInput, panelInput) uses this same pre-fetched result.
    Calls getmouse() once per queued KEY_MOUSE (cheap - not the expensive
    per-event post-processing callers do), preferring one with real click
    bits: a single call used to grab whatever was most recently queued,
    which could be a trailing motion event right after a real click,
    silently dropping it."""
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


def handleMovementInput(
    keys: List[int], ticker: Ticker, state: GameState, keybinds: Dict[str, str]
) -> Optional[Tuple[float, float]]:
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
    direction = resolveDirection(keys, keybinds)

    if IS_WINDOWS:
        direction = _pollHeldDirection(resolveVkByDirection(keybinds))

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

    if effectiveDx != 0.0 and effectiveDy != 0.0:
        # Normalized after collision, not on the raw input - a wall-slid
        # single axis keeps full speed instead of the diagonal's 1/sqrt(2).
        norm = math.sqrt(effectiveDx * effectiveDx + effectiveDy * effectiveDy)
        effectiveDx /= norm
        effectiveDy /= norm

    ticker.setTarget(WorldPosData(
        currentPos.x + effectiveDx * MOVE_LOOKAHEAD_TILES,
        currentPos.y + effectiveDy * MOVE_LOOKAHEAD_TILES,
    ))
    return direction
