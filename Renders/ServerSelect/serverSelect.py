from Constants.Screen import Screen

import curses
from typing import Dict, List

from Renders.EnterAccountInfo.enterAccountInfo import centeredX, determineRefreshWindow, drawCenteredBanner, drawTextAt, figletLineCount
from Renders.backgroundTexture import drawBackgroundTexture
from Models.Context import Context, required
from Utils.json.lastServerLoader import loadLastServer, saveLastServer

ROWS_PER_SLOT = 2  # 1 text row + 1 blank spacer row
COLUMN_GAP = 4
BUTTON_GAP = 6

BACK_TO_ACCOUNT = "Return to Account Select"
BACK_TO_CHAR = "Return to Char Select"


def drawServerSelect(stdscr : curses.window, ctx : Context) -> Screen:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Entering serverSelect screen")

    stdscr.erase()
    pad = curses.newpad(1500, 500)

    pad.keypad(True)
    pad.clrtobot()

    servers : Dict[str, str] = required(ctx.get("SERVERS"), "SERVERS")
    serverNames : List[str] = sorted(servers.keys())

    # Button row always has both entries, so nav bounds-checking only ever
    # special-cases an odd-numbered last grid row.
    gridRows : List[List[int]] = [
        list(range(i, min(i + 2, len(serverNames))))
        for i in range(0, len(serverNames), 2)
    ]
    buttonRow = [len(serverNames), len(serverNames) + 1]
    rows : List[List[int]] = gridRows + [buttonRow]

    nameWidth = max((len(name) for name in serverNames), default=0)

    # Fixed regardless of scroll position/selection, so it only needs computing once.
    headerHeight = figletLineCount("Select a Server") + 1

    rowIdx = 0
    colIdx = 0

    # Pre-select whichever server was picked last session, if it still exists.
    lastServer = loadLastServer()
    if lastServer in serverNames:
        flatIndex = serverNames.index(lastServer)
        for r, row in enumerate(gridRows):
            if flatIndex in row:
                rowIdx = r
                colIdx = row.index(flatIndex)
                break

    scrollOffset = 0
    selectionChanged = False

    while True:
        pad.move(0, 0)
        pad.clrtobot()
        drawBackgroundTexture(stdscr, pad, ctx, forceRegen=selectionChanged)

        height, width = stdscr.getmaxyx()
        visibleRows = max(1, (height - headerHeight) // ROWS_PER_SLOT)

        if rowIdx < scrollOffset:
            scrollOffset = rowIdx
        elif rowIdx >= scrollOffset + visibleRows:
            scrollOffset = rowIdx - visibleRows + 1

        shownRowCount = min(visibleRows, len(rows) - scrollOffset)
        totalHeight = headerHeight + shownRowCount * ROWS_PER_SLOT
        y = max(0, (height - totalHeight) // 2)

        y = drawCenteredBanner(stdscr, pad, y, "Select a Server")
        y += 1

        for actualRow in range(scrollOffset, min(scrollOffset + visibleRows, len(rows))):
            rowSelected = actualRow == rowIdx
            if actualRow == len(rows) - 1:
                y = _printButtonRow(stdscr, pad, y, rowSelected, colIdx)
            else:
                y = _printServerRow(stdscr, pad, y, serverNames, rows[actualRow], nameWidth, rowSelected, colIdx)

        determineRefreshWindow(stdscr, pad, y)
        key = pad.getch()

        prevSelection = (rowIdx, colIdx)
        if key == curses.KEY_UP or key == ord('w'):
            rowIdx = max(0, rowIdx - 1)
            colIdx = min(colIdx, len(rows[rowIdx]) - 1)
        elif key == curses.KEY_DOWN or key == ord('s'):
            rowIdx = min(len(rows) - 1, rowIdx + 1)
            colIdx = min(colIdx, len(rows[rowIdx]) - 1)
        elif key == curses.KEY_LEFT or key == ord('a'):
            colIdx = max(0, colIdx - 1)
        elif key == curses.KEY_RIGHT or key == ord('d'):
            colIdx = min(len(rows[rowIdx]) - 1, colIdx + 1)
        selectionChanged = (rowIdx, colIdx) != prevSelection

        if key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            entryIndex = rows[rowIdx][colIdx]
            if entryIndex == len(serverNames):
                return Screen.accountSelect
            elif entryIndex == len(serverNames) + 1:
                return Screen.charSelect
            else:
                name = serverNames[entryIndex]
                ctx["CURR_SERVER"] = servers[name]
                saveLastServer(name)
                return Screen.gameScreen

def _printServerRow(stdscr : curses.window,
                    pad : curses.window,
                    y : int,
                    serverNames : List[str],
                    rowEntries : List[int],
                    nameWidth : int,
                    rowSelected : bool,
                    colIdx : int) -> int:
    # Fixed-width two-column template so every row lines up at the same x
    # instead of re-centering to its own content.
    anchor = f"{'x' * nameWidth}{' ' * COLUMN_GAP}{'x' * nameWidth}"
    x = centeredX(stdscr, anchor)

    leftIndex = rowEntries[0]
    leftAttr = curses.A_REVERSE if rowSelected and colIdx == 0 else curses.A_NORMAL
    drawTextAt(stdscr, pad, y, x, serverNames[leftIndex].ljust(nameWidth), leftAttr)

    if len(rowEntries) > 1:
        rightIndex = rowEntries[1]
        rightAttr = curses.A_REVERSE if rowSelected and colIdx == 1 else curses.A_NORMAL
        drawTextAt(stdscr, pad, y, x + nameWidth + COLUMN_GAP, serverNames[rightIndex], rightAttr)

    return y + ROWS_PER_SLOT

def _printButtonRow(stdscr : curses.window,
                    pad : curses.window,
                    y : int,
                    rowSelected : bool,
                    colIdx : int) -> int:
    anchor = f"{BACK_TO_ACCOUNT}{' ' * BUTTON_GAP}{BACK_TO_CHAR}"
    x = centeredX(stdscr, anchor)

    leftAttr = curses.A_REVERSE if rowSelected and colIdx == 0 else curses.A_NORMAL
    drawTextAt(stdscr, pad, y, x, BACK_TO_ACCOUNT, leftAttr)

    rightAttr = curses.A_REVERSE if rowSelected and colIdx == 1 else curses.A_NORMAL
    drawTextAt(stdscr, pad, y, x + len(BACK_TO_ACCOUNT) + BUTTON_GAP, BACK_TO_CHAR, rightAttr)

    return y + ROWS_PER_SLOT
