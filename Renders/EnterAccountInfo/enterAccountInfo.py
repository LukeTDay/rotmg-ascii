from Constants.Screen import Screen
from Utils.json.accCredLoader import credential_loader
from authentication.getAccessAndClientToken import getAccessAndClientToken
from Renders.backgroundTexture import drawBackgroundTexture
from Models.Context import Context, AccountData, required

import curses, json, time, os, tempfile, threading, queue, pyfiglet
from typing import Callable, List, Sequence

# How often idle redraws fire while waiting on input (ms). Short enough that
# typing feels instant and the background texture keeps animating, long
# enough not to burn CPU redrawing a pad every loop.
INPUT_POLL_MS = 50

DrawFn = Callable[[], None]


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

    # Everything already committed to the screen (headers, previously
    # confirmed input). Redrawn in full alongside the background texture on
    # every tick, so the texture can keep animating without ever leaving
    # earlier prompts/echoed input undrawn (and thus vulnerable to being
    # overwritten by the texture's next scatter of glyphs).
    transcript : List[DrawFn] = []

    # No stored accounts means there's nothing to go back to.
    canSelect = len(storedAccounts) > 0

    yIndex = 0
    if canSelect:
        transcript.append(_centeredLine(stdscr, pad, yIndex, "If you would like to exit and select an already stored account please press ESC"))
        yIndex += 1
        transcript.append(_centeredLine(stdscr, pad, yIndex, "**If your account_credentials.json does not exist or is empty you will be redirected back here directly**"))
        yIndex += 2
    else:
        transcript.append(_centeredLine(stdscr, pad, yIndex, "You do not have any accounts stored."))
        yIndex += 1
        transcript.append(_centeredLine(stdscr, pad, yIndex, "You must input an account to move forward"))

    # Anchor to reset back to if this section needs to be retried.
    currYIndex = yIndex
    while True:
        yIndex = currYIndex
        email = _readLine(stdscr, pad, ctx, transcript, yIndex, "Please enter your email: ")
        if email is None and canSelect:
            return Screen.accountSelect
        if email is None and not canSelect:
            yIndex += 1
            msg = _centeredLine(stdscr, pad, yIndex, "You do not have any other accounts stored you must input a new one")
            _renderFrame(stdscr, pad, ctx, transcript, yIndex, extra=(msg,))
            time.sleep(2)
            continue
        # Type-checker appeasement.
        assert email is not None, "Email should never be a none here"
        break
    yIndex += 2

    # Anchor to reset back to if this section needs to be retried.
    currYIndex = yIndex

    while True:
        yIndex = currYIndex
        beforeLen = len(transcript)

        pass1 = _readLine(stdscr, pad, ctx, transcript, yIndex, "Please enter your password: ", mask=True)
        if pass1 is None:
            if canSelect:
                return Screen.accountSelect
            yIndex += 1
            msg = _centeredLine(stdscr, pad, yIndex, "You do not have any other accounts stored you must set a password to continue")
            _renderFrame(stdscr, pad, ctx, transcript, yIndex, extra=(msg,))
            time.sleep(2)
            del transcript[beforeLen:]
            continue
        yIndex += 2
        pass2 = _readLine(stdscr, pad, ctx, transcript, yIndex, "Confirm your password     : ", mask=True)
        if pass2 is None:
            if canSelect:
                return Screen.accountSelect
            yIndex += 1
            msg = _centeredLine(stdscr, pad, yIndex, "You do not have any other accounts stored you must set a password to continue")
            _renderFrame(stdscr, pad, ctx, transcript, yIndex, extra=(msg,))
            time.sleep(2)
            del transcript[beforeLen:]
            continue

        if pass1 == pass2:
            password = pass1
            assert password is not None, "Password should never be None here"
            break

        debugger.warning("Password confirmation did not match")
        yIndex += 1
        msg1 = _centeredLine(stdscr, pad, yIndex, "Password's did not match")
        yIndex += 1
        msg2 = _centeredLine(stdscr, pad, yIndex, "Press any key to retry or ESC to select another account")
        ch = _waitForKey(stdscr, pad, ctx, transcript, yIndex, extra=(msg1, msg2))
        # Discard this attempt's committed password lines before retrying.
        del transcript[beforeLen:]
        if ch == 27:
            if len(storedAccounts) == 0:
                yIndex += 2
                msg3 = _centeredLine(stdscr, pad, yIndex, "You currently have no accounts locally stored you must input one to continue")
                _renderFrame(stdscr, pad, ctx, transcript, yIndex, extra=(msg3,))
                time.sleep(2)
                continue
            return Screen.accountSelect

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

    verifyingTextX = centeredX(stdscr, "Verifying ROTMG account.....")
    buf : List[str] = []
    while thread.is_alive():
        spinner = _fixedLine(stdscr, pad, yIndex, verifyingTextX, f"Verifying ROTMG account{''.join(buf)}")
        _renderFrame(stdscr, pad, ctx, transcript, yIndex, extra=(spinner,))
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
        msgs : List[DrawFn] = []
        if errReason == "TOKEN_ERROR":
            msgs.append(_centeredLine(stdscr, pad, yIndex, "There was an issue loading your token"))
            yIndex += 1
            msgs.append(_centeredLine(stdscr, pad, yIndex, "Incorrect email or password"))
        elif errReason == "VERIFY_TOKEN_ERROR":
            msgs.append(_centeredLine(stdscr, pad, yIndex, "There was an issue verifying your token"))
            yIndex += 1
            msgs.append(_centeredLine(stdscr, pad, yIndex, f"Error Message: {errText}"))
        elif errReason == "UNEXPECTED_ERROR":
            msgs.append(_centeredLine(stdscr, pad, yIndex, "There was an unexpected error"))
            yIndex += 1
            msgs.append(_centeredLine(stdscr, pad, yIndex, f"Error Message: {errText}"))
        yIndex += 2
        msgs.append(_centeredLine(stdscr, pad, yIndex, "Please press any key to try again."))
        _waitForKey(stdscr, pad, ctx, transcript, yIndex, extra=msgs)
        return Screen.enterAccountInfo

    debugger.info("Account successfully verified")
    transcript.append(_centeredLine(stdscr, pad, yIndex, "Account successfully verified."))
    _renderFrame(stdscr, pad, ctx, transcript, yIndex)

    yIndex += 2
    currYIndex = yIndex
    while True:
        yIndex = currYIndex
        beforeLen = len(transcript)

        alias = _readLine(stdscr, pad, ctx, transcript, yIndex, "Please enter the alias of this account: ")
        if alias == "":
            yIndex += 1
            msg = _centeredLine(stdscr, pad, yIndex, "Cannot use an empty alias.")
            _renderFrame(stdscr, pad, ctx, transcript, yIndex, extra=(msg,))
            time.sleep(2)
            del transcript[beforeLen:]
            continue

        if alias is not None:
            shouldRecreate = False
            for account in storedAccounts:
                if account["alias"] == alias:
                    debugger.warning(f"Alias '{alias}' already in use")
                    yIndex += 1
                    msg = _centeredLine(stdscr, pad, yIndex, f"{alias} is already in use. You must choose another one")
                    _renderFrame(stdscr, pad, ctx, transcript, yIndex, extra=(msg,))
                    time.sleep(2)
                    shouldRecreate = True
                    break
            if shouldRecreate:
                del transcript[beforeLen:]
                continue
            break

        if len(storedAccounts) == 0:
            yIndex += 1
            msg = _centeredLine(stdscr, pad, yIndex, "As you do not have any other accounts, you must choose an alias for this one.")
            _renderFrame(stdscr, pad, ctx, transcript, yIndex, extra=(msg,))
            time.sleep(2)
            continue
        return Screen.accountSelect

    newEntry : AccountData = {
        "alias" : alias,
        "email" : email,
        "password" : password
    }
    storedAccounts.append(newEntry)

    accountCredentialsDir = "Config/Account Credentials/"
    dirExists = os.path.isdir(accountCredentialsDir)
    if not dirExists:
        try:
            os.makedirs(accountCredentialsDir)
        except PermissionError:
            debugger.exception("No permission to create Config/Account Credentials/ directory")
            yIndex += 2
            msg1 = _centeredLine(stdscr, pad, yIndex, "Config/Account Credentials directory does not exist and insufficient "
            "permission to create a new one. Please create the directory yourself or run "
            "the program with higher authority.")
            yIndex += 1
            msg2 = _centeredLine(stdscr, pad, yIndex, "Enter to exit.")
            _waitForKey(stdscr, pad, ctx, transcript, yIndex, extra=(msg1, msg2))
            return Screen.exit
        except Exception as e:
            debugger.exception("Unexpected error creating Config/Account Credentials/ directory")
            yIndex += 2
            msg1 = _centeredLine(stdscr, pad, yIndex, "Unexpected error occured when trying to create a directory to store the credentials.")
            yIndex += 1
            msg2 = _centeredLine(stdscr, pad, yIndex, f"Error {e}")
            yIndex += 1
            msg3 = _centeredLine(stdscr, pad, yIndex, "Press enter to exit.")
            _renderFrame(stdscr, pad, ctx, transcript, yIndex, extra=(msg1, msg2, msg3))
            return Screen.exit

    tempLoc = tempfile.NamedTemporaryFile(mode="w",dir=accountCredentialsDir, delete=False, encoding="utf-8")
    json.dump(storedAccounts,tempLoc, indent=4)
    tempLoc.close()
    os.replace(tempLoc.name, accountCredentialsDir + "account_credentials.json")

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
    """Centers text against the terminal's actual width (not the pad's). Returns the next free row."""
    _, maxX = stdscr.getmaxyx()
    x = max(0, (maxX - len(text)) // 2)
    pad.addstr(y, x, text[:max(0, maxX - x)], attr)
    return y + 1

def centeredX(stdscr : curses.window, text : str) -> int:
    """Column to center this text at. For live-editable text, compute once from a
    fixed-length anchor string and reuse it - recomputing each redraw shifts the
    line as the buffer grows/shrinks."""
    _, maxX = stdscr.getmaxyx()
    return max(0, (maxX - len(text)) // 2)

def drawTextAt(stdscr : curses.window,
               pad : curses.window,
               y : int,
               x : int,
               text : str,
               attr : int = curses.A_NORMAL) -> int:
    """Writes text at a fixed column instead of recentering it. Returns the next free row."""
    _, maxX = stdscr.getmaxyx()
    pad.addstr(y, x, text[:max(0, maxX - x)], attr)
    return y + 1

def _figletLines(text : str, font : str = "standard") -> List[str]:
    # width=1000 disables pyfiglet's 80-col auto-wrap (would otherwise garble longer banners).
    return pyfiglet.Figlet(font=font, width=1000).renderText(text).rstrip("\n").split("\n")

def figletLineCount(text : str, font : str = "standard") -> int:
    """Row count a banner would take, without drawing it (for layout before rendering)."""
    return len(_figletLines(text, font))

def drawCenteredBanner(stdscr : curses.window,
                       pad : curses.window,
                       y : int,
                       text : str,
                       font : str = "standard",
                       attr : int = curses.A_NORMAL) -> int:
    """Renders pyfiglet ASCII-art, each line centered against the terminal's
    current width (re-read every call, so it re-centers on resize). Returns
    the next free row."""
    _, maxX = stdscr.getmaxyx()
    lines = _figletLines(text, font)
    for i, line in enumerate(lines):
        x = max(0, (maxX - len(line)) // 2)
        pad.addstr(y + i, x, line[:max(0, maxX - x)], attr)
    return y + len(lines)

def _centeredLine(stdscr : curses.window,
                  pad : curses.window,
                  y : int,
                  text : str,
                  attr : int = curses.A_NORMAL) -> DrawFn:
    """A draw closure for one centered line, for use in a transcript/extra list."""
    return lambda: drawCenteredText(stdscr, pad, y, text, attr)

def _fixedLine(stdscr : curses.window,
              pad : curses.window,
              y : int,
              x : int,
              text : str,
              attr : int = curses.A_NORMAL) -> DrawFn:
    """A draw closure for one fixed-column line, for use in a transcript/extra list."""
    return lambda: drawTextAt(stdscr, pad, y, x, text, attr)

def _renderFrame(stdscr : curses.window,
                 pad : curses.window,
                 ctx : Context,
                 transcript : Sequence[DrawFn],
                 bottomY : int,
                 extra : Sequence[DrawFn] = ()) -> None:
    """Redraws the whole screen from scratch: background texture, then every
    committed line, then any transient (not-yet-committed) lines on top.
    Called on every idle tick as well as every keystroke, so the texture's
    per-regen scatter never leaves previously drawn text unredrawn beneath it."""
    pad.erase()
    drawBackgroundTexture(stdscr, pad, ctx)
    for draw in transcript:
        draw()
    for draw in extra:
        draw()
    determineRefreshWindow(stdscr, pad, bottomY)

def _waitForKey(stdscr : curses.window,
                pad : curses.window,
                ctx : Context,
                transcript : Sequence[DrawFn],
                bottomY : int,
                extra : Sequence[DrawFn] = ()) -> int:
    """Blocks until a real key is pressed, but redraws the full frame on every
    idle poll tick in the meantime so the background texture keeps animating."""
    pad.timeout(INPUT_POLL_MS)
    try:
        while True:
            _renderFrame(stdscr, pad, ctx, transcript, bottomY, extra)
            ch = pad.getch()
            if ch != -1:
                return ch
    finally:
        pad.timeout(-1)

def _readLine(stdscr : curses.window,
             pad : curses.window,
             ctx : Context,
             transcript : List[DrawFn],
             y : int,
             prompt : str,
             mask : bool = False) -> str | None:
    """Reads one line of input, redrawing the full transcript + background
    texture on every poll tick (not just on keypress) so the texture keeps
    animating while idle without corrupting already-committed text. On Enter,
    appends the finished prompt+value to the transcript and returns it. On
    ESC, leaves the transcript untouched and returns None."""
    x = centeredX(stdscr, prompt)
    buf : List[str] = []
    pad.timeout(INPUT_POLL_MS)
    try:
        while True:
            shown = ('*' * len(buf)) if mask else ''.join(buf)
            live = _fixedLine(stdscr, pad, y, x, f"{prompt}{shown}")
            _renderFrame(stdscr, pad, ctx, transcript, y, extra=(live,))
            ch = pad.getch()
            if ch == -1:
                continue
            if ch in (curses.KEY_ENTER, ord('\n')):
                break
            elif ch == 27:
                return None
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                if buf:
                    buf.pop()
            elif ch == curses.KEY_MOUSE:
                # Clicks/scroll are global mouse events, not typed input - drain and ignore.
                try:
                    curses.getmouse()
                except curses.error:
                    pass
            elif 32 <= ch <= 126:
                # Only plain printable ASCII - excludes KEY_MOUSE/arrows/function keys, which
                # otherwise decode via chr() into stray characters landing in the buffer.
                buf.append(chr(ch))
    finally:
        pad.timeout(-1)

    result = ''.join(buf)
    shown = ('*' * len(result)) if mask else result
    transcript.append(_fixedLine(stdscr, pad, y, x, f"{prompt}{shown}"))
    return result

def verifyWorker(credentialDict, resultQueue, debugger) -> None:
    try:
        outcome = getAccessAndClientToken(credentialDict, debugger)
    except Exception as e:
        debugger.exception("Unexpected error verifying account")
        outcome = (False, "UNEXPECTED_ERROR", f"Unexpected error: {e}")
    resultQueue.put(outcome)
