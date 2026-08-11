import curses
from typing import List, Optional

from Constants.Screen import Screen
from Models.Context import Context, required
from Renders.EnterAccountInfo.enterAccountInfo import (
    centeredX, determineRefreshWindow, drawCenteredBanner, drawCenteredText, drawTextAt, figletLineCount,
)
from Renders.PauseMenu.keybindConfig import drawKeybindConfig
from Renders.backgroundTexture import drawBackgroundTexture

ROWS_PER_SLOT = 2  # 1 text row + 1 blank spacer row
COLUMN_GAP = 4

_GRID: List[List[str]] = [
    ["Character Select", "Account Select", "Server Select"],
    ["Change Keybinds", "Create Character", "Delete Character"],
    ["Resume Game", "Quit to Desktop", "About / Version"],
]

# Sentinel meaning "an action was handled inline (stub message, keybind
# editor, etc) - stay in this menu" - distinct from None, which means
# "resume gameplay" (Resume Game or ESC).
_STAY = object()


def drawPauseMenu(stdscr: curses.window, ctx: Context) -> Optional[Screen]:
    """Blocking nested menu, invoked directly as a function call from
    gameScreen._connectedLoop - not routed through main.py's Screen
    dispatcher, since _connectedLoop has no clean way to pause and resume
    mid-connection (see the plan this implements). Returns None to resume
    gameplay untouched, or a Screen for the caller to tear the connection
    down and leave gameScreen entirely."""
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Entering pause menu")

    pad = curses.newpad(200, 500)
    pad.keypad(True)

    colWidth = max(len(label) for row in _GRID for label in row)
    headerHeight = figletLineCount("Menu") + 1

    rowIdx = 0
    colIdx = 0
    selectionChanged = False

    while True:
        pad.move(0, 0)
        pad.clrtobot()
        drawBackgroundTexture(stdscr, pad, ctx, forceRegen=selectionChanged)

        height, _width = stdscr.getmaxyx()
        totalHeight = headerHeight + len(_GRID) * ROWS_PER_SLOT + 2
        y = max(0, (height - totalHeight) // 2)

        y = drawCenteredBanner(stdscr, pad, y, "Menu")
        y += 1

        for row in range(len(_GRID)):
            y = _printGridRow(stdscr, pad, y, _GRID[row], colWidth, row == rowIdx, colIdx)

        y += 1
        y = drawCenteredText(stdscr, pad, y, "Arrows/WASD to navigate, Enter to select, ESC to resume")
        determineRefreshWindow(stdscr, pad, y)

        key = pad.getch()

        if key == 27:  # ESC - resume gameplay
            return None

        prevSelection = (rowIdx, colIdx)
        if key == curses.KEY_UP or key == ord('w'):
            rowIdx = max(0, rowIdx - 1)
        elif key == curses.KEY_DOWN or key == ord('s'):
            rowIdx = min(len(_GRID) - 1, rowIdx + 1)
        elif key == curses.KEY_LEFT or key == ord('a'):
            colIdx = max(0, colIdx - 1)
        elif key == curses.KEY_RIGHT or key == ord('d'):
            colIdx = min(len(_GRID[rowIdx]) - 1, colIdx + 1)
        selectionChanged = (rowIdx, colIdx) != prevSelection

        if key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            result = _activate(stdscr, pad, ctx, _GRID[rowIdx][colIdx], debugger)
            if result is not _STAY:
                return result


def _printGridRow(stdscr: curses.window, pad: curses.window, y: int, labels: List[str],
                   colWidth: int, rowSelected: bool, colIdx: int) -> int:
    # Fixed-width N-column template so every row lines up at the same x
    # instead of re-centering to its own content - same technique as
    # serverSelect.py's 2-column grid, generalized to N columns.
    anchor = (" " * COLUMN_GAP).join("x" * colWidth for _ in labels)
    x = centeredX(stdscr, anchor)
    for i, label in enumerate(labels):
        attr = curses.A_REVERSE if rowSelected and colIdx == i else curses.A_NORMAL
        drawTextAt(stdscr, pad, y, x, label.ljust(colWidth), attr)
        x += colWidth + COLUMN_GAP
    return y + ROWS_PER_SLOT


def _activate(stdscr: curses.window, pad: curses.window, ctx: Context, label: str, debugger):
    if label == "Character Select":
        return Screen.charSelect
    if label == "Account Select":
        return Screen.accountSelect
    if label == "Server Select":
        return Screen.serverSelect
    if label == "Quit to Desktop":
        return Screen.exit
    if label == "Resume Game":
        return None
    if label == "Change Keybinds":
        drawKeybindConfig(stdscr, ctx)
        return _STAY
    if label == "Create Character":
        return Screen.charCreate
    if label == "Delete Character":
        _showMessage(stdscr, pad, ctx, "Delete Character", ["Not yet implemented."])
        return _STAY
    if label == "About / Version":
        _showAbout(stdscr, pad, ctx)
        return _STAY
    debugger.warning(f"Pause menu: unhandled label {label!r}")
    return _STAY


def _showMessage(stdscr: curses.window, pad: curses.window, ctx: Context, banner: str, lines: List[str]) -> None:
    pad.move(0, 0)
    pad.clrtobot()
    drawBackgroundTexture(stdscr, pad, ctx)
    y = drawCenteredBanner(stdscr, pad, 0, banner)
    y += 1
    for line in lines:
        y = drawCenteredText(stdscr, pad, y, line)
    y += 1
    y = drawCenteredText(stdscr, pad, y, "Press any key to continue")
    determineRefreshWindow(stdscr, pad, y)
    pad.getch()


def _showAbout(stdscr: curses.window, pad: curses.window, ctx: Context) -> None:
    account = ctx.get("account", {})
    lines = [
        f"Build version: {ctx.get('buildVersion', 'unknown')}",
        f"Account: {account.get('alias', 'unknown')}",
        f"Server: {ctx.get('CURR_SERVER', 'unknown')}",
    ]
    _showMessage(stdscr, pad, ctx, "About", lines)
