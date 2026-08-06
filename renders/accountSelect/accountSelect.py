from Constants.Screen import Screen
from Utils.json.accCredLoader import credential_loader

import curses


def drawAccountSelect(stdscr : curses.window, ctx) -> Screen:

    storedAccounts = credential_loader()

    yIndex = 0
    stdscr.addstr(yIndex,0,"Currently stored accounts")
    i = 0
    for account in storedAccounts:
        yIndex += 2
        i+= 1
        stdscr.addstr(yIndex, 0, f"{i}: {account["alias"]}")
    stdscr.addstr(yIndex+2, 0, f"{i+1}: Enter a New Account")
    stdscr.addstr(yIndex+4, 0, f"{i+2}: Exit Program")
    

    stdscr.addstr(yIndex + 6,0,f"Please make a selection:")
    stdscr.refresh()
    input = stdscr.getch()

    if (input == ord(f"{i+2}")):
        return Screen.exit
    elif (input == ord(f"i+1"))
        return Screen.enterAccountInfo
    elif ord('1') <= input <= ord(str(i)):
        selected = input - ord('0')          # back to an actual int, e.g. 3
        ctx["account"] = storedAccounts[selected - 1]
        return Screen.login
    return Screen.accountSelect
    pass
