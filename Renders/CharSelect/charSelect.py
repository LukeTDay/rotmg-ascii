from Constants.Screen import Screen

import curses
from typing import List

from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow
from Models.CharListData import CharListData
from Models.Context import Context, required
from Constants.ClassIds import *


def drawCharSelect(stdscr : curses.window, ctx : Context) -> Screen:

    stdscr.erase()
    pad = curses.newpad(1500 ,150)

    pad.keypad(True)
    pad.clrtobot()

    loadedChars : List[CharListData] = required(ctx.get("CHARLIST"), "CHARLIST")

    loadedChars.sort(key=lambda char: char.currentFame, reverse=True)

    WIDTH_TILL_NEXT_LISTING = 4
    selected = 0
    scrollOffset = 0
    while True:
        pad.move(0,0)
        pad.clrtobot()
        pad.addstr(0,0,f"{'Select a character':^36}")
        alias = required(ctx.get("account"), "account")["alias"]
        pad.addstr(2,0,f"{alias:^36}")

        height,width = stdscr.getmaxyx()
        visibleRows = (height - 6) // WIDTH_TILL_NEXT_LISTING

        if selected < scrollOffset:
            scrollOffset = selected
        elif selected >= scrollOffset + visibleRows:
            scrollOffset = selected - visibleRows + 1

        index = 0
        for char in loadedChars[scrollOffset : scrollOffset + visibleRows]:
            actualIndex = scrollOffset + index
            if (actualIndex == selected):
                attr = curses.A_REVERSE
            else:
                attr = curses.A_NORMAL
            printCharSlot(pad,index,char, attr, WIDTH_TILL_NEXT_LISTING)
            index += 1
        determineRefreshWindow(stdscr,pad,index)
        key = pad.getch()

        if key == curses.KEY_UP or key == ord('w'):
            selected = selected - 1
            selected = max(0, selected)
        elif key == curses.KEY_DOWN or key == ord('s'):
            selected = selected + 1
            selected = min(len(loadedChars) - 1, selected)
        elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            ctx["CURR_CHAR_ID"] = loadedChars[selected].charID
            return Screen.gameScreen

def printCharSlot(pad : curses.window,
                  index : int,
                  char : CharListData,
                  attr : int,
                  width : int) -> None:
    baseIndex = (index + 1) * width
    str1 = f" {char.charID:<3} - {idToClass(char.objectType):<11} - LVL {char.currentLevel:} "
    str2 = f" Current Fame: {char.currentFame :<9} - {'Seasonal' if char.isSeasonal else 'Standard'} "
    str3 = f" {char.equipmentList[0]:5} - {char.equipmentList[1]:5} - {char.equipmentList[2]:5} - {char.equipmentList[3]:5} "
    maxLength = max(len(str1),len(str2),len(str3))
    pad.addstr(baseIndex,     0, f"{str1:<{maxLength}}", attr)
    pad.addstr(baseIndex + 1, 0, f"{str2:<{maxLength}}", attr)
    pad.addstr(baseIndex + 2, 0, f"{str3:<{maxLength}}", attr)
