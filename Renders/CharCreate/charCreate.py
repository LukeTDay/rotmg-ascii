from Constants.Screen import Screen
from Constants.ClassIds import ALL as ALL_CLASSES, CLASS_UNLOCK_REQUIREMENTS, idToClass
from Constants import ColorPairs

from Models.Context import Context, PendingNewChar, required

from Renders.EnterAccountInfo.enterAccountInfo import centeredX, determineRefreshWindow, drawCenteredBanner, drawCenteredText, figletLineCount
from Renders.backgroundTexture import drawBackgroundTexture

import curses
from typing import List, Set

ROWS_PER_SLOT = 2  # 1 text row + 1 blank spacer row
COLUMN_GAP = 3
SEASONAL_STANDARD_GAP = 6


def drawCharCreate(stdscr: curses.window, ctx: Context) -> Screen:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Entering charCreate screen")

    stdscr.erase()
    pad = curses.newpad(1500, 500)
    pad.keypad(True)
    pad.clrtobot()

    charData = required(ctx.get("CHARDATA"), "CHARDATA")
    unlockedClasses = charData.unlockedClasses

    # Two rows of every class, in Constants/ClassIds.ALL's order, plus a
    # third single-entry row for the back button.
    half = (len(ALL_CLASSES) + 1) // 2
    gridRows: List[List[int]] = [ALL_CLASSES[:half], ALL_CLASSES[half:]]
    backRowIdx = len(gridRows)
    nameWidth = max(len(idToClass(c) or "") for c in ALL_CLASSES)

    headerHeight = figletLineCount("Character Creation") + 1

    # Forced here by login.py when the account has zero characters - ESC/Back
    # would otherwise land on an empty charSelect with nothing to do there.
    canLeaveToCharSelect = len(charData.charIds) > 0
    NO_CHARS_WARNING = "You must create a character before returning to Character Select"

    stage = "grid"  # "grid" | "confirm"
    rowIdx = 0
    colIdx = 0
    chosenClassId: int | None = None
    confirmChoice = 0  # 0 = Seasonal, 1 = Standard
    statusMessage = ""
    selectionChanged = False

    while True:
        pad.move(0, 0)
        pad.clrtobot()
        drawBackgroundTexture(stdscr, pad, ctx, forceRegen=selectionChanged)

        height, _ = stdscr.getmaxyx()
        if stage == "grid":
            # Always reserves the status-message line, shown or not, so the grid
            # itself never shifts when a locked-class message pops in/out.
            contentHeight = (backRowIdx + 1) * ROWS_PER_SLOT + 2
        else:
            contentHeight = 5
        y = max(0, (height - headerHeight - 1 - contentHeight) // 2)

        y = drawCenteredBanner(stdscr, pad, y, "Character Creation")
        y += 1

        if stage == "grid":
            for r in range(backRowIdx + 1):
                rowSelected = r == rowIdx
                if r == backRowIdx:
                    y = _printBackRow(stdscr, pad, y, rowSelected)
                else:
                    y = _printClassRow(stdscr, pad, y, gridRows[r], nameWidth, unlockedClasses, rowSelected, colIdx)
            y += 1
            if statusMessage:
                drawCenteredText(stdscr, pad, y, statusMessage, curses.color_pair(ColorPairs.CRUCIBLE) | curses.A_BOLD)
        else:
            className = idToClass(chosenClassId) if chosenClassId is not None else ""
            y = drawCenteredText(stdscr, pad, y, f"Create a {className} character:")
            y += 1
            y = _printSeasonalRow(stdscr, pad, y, confirmChoice)
            y += 1
            y = drawCenteredText(stdscr, pad, y, "Enter to confirm - Esc to go back")

        determineRefreshWindow(stdscr, pad, y)
        key = pad.getch()

        if stage == "grid":
            prevSelection = (rowIdx, colIdx)
            if key == curses.KEY_UP or key == ord('w'):
                rowIdx = max(0, rowIdx - 1)
                colIdx = min(colIdx, _rowLen(gridRows, backRowIdx, rowIdx) - 1)
            elif key == curses.KEY_DOWN or key == ord('s'):
                rowIdx = min(backRowIdx, rowIdx + 1)
                colIdx = min(colIdx, _rowLen(gridRows, backRowIdx, rowIdx) - 1)
            elif key == curses.KEY_LEFT or key == ord('a'):
                colIdx = max(0, colIdx - 1)
            elif key == curses.KEY_RIGHT or key == ord('d'):
                colIdx = min(_rowLen(gridRows, backRowIdx, rowIdx) - 1, colIdx + 1)
            if (rowIdx, colIdx) != prevSelection:
                selectionChanged = True
                statusMessage = ""
            else:
                selectionChanged = False

            if key == 27:
                if canLeaveToCharSelect:
                    return Screen.charSelect
                statusMessage = NO_CHARS_WARNING
            elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
                if rowIdx == backRowIdx:
                    if canLeaveToCharSelect:
                        return Screen.charSelect
                    statusMessage = NO_CHARS_WARNING
                else:
                    classId = gridRows[rowIdx][colIdx]
                    if classId in unlockedClasses:
                        chosenClassId = classId
                        confirmChoice = 0
                        stage = "confirm"
                    else:
                        statusMessage = _lockMessage(classId)
        else:
            selectionChanged = False
            if key == curses.KEY_LEFT or key == ord('a'):
                confirmChoice = 0
            elif key == curses.KEY_RIGHT or key == ord('d'):
                confirmChoice = 1
            elif key == 27 or key in (curses.KEY_BACKSPACE, 127, 8):
                stage = "grid"
                chosenClassId = None
            elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
                assert chosenClassId is not None, "confirm stage should never be reached without a chosen class"
                ctx["PENDING_NEW_CHAR"] = PendingNewChar(classType=chosenClassId, isSeasonal=(confirmChoice == 0))
                return Screen.serverSelect


def _rowLen(gridRows: List[List[int]], backRowIdx: int, rowIdx: int) -> int:
    return 1 if rowIdx == backRowIdx else len(gridRows[rowIdx])


def _lockMessage(classId: int) -> str:
    requirements = CLASS_UNLOCK_REQUIREMENTS.get(classId, [])
    reqText = " and ".join(f"Level {level} {idToClass(precursorId)}" for precursorId, level in requirements)
    return f"{idToClass(classId)} is locked - requires {reqText}"


def _classAttr(pair: int, selected: bool) -> int:
    if selected:
        return curses.color_pair(ColorPairs.SELECTED_VARIANT[pair]) | curses.A_BOLD
    return curses.color_pair(pair)


def _printClassRow(stdscr: curses.window,
                   pad: curses.window,
                   y: int,
                   rowClasses: List[int],
                   nameWidth: int,
                   unlockedClasses: Set[int],
                   rowSelected: bool,
                   colIdx: int) -> int:
    totalWidth = len(rowClasses) * nameWidth + (len(rowClasses) - 1) * COLUMN_GAP
    x = centeredX(stdscr, "x" * totalWidth)

    cursor = x
    for i, classId in enumerate(rowClasses):
        name = (idToClass(classId) or str(classId)).ljust(nameWidth)
        pair = ColorPairs.STANDARD if classId in unlockedClasses else ColorPairs.CRUCIBLE
        attr = _classAttr(pair, rowSelected and i == colIdx)
        pad.addstr(y, cursor, name, attr)
        cursor += nameWidth + COLUMN_GAP

    return y + ROWS_PER_SLOT


def _printBackRow(stdscr: curses.window, pad: curses.window, y: int, rowSelected: bool) -> int:
    attr = curses.A_REVERSE if rowSelected else curses.A_NORMAL
    y = drawCenteredText(stdscr, pad, y, "Back to Character Select", attr)
    return y + (ROWS_PER_SLOT - 1)


def _printSeasonalRow(stdscr: curses.window, pad: curses.window, y: int, confirmChoice: int) -> int:
    seasonalText = "Seasonal"
    standardText = "Standard"
    anchor = f"{seasonalText}{' ' * SEASONAL_STANDARD_GAP}{standardText}"
    x = centeredX(stdscr, anchor)

    pad.addstr(y, x, seasonalText, _classAttr(ColorPairs.SEASONAL, confirmChoice == 0))
    pad.addstr(y, x + len(seasonalText) + SEASONAL_STANDARD_GAP, standardText, _classAttr(ColorPairs.STANDARD, confirmChoice == 1))
    return y + 1
