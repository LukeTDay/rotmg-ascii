from Utils.json.accCredLoader import credential_loader

from authentication.getAccessAndClientToken import getAccessAndClientToken

from Renders.AccountSelect.accountSelect import drawAccountSelect
from Renders.Login.login import drawLogin
from Renders.CharSelect.charSelect import drawCharSelect
from Renders.ServerSelect.serverSelect import drawServerSelect
from Renders.GameScreen.gameScreen import drawGame
from Renders.EnterAccountInfo.enterAccountInfo import enterAccountInfo

from Constants.Screen import Screen
from Constants import ColorPairs
from Models.Context import Context
from Debug.Debugger import Debugger

import curses, sys, traceback

#accessToken,clientToken = getAccessAndClientToken(accounts[0])[1]

def main(stdscr : curses.window, debugger : Debugger):
    debugger.info("App started")
    curses.curs_set(0) # Makes the cursor disappear
    curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    curses.mouseinterval(0)
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
    curses.init_pair(ColorPairs.MAP_BLACK, curses.COLOR_BLACK, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.MAP_RED, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.MAP_GREEN, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.MAP_YELLOW, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.MAP_BLUE, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.MAP_MAGENTA, curses.COLOR_MAGENTA, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.MAP_CYAN, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.MAP_WHITE, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.init_pair(ColorPairs.FILL_RED, curses.COLOR_BLACK, curses.COLOR_RED)
    curses.init_pair(ColorPairs.FILL_BLUE, curses.COLOR_BLACK, curses.COLOR_BLUE)
    curses.init_pair(ColorPairs.FILL_YELLOW, curses.COLOR_BLACK, curses.COLOR_YELLOW)
    curses.init_pair(ColorPairs.FILL_WHITE, curses.COLOR_BLACK, curses.COLOR_WHITE)
    stdscr.bkgd(" ", curses.color_pair(ColorPairs.DEFAULT))

    screen = Screen.accountSelect
    ctx : Context = {"DEBUGGER": debugger}  # shared data screens pass forward
    handlers = {
        Screen.accountSelect: drawAccountSelect,
        Screen.enterAccountInfo: enterAccountInfo,
        Screen.login: drawLogin,
        Screen.charSelect: drawCharSelect,
        Screen.serverSelect: drawServerSelect,
        Screen.gameScreen: drawGame,
    }
    while screen != Screen.exit:
        stdscr.erase()
        screen = handlers[screen](stdscr, ctx)

    debugger.info("App exited normally")

if __name__ == "__main__":
    debugger = Debugger()
    try:
        curses.wrapper(main, debugger)
    except Exception:
        # curses.wrapper already restored the terminal by this point, so it's
        # safe to print straight to the now-normal stdout/stderr.
        debugger.exception("Unhandled exception escaped curses.wrapper")
        traceback.print_exc()
        debugger.stop()
        sys.exit(1)
    else:
        debugger.stop()