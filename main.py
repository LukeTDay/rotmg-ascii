from Utils.json.accCredLoader import credential_loader

from authentication.getAccessAndClientToken import getAccessAndClientToken

from Renders.AccountSelect.accountSelect import drawAccountSelect
from Renders.Login.login import drawLogin
from Renders.CharSelect.charSelect import drawCharSelect
from Renders.GameScreen.gameScreen import drawGame
from Renders.EnterAccountInfo.enterAccountInfo import enterAccountInfo

from Constants.Screen import Screen
from Constants import ColorPairs
from Models.Context import Context

import curses, sys, traceback

#accessToken,clientToken = getAccessAndClientToken(accounts[0])[1]

def main(stdscr : curses.window):
    curses.curs_set(0) # Makes the cursor disappear
    curses.start_color()
    curses.init_pair(ColorPairs.DEFAULT, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.FAME, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.SEASONAL, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.STANDARD, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.CRUCIBLE, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.FAME_SELECTED, curses.COLOR_YELLOW, curses.COLOR_WHITE)
    curses.init_pair(ColorPairs.SEASONAL_SELECTED, curses.COLOR_GREEN, curses.COLOR_WHITE)
    curses.init_pair(ColorPairs.STANDARD_SELECTED, curses.COLOR_BLUE, curses.COLOR_WHITE)
    curses.init_pair(ColorPairs.CRUCIBLE_SELECTED, curses.COLOR_RED, curses.COLOR_WHITE)
    stdscr.bkgd(" ", curses.color_pair(ColorPairs.DEFAULT))

    screen = Screen.accountSelect
    ctx : Context = {}  # shared data screens pass forward
    handlers = {
        Screen.accountSelect: drawAccountSelect,
        Screen.enterAccountInfo: enterAccountInfo,
        Screen.login: drawLogin,
        Screen.charSelect: drawCharSelect,
        Screen.gameScreen: drawGame,
    }
    while screen != Screen.exit:
        stdscr.erase()
        screen = handlers[screen](stdscr, ctx)

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except Exception:
        # curses.wrapper already restored the terminal by this point, so it's
        # safe to print straight to the now-normal stdout/stderr.
        traceback.print_exc()
        sys.exit(1)