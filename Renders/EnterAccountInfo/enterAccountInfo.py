from Constants.Screen import Screen
from Utils.json.accCredLoader import credential_loader
from authentication.getAccessAndClientToken import getAccessAndClientToken
from Models.Context import Context, AccountData, required

import curses, json, time, os, tempfile, threading, queue, pyfiglet
from typing import List


def enterAccountInfo(stdscr : curses.window, ctx : Context) -> Screen:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Entering enterAccountInfo screen")

    try:
        storedAccounts = credential_loader()
    except FileNotFoundError:
        storedAccounts = []

    stdscr.erase()
    pad = curses.newpad(100,500)
    pad.keypad(True)
    pad.clrtobot()

    #Keeping track of yIndex so that it can be updated dynamically
    yIndex = 0

    #If an account has no accounts registered in their JSON file they will
    # be disallowed from returning to the account select screen
    canSelect = True
    if len(storedAccounts) == 0:
        canSelect = False

    #Only print this warning for accounts that can go back to the account
    # select screen
    if canSelect:
        drawCenteredText(stdscr,pad,yIndex,"If you would like to exit and select an already stored account please press ESC")
        determineRefreshWindow(stdscr,pad,yIndex)
        yIndex += 1
        drawCenteredText(stdscr,pad,yIndex,"**If your account_credentials.json does not exist or is empty you will be redirected back here directly**")
        determineRefreshWindow(stdscr,pad,yIndex)
        yIndex += 2
    if not canSelect:
        drawCenteredText(stdscr,pad,yIndex, "You do not have any accounts stored.")
        yIndex += 1
        drawCenteredText(stdscr,pad,yIndex, "You must input an account to move forward")
        determineRefreshWindow(stdscr,pad,yIndex)

    #In the case that passwords do not match will need to use this variable
    # as an anchor of where the passwords section started
    currYIndex = yIndex
    while True:
        #This resets the yIndex to the start of the password section
        # as well as clearing anything beneath it that may have been
        # printed before
        yIndex = currYIndex
        pad.move(yIndex,0)
        pad.clrtobot()
        determineRefreshWindow(stdscr=stdscr,
                               pad=pad,
                               yIndex=yIndex)

        email = getEmail(stdscr=stdscr,
                        pad=pad,
                        yIndex=yIndex,
                        )
        if email == None and canSelect:
            return Screen.accountSelect
        if email == None and not canSelect:
            yIndex += 1
            drawCenteredText(stdscr,pad,yIndex, "You do not have any other accounts stored you must input a new one")
            determineRefreshWindow(stdscr,pad,yIndex)
            time.sleep(2)
            continue
        #Mostly added these so pylance would stop whining
        assert email is not None, "Email should never be a none here"
        break
    yIndex += 2

    #In the case that passwords do not match will need to use this variable
    # as an anchor of where the passwords section started
    currYIndex = yIndex

    #This will continue until exit or both passwords are the same
    while True:
        #This resets the yIndex to the start of the password section
        # as well as clearing anything beneath it that may have been
        # printed before
        yIndex = currYIndex
        pad.move(yIndex,0)
        pad.clrtobot()
        determineRefreshWindow(stdscr,pad,yIndex)

        pass1 = getPassword(stdscr,
                            pad=pad,
                            questionToAsk="Please enter your password",
                            yIndex=yIndex)
        if pass1 is None and canSelect:
            return Screen.accountSelect
        yIndex += 2
        pass2 = getPassword(stdscr,
                            pad=pad,
                            questionToAsk="Confirm your password     ",
                            yIndex=yIndex)
        if pass2 is None and canSelect:
            return Screen.accountSelect

        if pass1 == pass2:
            password = pass1
            assert password is not None, "Password should never be None here"
            break
        else:
            debugger.warning("Password confirmation did not match")
            yIndex += 1
            drawCenteredText(stdscr,pad,yIndex,"Password's did not match")
            determineRefreshWindow(stdscr,pad,yIndex)
            yIndex += 1
            drawCenteredText(stdscr,pad,yIndex,"Press any key to retry or ESC to select another account")
            determineRefreshWindow(stdscr,pad,yIndex)
            ch = pad.getch()
            if ch == 27:
                if len(storedAccounts) == 0:
                    yIndex += 2
                    drawCenteredText(stdscr,pad,yIndex,"You currently have no accounts locally stored you must input one to continue")
                    determineRefreshWindow(stdscr,pad,yIndex)
                    time.sleep(2)
                    continue
                return Screen.accountSelect

    #Verify that the email and password combination actually work.
    # If they do prompt for an alias and save the account to the json file
    # If it does not notify the user and then recall this module
    yIndex += 2

    resultQueue = queue.Queue()

    if email is None:
        raise RuntimeError("Email is None. This should not be possible")
    if password is None:
        raise RuntimeError("Password is None. This should not be possible")

    credentialDict = {
        "email" : email,
        "password"  : password
    }

    thread = threading.Thread(target=verifyWorker, args=(credentialDict, resultQueue, debugger), daemon=True)
    thread.start()

    buf : List[str] = []
    while thread.is_alive():
        pad.move(yIndex,0)
        pad.clrtobot()
        drawCenteredText(stdscr,pad,yIndex,f"Verifying ROTMG account{''.join(buf)}")
        determineRefreshWindow(stdscr,pad,yIndex)
        time.sleep(0.25)
        if len(buf) == 5:
            buf = []
        else:
            buf.append(".")

    success = resultQueue.get()

    if not success[0]:
        errReason = success[1]
        errText = success[2]
        debugger.warning(f"Account verify failed ({errReason}): {errText}")
        if errReason == "TOKEN_ERROR":
            pad.clrtobot()
            drawCenteredText(stdscr,pad,yIndex, "There was an issue loading your token")
            yIndex += 1
            drawCenteredText(stdscr,pad,yIndex,f"Incorrect email or password")
            determineRefreshWindow(stdscr,pad,yIndex)
        elif errReason == "VERIFY_TOKEN_ERROR":
            pad.clrtobot()
            drawCenteredText(stdscr,pad,yIndex, "There was an issue verifying your token")
            yIndex += 1
            drawCenteredText(stdscr,pad,yIndex,f"Error Message: {errText}")
            determineRefreshWindow(stdscr,pad,yIndex)
        elif errReason == "UNEXPECTED_ERROR":
            pad.clrtobot()
            drawCenteredText(stdscr,pad,yIndex, "There was an unexpected error")
            yIndex += 1
            drawCenteredText(stdscr,pad,yIndex,f"Error Message: {errText}")
            determineRefreshWindow(stdscr,pad,yIndex)
        yIndex += 2
        drawCenteredText(stdscr,pad,yIndex,"Please press any key to try again.")
        determineRefreshWindow(stdscr,pad,yIndex)
        pad.getch()
        return Screen.enterAccountInfo

    debugger.info("Account successfully verified")
    pad.clrtobot()
    drawCenteredText(stdscr,pad,yIndex, "Account successfully verified.")
    determineRefreshWindow(stdscr,pad,yIndex)

    yIndex += 2
    currYIndex = yIndex
    while True:
        yIndex = currYIndex
        pad.move(yIndex,0)
        pad.clrtobot()

        alias = getAlias(
            stdscr=stdscr,
            pad=pad,
            yIndex=yIndex,
        )
        if alias == "":
            yIndex += 1
            drawCenteredText(stdscr,pad,yIndex, "Cannot use an empty alias.")
            determineRefreshWindow(stdscr,pad,yIndex)
            time.sleep(2)
            continue

        if alias is not None:
            shouldRecreate = False
            for account in storedAccounts:
                if account["alias"] == alias:
                    debugger.warning(f"Alias '{alias}' already in use")
                    yIndex += 1
                    drawCenteredText(stdscr,pad,yIndex,f"{alias} is already in use. You must choose another one")
                    determineRefreshWindow(stdscr,pad,yIndex)
                    time.sleep(2)
                    shouldRecreate = True
                    break
            if shouldRecreate:
                continue
            break

        if len(storedAccounts) == 0:
            yIndex += 1
            drawCenteredText(stdscr,pad,yIndex, "As you do not have any other accounts, you must choose an alias for this one.")
            determineRefreshWindow(stdscr,pad,yIndex)
            time.sleep(2)
            continue
        return Screen.accountSelect

    newEntry : AccountData = {
        "alias" : alias,
        "email" : email,
        "password" : password
    }
    storedAccounts.append(newEntry)

    #Storing the accounts in the credentials folder
    dirExists = os.path.isdir("Credentials/")
    if not dirExists:
        try:
            os.mkdir("Credentials")
        except PermissionError:
            debugger.exception("No permission to create Credentials/ directory")
            yIndex += 2
            drawCenteredText(stdscr,pad,yIndex,"Credentials directory does not exist and insufficient "
            "permission to create a new one. Please create the directory yourself or run "
            "the program with higher authority.")
            determineRefreshWindow(stdscr,pad,yIndex)
            yIndex += 1
            drawCenteredText(stdscr,pad,yIndex,"Enter to exit.")
            determineRefreshWindow(stdscr,pad,yIndex)
            pad.getch()
            return Screen.exit
        except Exception as e:
            debugger.exception("Unexpected error creating Credentials/ directory")
            yIndex += 2
            drawCenteredText(stdscr,pad,yIndex,"Unexpected error occured when trying to create a directory to store the credentials.")
            determineRefreshWindow(stdscr,pad,yIndex)
            yIndex += 1
            drawCenteredText(stdscr,pad,yIndex,f"Error {e}")
            determineRefreshWindow(stdscr,pad,yIndex)
            yIndex += 1
            drawCenteredText(stdscr,pad,yIndex,"Press enter to exit.")
            determineRefreshWindow(stdscr,pad,yIndex)
            return Screen.exit

    tempLoc = tempfile.NamedTemporaryFile(mode="w",dir="Credentials/", delete=False, encoding="utf-8")
    json.dump(storedAccounts,tempLoc, indent=4)
    tempLoc.close()
    os.replace(tempLoc.name, "Credentials/account_credentials.json")

    return Screen.accountSelect

def determineRefreshWindow(stdscr : curses.window,
                           pad : curses.window,
                           yIndex : int) -> None:
    maxY, maxX = stdscr.getmaxyx()
    scrollTop = max(0, yIndex - maxY + 1)
    pad.refresh(scrollTop,0,0,0,maxY-1,maxX-1)

def drawCenteredText(stdscr : curses.window,
                     pad : curses.window,
                     y : int,
                     text : str,
                     attr : int = curses.A_NORMAL) -> int:
    """Writes a single line centered against the terminal's actual width
    (not the pad's fixed width). Returns the next free row."""
    _, maxX = stdscr.getmaxyx()
    x = max(0, (maxX - len(text)) // 2)
    pad.addstr(y, x, text[:max(0, maxX - x)], attr)
    return y + 1

def centeredX(stdscr : curses.window, text : str) -> int:
    """Column that would center this text against the terminal's actual width.
    Callers that redraw a growing/shrinking string (e.g. live input echo)
    should compute this once from a fixed-length anchor string and reuse it,
    rather than recomputing from the current text each redraw - recomputing
    would recenter (and therefore visibly shift) the line on every keystroke."""
    _, maxX = stdscr.getmaxyx()
    return max(0, (maxX - len(text)) // 2)

def drawTextAt(stdscr : curses.window,
               pad : curses.window,
               y : int,
               x : int,
               text : str,
               attr : int = curses.A_NORMAL) -> int:
    """Writes text at a fixed column instead of recentering it. Returns the
    next free row."""
    _, maxX = stdscr.getmaxyx()
    pad.addstr(y, x, text[:max(0, maxX - x)], attr)
    return y + 1

def _figletLines(text : str, font : str = "standard") -> List[str]:
    # width=1000 disables pyfiglet's default 80-column auto-wrap, which would
    # otherwise silently wrap longer banners onto a garbled second line.
    return pyfiglet.Figlet(font=font, width=1000).renderText(text).rstrip("\n").split("\n")

def figletLineCount(text : str, font : str = "standard") -> int:
    """Row count a banner of this text/font will take up, without drawing it -
    lets a caller lay out content around a banner before rendering it."""
    return len(_figletLines(text, font))

def drawCenteredBanner(stdscr : curses.window,
                       pad : curses.window,
                       y : int,
                       text : str,
                       font : str = "standard",
                       attr : int = curses.A_NORMAL) -> int:
    """Renders text as large pyfiglet ASCII-art, each line centered against the
    terminal's actual width (re-read every call, so it re-centers if the
    terminal is resized between frames). Returns the next free row so callers
    can stack more content underneath."""
    _, maxX = stdscr.getmaxyx()
    lines = _figletLines(text, font)
    for i, line in enumerate(lines):
        x = max(0, (maxX - len(line)) // 2)
        pad.addstr(y + i, x, line[:max(0, maxX - x)], attr)
    return y + len(lines)

def getPassword(stdscr : curses.window,
                pad : curses.window,
                questionToAsk : str,
                yIndex : int) -> str | None:
    prompt = f"{questionToAsk}: "
    # Anchored on the prompt's own (fixed-length) width, not the growing
    # buffer, so the line doesn't recenter/shift horizontally as you type.
    x = centeredX(stdscr, prompt)
    drawTextAt(stdscr,pad,yIndex,x,prompt)
    determineRefreshWindow(stdscr,pad,yIndex)

    buf = []
    while True:
        ch = pad.getch()
        if ch in (curses.KEY_ENTER, ord('\n')):
            break
        elif ch == 27:
            return None
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
        else:
            buf.append(chr(ch))

        pad.move(yIndex, x)
        pad.clrtobot()
        drawTextAt(stdscr,pad,yIndex,x,f"{prompt}{'*' * len(buf)} ")
        determineRefreshWindow(stdscr,pad,yIndex)

    result = ''.join(buf)
    return result

def getEmail(stdscr : curses.window,
                pad : curses.window,
                yIndex : int) -> str | None:
    prompt = "Please enter your email: "
    x = centeredX(stdscr, prompt)
    drawTextAt(stdscr,pad,yIndex,x,prompt)
    determineRefreshWindow(stdscr,pad,yIndex)

    buf = []
    while True:
        ch = pad.getch()
        if ch in (curses.KEY_ENTER, ord('\n')):
            break
        elif ch == 27:
            return None
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
        else:
            buf.append(chr(ch))
        pad.move(yIndex, x)
        pad.clrtobot()
        drawTextAt(stdscr,pad,yIndex,x, f"{prompt}{''.join(buf)}")
        determineRefreshWindow(stdscr,pad,yIndex)
    return ''.join(buf)

def getAlias(stdscr : curses.window,
                pad : curses.window,
                yIndex : int) -> str | None:
    prompt = "Please enter the alias of this account: "
    x = centeredX(stdscr, prompt)
    drawTextAt(stdscr,pad,yIndex,x,prompt)
    determineRefreshWindow(stdscr,pad,yIndex)

    buf = []
    while True:
        ch = pad.getch()
        if ch in (curses.KEY_ENTER, ord('\n')):
            break
        elif ch == 27:
            return None
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
        else:
            buf.append(chr(ch))
        pad.move(yIndex, x)
        pad.clrtobot()
        drawTextAt(stdscr,pad,yIndex,x, f"{prompt}{''.join(buf)}")
        determineRefreshWindow(stdscr,pad,yIndex)
    return ''.join(buf)

def verifyWorker(credentialDict, resultQueue, debugger) -> None:
    try:
        outcome = getAccessAndClientToken(credentialDict, debugger)
    except Exception as e:
        debugger.exception("Unexpected error verifying account")
        outcome = (False, "UNEXPECTED_ERROR", f"Unexpected error: {e}")
    resultQueue.put(outcome)



