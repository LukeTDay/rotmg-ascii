from Constants.Screen import Screen

import curses
from typing import List

from Renders.EnterAccountInfo.enterAccountInfo import centeredX, determineRefreshWindow, drawCenteredBanner, drawCenteredText, figletLineCount
from Models.CharListData import CharListData
from Models.Context import Context, required
from Constants.ClassIds import *
from Constants import ColorPairs
from Utils.XML.parseObjectNames import objectIdToName

ROWS_PER_SLOT = 4  # 3 text rows + 1 blank spacer row
STATS_WIDTH = 25  # fixed width for the name/level and fame/seasonal rows


def drawCharSelect(stdscr : curses.window, ctx : Context) -> Screen:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Entering charSelect screen")

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
            return Screen.serverSelect

def _printSplitRow(stdscr : curses.window,
                   pad : curses.window,
                   y : int,
                   leftText : str,
                   rightText : str,
                   width : int,
                   leftPair : int | None,
                   rightPair : int | None,
                   selected : bool) -> int:
    """Draws leftText/rightText spread across width, each independently
    plain or colored via a native curses.COLOR_*/init_pair() pair (None =
    plain) - same "no RGB remap" approach Debug/cp437_full_charset_16color_test.py
    confirmed renders identically on Windows and Linux (raw ANSI truecolor
    doesn't survive curses.addstr - see CLAUDE.md).

    When selected, plain segments get A_REVERSE (the usual highlighted-row
    look) but colored segments switch to their ColorPairs.SELECTED_VARIANT
    (same foreground, white background) instead - reverse-video would swap
    fg/bg and wash out the color's hue, and the point of coloring these in
    the first place is for it to stay visible while selected."""
    gap = max(1, width - len(leftText) - len(rightText))
    line = f"{leftText}{' ' * gap}{rightText}"
    x = centeredX(stdscr, line)
    _, maxX = stdscr.getmaxyx()

    def clip(text : str, startX : int) -> str:
        return text[:max(0, maxX - startX)]

    def segAttr(pair : int | None) -> int:
        if pair is None:
            return curses.A_REVERSE if selected else curses.A_NORMAL
        if selected:
            return curses.color_pair(ColorPairs.SELECTED_VARIANT[pair]) | curses.A_BOLD
        return curses.color_pair(pair)

    if leftClipped := clip(leftText, x):
        pad.addstr(y, x, leftClipped, segAttr(leftPair))
    gapX = x + len(leftText)
    if gapClipped := clip(' ' * gap, gapX):
        pad.addstr(y, gapX, gapClipped, curses.A_REVERSE if selected else curses.A_NORMAL)
    rightX = gapX + gap
    if rightClipped := clip(rightText, rightX):
        pad.addstr(y, rightX, rightClipped, segAttr(rightPair))
    return y + 1

def _statsRowTexts(char : CharListData) -> tuple[str, str, str, str]:
    nameText = f" {idToClass(char.objectType)}"
    levelText = f"LVL {char.currentLevel:2} "
    fameText = f" {char.currentFame}"
    seasonalText = f"{'Seasonal' if char.isSeasonal else 'Standard'} "
    return nameText, levelText, fameText, seasonalText

def _equipSlotText(objectId : int) -> str:
    if objectId == -1:
        return "Empty"
    return objectIdToName(objectId) or str(objectId)

def _truncateItemName(name : str, width : int) -> str:
    """Truncates a single item name to width, replacing the cut-off tail with
    "..." rather than chopping it silently - keeps a truncated name readable
    ("Sprite's Wand of...") instead of ending mid-word with no indication."""
    if len(name) <= width:
        return name
    if width <= 3:
        return name[:max(0, width)]
    return name[:width - 3] + "..."

def _buildEquipmentRow(stdscr : curses.window, char : CharListData) -> str:
    """Resolves the first 4 equipment slots (weapon/ability/armor/ring -
    equipmentList can carry more entries than that, e.g. inventory/backpack,
    which this deliberately ignores) to names, and truncates each name
    individually so the combined row never exceeds the terminal's actual
    width - instead of letting the tail of the whole line get blindly clipped
    by drawCenteredText, which could cut an early item's name off mid-word or
    drop later items entirely."""
    names = [_equipSlotText(i) for i in char.equipmentList[:4]]
    if not names:
        return ""

    _, maxX = stdscr.getmaxyx()
    separator = " - "
    overhead = 2 + len(separator) * (len(names) - 1)  # leading/trailing space + separators
    perItemWidth = max(1, (maxX - overhead) // len(names))

    truncated = [_truncateItemName(name, perItemWidth) for name in names]
    return " " + separator.join(truncated) + " "

def printCharSlot(stdscr : curses.window,
                  pad : curses.window,
                  y : int,
                  char : CharListData,
                  attr : int) -> int:
    nameText, levelText, fameText, seasonalText = _statsRowTexts(char)
    str3 = _buildEquipmentRow(stdscr, char)

    selected = attr == curses.A_REVERSE
    namePair = ColorPairs.CRUCIBLE if char.isInCrucible else None
    seasonalPair = ColorPairs.SEASONAL if char.isSeasonal else ColorPairs.STANDARD

    y = _printSplitRow(stdscr, pad, y, nameText, levelText, STATS_WIDTH, namePair, None, selected)
    y = _printSplitRow(stdscr, pad, y, fameText, seasonalText, STATS_WIDTH, ColorPairs.FAME, seasonalPair, selected)
    y = drawCenteredText(stdscr, pad, y, str3, attr)
    return y + 1

def printBackSlot(stdscr : curses.window,
                  pad : curses.window,
                  y : int,
                  attr : int) -> int:
    # Kept the same total height as printCharSlot (ROWS_PER_SLOT rows) so the
    # scroll/visibleRows math above can treat every entry as a uniform slot.
    y = drawCenteredText(stdscr, pad, y, "Back to Account Select", attr)
    return y + 3
