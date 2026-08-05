from Utils.json.accCredLoader import credential_loader

from authentication.getAccessAndClientToken import getAccessAndClientToken

from renders.accountSelect.accountSelect import draw_account_select
from renders.login.login import draw_login
from renders.charSelect.charSelect import draw_char_select
from renders.gameScreen.gameScreen import draw_game

from Constants.Screen import Screen

import curses

#accounts = credential_loader()
#accessToken,clientToken = getAccessAndClientToken(accounts[0])[1]

def main(stdscr):
    screen = Screen.accountSelect
    ctx = {}  # shared data screens pass forward
    handlers = {
        Screen.accountSelect: draw_account_select,
        Screen.login: draw_login,
        Screen.charSelect: draw_char_select,
        Screen.gameScreen: draw_game,
    }
    while screen != Screen.exit:
        stdscr.erase()
        screen = handlers[screen](stdscr, ctx)

if __name__ == "__main__":
    curses.wrapper(main)