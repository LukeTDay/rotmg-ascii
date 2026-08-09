from Constants.Screen import Screen

import curses
from typing import List

from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow, drawCenteredBanner, drawCenteredText, figletLineCount
from Models.CharListData import CharListData
from Models.Context import Context, required
from Constants.ClassIds import *

ROWS_PER_SLOT = 4  # 3 text rows + 1 blank spacer row


def drawCharSelect(stdscr : curses.window, ctx : Context) -> Screen:

    stdscr.erase()
    pad = curses.newpad(1500 ,500)

    pad.keypad(True)
    pad.clrtobot()

    loadedChars : List[CharListData] = required(ctx.get("CHARLIST"), "CHARLIST")

    loadedChars.sort(key=lambda char: char.currentFame, reverse=True)

    alias = required(ctx.get("account"), "account")["alias"]

    # Fixed regardless of scroll position/selection, so it only needs computing once.
    headerHeight = figletLineCount("Select a character") + 1 + figletLineCount(alias) + 1

    selected = 0
    scrollOffset = 0
    while True:
        pad.move(0,0)
        pad.clrtobot()

        height,width = stdscr.getmaxyx()
        visibleRows = max(1, (height - headerHeight) // ROWS_PER_SLOT)

        if selected < scrollOffset:
            scrollOffset = selected
        elif selected >= scrollOffset + visibleRows:
            scrollOffset = selected - visibleRows + 1

        entryCount = len(loadedChars) + 1  # + "Back to Account Select"
        shownCount = min(visibleRows, entryCount - scrollOffset)
        totalHeight = headerHeight + shownCount * ROWS_PER_SLOT
        y = max(0, (height - totalHeight) // 2)

        y = drawCenteredBanner(stdscr, pad, y, "Select a character")
        y += 1
        y = drawCenteredBanner(stdscr, pad, y, alias)
        y += 1

        for actualIndex in range(scrollOffset, min(scrollOffset + visibleRows, entryCount)):
            attr = curses.A_REVERSE if actualIndex == selected else curses.A_NORMAL
            if actualIndex < len(loadedChars):
                y = printCharSlot(stdscr, pad, y, loadedChars[actualIndex], attr)
            else:
                y = printBackSlot(stdscr, pad, y, attr)

        determineRefreshWindow(stdscr,pad,y)
        key = pad.getch()

        if key == curses.KEY_UP or key == ord('w'):
            selected = selected - 1
            selected = max(0, selected)
        elif key == curses.KEY_DOWN or key == ord('s'):
            selected = selected + 1
            selected = min(entryCount - 1, selected)
        elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            if selected == len(loadedChars):
                return Screen.accountSelect
            ctx["CURR_CHAR_ID"] = loadedChars[selected].charID
            return Screen.gameScreen

def printCharSlot(stdscr : curses.window,
                  pad : curses.window,
                  y : int,
                  char : CharListData,
                  attr : int) -> int:
    str1 = f" {char.charID:<3} - {idToClass(char.objectType):<11} - LVL {char.currentLevel:} "
    str2 = f" Current Fame: {char.currentFame :<9} - {'Seasonal' if char.isSeasonal else 'Standard'} "
    str3 = f" {char.equipmentList[0]:5} - {char.equipmentList[1]:5} - {char.equipmentList[2]:5} - {char.equipmentList[3]:5} "
    maxLength = max(len(str1),len(str2),len(str3))

    y = drawCenteredText(stdscr, pad, y, f"{str1:<{maxLength}}", attr)
    y = drawCenteredText(stdscr, pad, y, f"{str2:<{maxLength}}", attr)
    y = drawCenteredText(stdscr, pad, y, f"{str3:<{maxLength}}", attr)
    return y + 1

def printBackSlot(stdscr : curses.window,
                  pad : curses.window,
                  y : int,
                  attr : int) -> int:
    # Kept the same total height as printCharSlot (ROWS_PER_SLOT rows) so the
    # scroll/visibleRows math above can treat every entry as a uniform slot.
    y = drawCenteredText(stdscr, pad, y, "Back to Account Select", attr)
    return y + 3
