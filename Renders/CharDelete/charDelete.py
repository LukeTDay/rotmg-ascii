from Constants.Screen import Screen
from Constants import ApiPoints, ColorPairs

from Models.Context import Context, required

from Renders.CharSelect.charSelect import printCharSlot
from Renders.EnterAccountInfo.enterAccountInfo import centeredX, determineRefreshWindow, drawCenteredBanner, drawCenteredText, figletLineCount
from Renders.backgroundTexture import drawBackgroundTexture

import curses
import requests
from typing import Tuple

ROWS_PER_SLOT = 4  # matches charSelect.py's printCharSlot/printBackSlot height contract
YES_NO_GAP = 6


def drawCharDelete(stdscr: curses.window, ctx: Context) -> Screen:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Entering charDelete screen")

    stdscr.erase()
    pad = curses.newpad(1500, 500)
    pad.keypad(True)
    pad.clrtobot()

    # Same list object charSelect.py mutates - removing an entry here updates
    # ctx["CHARLIST"] directly, no separate sync step needed.
    loadedChars = required(ctx.get("CHARLIST"), "CHARLIST")
    loadedChars.sort(key=lambda char: char.currentFame, reverse=True)

    headerHeight = figletLineCount("Delete A Character") + 1

    stage = "list"  # "list" | "confirm"
    selected = 0
    scrollOffset = 0
    confirmChoice = 1  # 0 = Yes, 1 = No - starts on No
    statusMessage = ""
    selectionChanged = False

    while True:
        pad.move(0, 0)
        pad.clrtobot()
        drawBackgroundTexture(stdscr, pad, ctx, forceRegen=selectionChanged)

        height, _width = stdscr.getmaxyx()
        entryCount = len(loadedChars) + 1  # + "Back to Character Select"

        if stage == "list":
            visibleRows = max(1, (height - headerHeight) // ROWS_PER_SLOT)
            if selected < scrollOffset:
                scrollOffset = selected
            elif selected >= scrollOffset + visibleRows:
                scrollOffset = selected - visibleRows + 1
            shownCount = min(visibleRows, entryCount - scrollOffset)
            contentHeight = shownCount * ROWS_PER_SLOT + (2 if statusMessage else 0)
        else:
            contentHeight = 1 + 1 + ROWS_PER_SLOT + 1 + 1 + (2 if statusMessage else 0)

        y = max(0, (height - headerHeight - contentHeight) // 2)
        y = drawCenteredBanner(stdscr, pad, y, "Delete A Character")
        y += 1

        if stage == "list":
            for actualIndex in range(scrollOffset, min(scrollOffset + visibleRows, entryCount)):
                attr = curses.A_REVERSE if actualIndex == selected else curses.A_NORMAL
                if actualIndex < len(loadedChars):
                    y = printCharSlot(stdscr, pad, y, loadedChars[actualIndex], attr)
                else:
                    y = _printBackSlot(stdscr, pad, y, attr)
            if statusMessage:
                y += 1
                y = drawCenteredText(stdscr, pad, y, statusMessage, curses.color_pair(ColorPairs.CRUCIBLE) | curses.A_BOLD)
        else:
            charToConfirm = loadedChars[selected]
            y = drawCenteredText(stdscr, pad, y, "Are you sure you want to delete?")
            y += 1
            y = printCharSlot(stdscr, pad, y, charToConfirm, curses.A_NORMAL)
            y += 1
            y = _printYesNoRow(stdscr, pad, y, confirmChoice)
            if statusMessage:
                y += 1
                y = drawCenteredText(stdscr, pad, y, statusMessage, curses.color_pair(ColorPairs.CRUCIBLE) | curses.A_BOLD)

        determineRefreshWindow(stdscr, pad, y)
        key = pad.getch()

        if stage == "list":
            prevSelected = selected
            if key == curses.KEY_UP or key == ord('w'):
                selected = max(0, selected - 1)
            elif key == curses.KEY_DOWN or key == ord('s'):
                selected = min(entryCount - 1, selected + 1)
            selectionChanged = selected != prevSelected
            if selectionChanged:
                statusMessage = ""

            if key == 27:
                return Screen.charSelect
            elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
                if selected < len(loadedChars):
                    stage = "confirm"
                    confirmChoice = 1
                    statusMessage = ""
                else:
                    return Screen.charSelect
        else:
            selectionChanged = False
            if key == curses.KEY_LEFT or key == ord('a'):
                confirmChoice = 0
            elif key == curses.KEY_RIGHT or key == ord('d'):
                confirmChoice = 1
            elif key == 27 or key in (curses.KEY_BACKSPACE, 127, 8):
                stage = "list"
                statusMessage = ""
            elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
                if confirmChoice == 1:  # No - back to the list, same character still highlighted
                    stage = "list"
                    statusMessage = ""
                else:  # Yes
                    charToDelete = loadedChars[selected]
                    pendingY = drawCenteredText(stdscr, pad, y + 1, "Deleting character...")
                    determineRefreshWindow(stdscr, pad, pendingY)

                    success, errorText = _deleteCharacter(required(ctx.get("accessToken"), "accessToken"), charToDelete.charID)
                    if success:
                        debugger.info(f"Deleted character {charToDelete.charID}")
                        loadedChars.remove(charToDelete)
                        charData = ctx.get("CHARDATA")
                        if charData is not None and charToDelete.charID in charData.charIds:
                            charData.charIds.remove(charToDelete.charID)
                        if ctx.get("CURR_CHAR_ID") == charToDelete.charID:
                            ctx.pop("CURR_CHAR_ID", None)
                        selected = min(selected, max(0, len(loadedChars) - 1))
                        statusMessage = ""
                    else:
                        debugger.warning(f"Character delete failed: {errorText}")
                        statusMessage = f"Delete failed: {errorText}"
                    stage = "list"


def _printBackSlot(stdscr: curses.window, pad: curses.window, y: int, attr: int) -> int:
    # Same total height as printCharSlot so scroll math treats every entry uniformly.
    y = drawCenteredText(stdscr, pad, y, "Back to Character Select", attr)
    return y + 3


def _classAttr(pair: int, selected: bool) -> int:
    if selected:
        return curses.color_pair(ColorPairs.SELECTED_VARIANT[pair]) | curses.A_BOLD
    return curses.color_pair(pair)


def _printYesNoRow(stdscr: curses.window, pad: curses.window, y: int, confirmChoice: int) -> int:
    yesText = "Yes"
    noText = "No"
    anchor = f"{yesText}{' ' * YES_NO_GAP}{noText}"
    x = centeredX(stdscr, anchor)

    pad.addstr(y, x, yesText, _classAttr(ColorPairs.CRUCIBLE, confirmChoice == 0))
    pad.addstr(y, x + len(yesText) + YES_NO_GAP, noText, _classAttr(ColorPairs.SEASONAL, confirmChoice == 1))
    return y + 1


def _deleteCharacter(accessToken: str, charId: int) -> Tuple[bool, str]:
    r = requests.post(url=ApiPoints.CHARDELETE, params={"accessToken": accessToken, "charId": charId})
    if "Success" in r.text:
        return True, ""
    return False, r.text
