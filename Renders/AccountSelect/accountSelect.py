from Constants.Screen import Screen
from Utils.json.accCredLoader import credential_loader
from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow, drawCenteredBanner, drawCenteredText, figletLineCount
from Renders.backgroundTexture import drawBackgroundTexture
from Models.Context import Context, required

import curses, json

ROWS_PER_SLOT = 2  # 1 text row + 1 blank spacer row


def drawAccountSelect(stdscr : curses.window, ctx : Context) -> Screen:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Entering accountSelect screen")

    try:
        storedAccounts = credential_loader()
    except json.JSONDecodeError as e:
        debugger.exception("Failed to parse Credentials/account_credentials.json")
        stdscr.erase()
        pad = curses.newpad(1500, 500)
        pad.keypad(True)
        y = drawCenteredBanner(stdscr, pad, 0, "JSON Error")
        y = drawCenteredText(stdscr, pad, y + 1, "There was an error decoding your JSON folder")
        y = drawCenteredText(stdscr, pad, y, "Please reference the README for help")
        y = drawCenteredText(stdscr, pad, y + 1, f"Error: {e}")
        y = drawCenteredText(stdscr, pad, y + 1, "Please enter any key to exit.")
        determineRefreshWindow(stdscr, pad, y)
        pad.getch()
        return Screen.exit
    except FileNotFoundError:
        debugger.info("No account_credentials.json found - redirecting to enterAccountInfo")
        return Screen.enterAccountInfo
    if len(storedAccounts) == 0:
        return Screen.enterAccountInfo

    stdscr.erase()
    pad = curses.newpad(1500, 500)
    pad.keypad(True)
    pad.clrtobot()

    # Fixed regardless of scroll position/selection, so it only needs computing once.
    headerHeight = figletLineCount("Select an account") + 1

    selected = 0
    scrollOffset = 0

    while True:
        pad.move(0,0)
        pad.clrtobot()
        drawBackgroundTexture(stdscr, pad, ctx)

        height,width = stdscr.getmaxyx()
        entryCount = len(storedAccounts) + 1  # + "Enter New Account Information"
        visibleRows = max(1, (height - headerHeight) // ROWS_PER_SLOT)

        if selected < scrollOffset:
            scrollOffset = selected
        elif selected >= scrollOffset + visibleRows:
            scrollOffset = selected - visibleRows + 1

        shownCount = min(visibleRows, entryCount - scrollOffset)
        totalHeight = headerHeight + shownCount * ROWS_PER_SLOT
        y = max(0, (height - totalHeight) // 2)

        y = drawCenteredBanner(stdscr, pad, y, "Select an account")
        y += 1

        labels = [account["alias"] for account in storedAccounts] + ["Enter New Account Information"]
        index = 0
        for label in labels[scrollOffset : scrollOffset + visibleRows]:
            actualIndex = scrollOffset + index
            attr = curses.A_REVERSE if actualIndex == selected else curses.A_NORMAL
            y = drawCenteredText(stdscr, pad, y, label, attr)
            y += 1
            index += 1

        y = drawCenteredText(stdscr, pad, y, "Navigate to an account and press 'Enter'")
        determineRefreshWindow(stdscr, pad, y)
        key = pad.getch()

        if key == curses.KEY_UP or key == ord('w'):
            selected = selected - 1
            selected = max(0, selected)
        elif key == curses.KEY_DOWN or key == ord('s'):
            selected = selected + 1
            selected = min(entryCount - 1, selected)
        elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            if selected == len(storedAccounts):
                return Screen.enterAccountInfo
            ctx["account"] = storedAccounts[selected]
            return Screen.login

