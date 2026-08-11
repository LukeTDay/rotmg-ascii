from Constants.Screen import Screen
from Constants import ColorPairs
from Utils.json.accCredLoader import credential_loader
from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow, drawCenteredBanner, drawCenteredText, figletLineCount
from Renders.backgroundTexture import drawBackgroundTexture
from Models.Context import Context, required

import curses, json, os, tempfile

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
    selectionChanged = False
    removeMode = False

    while True:
        pad.move(0,0)
        pad.clrtobot()
        drawBackgroundTexture(stdscr, pad, ctx, forceRegen=selectionChanged)

        height,width = stdscr.getmaxyx()
        newAccountIndex = len(storedAccounts)
        toggleIndex = len(storedAccounts) + 1
        entryCount = len(storedAccounts) + 2  # + "Enter New Account Information" + remove/select toggle
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

        labels = [account["alias"] for account in storedAccounts] + [
            "Enter New Account Information",
            "Select Account" if removeMode else "Remove Account",
        ]
        index = 0
        for label in labels[scrollOffset : scrollOffset + visibleRows]:
            actualIndex = scrollOffset + index
            if actualIndex == selected:
                if removeMode and actualIndex < newAccountIndex:
                    attr = curses.color_pair(ColorPairs.ACCOUNT_REMOVE_SELECTED)
                else:
                    attr = curses.A_REVERSE
            else:
                attr = curses.A_NORMAL
            y = drawCenteredText(stdscr, pad, y, label, attr)
            y += 1
            index += 1

        prompt = "Navigate to an account and press 'Enter' to remove it" if removeMode else "Navigate to an account and press 'Enter'"
        y = drawCenteredText(stdscr, pad, y, prompt)
        determineRefreshWindow(stdscr, pad, y)
        key = pad.getch()

        prevSelected = selected
        if key == curses.KEY_UP or key == ord('w'):
            selected = selected - 1
            selected = max(0, selected)
        elif key == curses.KEY_DOWN or key == ord('s'):
            selected = selected + 1
            selected = min(entryCount - 1, selected)
        selectionChanged = selected != prevSelected

        if key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            if selected == toggleIndex:
                removeMode = not removeMode
                selected = 0
                selectionChanged = True
            elif selected == newAccountIndex:
                return Screen.enterAccountInfo
            elif removeMode:
                storedAccounts.pop(selected)
                tempLoc = tempfile.NamedTemporaryFile(mode="w", dir="Credentials/", delete=False, encoding="utf-8")
                json.dump(storedAccounts, tempLoc, indent=4)
                tempLoc.close()
                os.replace(tempLoc.name, "Credentials/account_credentials.json")
                removeMode = False
                selected = 0
                selectionChanged = True
            else:
                ctx["account"] = storedAccounts[selected]
                return Screen.login

