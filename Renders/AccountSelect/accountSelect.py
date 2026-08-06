from Constants.Screen import Screen
from Utils.json.accCredLoader import credential_loader

import curses


def drawAccountSelect(stdscr : curses.window, ctx) -> Screen:

    storedAccounts = credential_loader()
    selected = 0
    scrollOffset = 0

    while True:
        stdscr.erase()
        stdscr.addstr(0,0,"Currently Stored Accounts: ")

        height,width = stdscr.getmaxyx()
        visibleRows = (height - 6) // 2

        if selected < scrollOffset:
            scrollOffset = selected
        elif selected >= scrollOffset + visibleRows:
            scrollOffset = selected - visibleRows + 1

        index = 0
        for account in storedAccounts[scrollOffset : scrollOffset + visibleRows]:
            actualIndex = scrollOffset + index
            if (actualIndex == selected):
                attr = curses.A_REVERSE
            else:
                attr = curses.A_NORMAL
            stdscr.addstr((index + 1) * 2, 0, f"{account["alias"]}", attr)
            index += 1
        actualIndex = scrollOffset + index
        if (actualIndex == selected):
            attr = curses.A_REVERSE
        else:
            attr = curses.A_NORMAL
        stdscr.addstr((index + 1) * 2, 0, f"Enter New Account Information", attr)

        stdscr.addstr((index + 2) * 2, 0, "Navigate to an account and press 'Enter'")

        stdscr.refresh()
        key = stdscr.getch()

        if key == curses.KEY_UP or key == ord('w'):
            selected = selected - 1
            selected = max(0, selected)
        elif key == curses.KEY_DOWN or key == ord('s'):
            selected = selected + 1
            selected = min(len(storedAccounts), selected)
        elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            if selected == len(storedAccounts):
                return Screen.enterAccountInfo
            ctx["account"] = storedAccounts[selected]
            return Screen.login

