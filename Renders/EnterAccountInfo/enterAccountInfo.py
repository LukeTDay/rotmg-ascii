from Constants.Screen import Screen
from Utils.json.accCredLoader import credential_loader
from authentication.getAccessAndClientToken import getAccessAndClientToken

import curses, json, time, os, tempfile, threading, queue
from typing import List


def enterAccountInfo(stdscr : curses.window, ctx) -> Screen:
    try:
        storedAccounts = credential_loader()
    except FileNotFoundError:
        storedAccounts = []

    stdscr.erase()
    pad = curses.newpad(100,150)
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
        pad.addstr(yIndex,0,"If you would like to exit and select an already stored account please press ESC")
        determineRefreshWindow(stdscr,pad,yIndex)
        yIndex += 1
        pad.addstr(yIndex,0,"**If your account_credentials.json does not exist or is empty you will be redirected back here directly**")
        determineRefreshWindow(stdscr,pad,yIndex)
        yIndex += 2
    if not canSelect:
        pad.addstr(yIndex,0, "You do not have any accounts stored.")
        yIndex += 1
        pad.addstr(yIndex, 0, "You must input an account to move forward")
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
                        xIndex=0,
                        )    
        if email == None and canSelect:
            return Screen.accountSelect
        if email == None and not canSelect:
            yIndex += 1
            pad.addstr(yIndex, 0, "You do not have any other accounts stored you must input a new one")
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
                            yIndex=yIndex,
                            xIndex=0)
        if pass1 is None and canSelect:
            return Screen.accountSelect
        yIndex += 2
        pass2 = getPassword(stdscr,
                            pad=pad,
                            questionToAsk="Confirm your password     ",
                            yIndex=yIndex,
                            xIndex=0)
        if pass2 is None and canSelect: 
            return Screen.accountSelect

        if pass1 == pass2:
            password = pass1
            assert password is not None, "Password should never be None here"
            break
        else:
            yIndex += 1
            pad.addstr(yIndex,0,"Password's did not match")
            determineRefreshWindow(stdscr,pad,yIndex)
            yIndex += 1
            pad.addstr(yIndex,0,"Press any key to retry or ESC to select another account")
            determineRefreshWindow(stdscr,pad,yIndex)
            ch = pad.getch()
            if ch == 27:
                if len(storedAccounts) == 0:
                    yIndex += 2
                    pad.addstr(yIndex,0,"You currently have no accounts locally stored you must input one to continue")
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

    thread = threading.Thread(target=verifyWorker, args=(credentialDict, resultQueue), daemon=True)
    thread.start()

    buf : List[str] = []
    while thread.is_alive():
        pad.move(yIndex,0)
        pad.clrtobot()
        pad.addstr(yIndex,0,f"Verifying ROTMG account{''.join(buf)}")
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
        if errReason == "TOKEN_ERROR":
            pad.clrtobot()
            pad.addstr(yIndex,0, "There was an issue loading your token")
            yIndex += 1
            pad.addstr(yIndex,0,f"Incorrect email or password")
            determineRefreshWindow(stdscr,pad,yIndex)
        elif errReason == "VERIFY_TOKEN_ERROR":
            pad.clrtobot()
            pad.addstr(yIndex,0, "There was an issue verifying your token")
            yIndex += 1
            pad.addstr(yIndex,0,f"Error Message: {errText}")
            determineRefreshWindow(stdscr,pad,yIndex)
        elif errReason == "UNEXPECTED_ERROR":
            pad.clrtobot()
            pad.addstr(yIndex,0, "There was an unexpected error")
            yIndex += 1
            pad.addstr(yIndex,0,f"Error Message: {errText}")
            determineRefreshWindow(stdscr,pad,yIndex)
        yIndex += 2
        pad.addstr(yIndex,0,"Please press any key to try again.")
        determineRefreshWindow(stdscr,pad,yIndex)
        pad.getch()
        return Screen.enterAccountInfo
    
    pad.clrtobot()
    pad.addstr(yIndex,0, "Account successfully verified.")
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
            xIndex=0
        )
        if alias == "":
            yIndex += 1
            pad.addstr(yIndex, 0, "Cannot use an empty alias.")
            determineRefreshWindow(stdscr,pad,yIndex)
            time.sleep(2)
            continue

        if alias is not None:
            shouldRecreate = False
            for account in storedAccounts:
                if account["alias"] == alias:
                    yIndex += 1
                    pad.addstr(yIndex,0,f"{alias} is already in use. You must choose another one")
                    determineRefreshWindow(stdscr,pad,yIndex)
                    time.sleep(2)
                    shouldRecreate = True
                    break
            if shouldRecreate:
                continue
            break

        if len(storedAccounts) == 0:
            yIndex += 1
            pad.addstr(yIndex, 0, "As you do not have any other accounts, you must choose an alias for this one.")
            determineRefreshWindow(stdscr,pad,yIndex)
            time.sleep(2)
            continue
        return Screen.accountSelect

    newEntry = {
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
            yIndex += 2
            pad.addstr(yIndex,0,"Credentials directory does not exist and insufficient "
            "permission to create a new one. Please create the directory yourself or run "
            "the program with higher authority.")
            determineRefreshWindow(stdscr,pad,yIndex)
            yIndex += 1
            pad.addstr(yIndex,0,"Enter to exit.")
            determineRefreshWindow(stdscr,pad,yIndex)
            pad.getch()
            return Screen.exit
        except Exception as e:
            yIndex += 2
            pad.addstr(yIndex,0,"Unexpected error occured when trying to create a directory to store the credentials.")
            determineRefreshWindow(stdscr,pad,yIndex)
            yIndex += 1
            pad.addstr(yIndex,0,f"Error {e}")
            determineRefreshWindow(stdscr,pad,yIndex)
            yIndex += 1
            pad.addstr(yIndex,0,"Press enter to exit.")
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

def getPassword(stdscr : curses.window,
                pad : curses.window,
                questionToAsk : str,
                yIndex : int,
                xIndex : int) -> str | None:
    pad.addstr(yIndex,xIndex,f"{questionToAsk}: ")
    determineRefreshWindow(stdscr,pad,yIndex)

    buf = []
    while True:
        ch = pad.getch()
        if ch in (curses.KEY_ENTER, ord('\n')):
            break
        elif ch == 27:
            return None
        elif ch in (curses.KEY_BACKSPACE, 127):
            if buf:
                buf.pop()
        else:
            buf.append(chr(ch))

        pad.move(yIndex, xIndex)
        pad.clrtobot()
        pad.addstr(yIndex,xIndex,f"{questionToAsk}: {'*' * len(buf)} ")
        determineRefreshWindow(stdscr,pad,yIndex)

    result = ''.join(buf)
    return result

def getEmail(stdscr : curses.window,
                pad : curses.window,
                yIndex : int,
                xIndex : int) -> str | None:
    pad.addstr(yIndex, xIndex, "Please enter your email: ")
    determineRefreshWindow(stdscr,pad,yIndex)

    buf = []
    while True:
        ch = pad.getch()
        if ch in (curses.KEY_ENTER, ord('\n')):
            break
        elif ch == 27:
            return None
        elif ch in (curses.KEY_BACKSPACE, 127):
            if buf:
                buf.pop()
        else:
            buf.append(chr(ch))
        pad.move(yIndex, xIndex)
        pad.clrtobot()
        pad.addstr(yIndex, xIndex, f"Please enter your email: {''.join(buf)}")
        determineRefreshWindow(stdscr,pad,yIndex)
    return ''.join(buf)

def getAlias(stdscr : curses.window,
                pad : curses.window,
                yIndex : int,
                xIndex : int) -> str | None:
    pad.addstr(yIndex, xIndex, "Please enter the alias of this account: ")
    determineRefreshWindow(stdscr,pad,yIndex)

    buf = []
    while True:
        ch = pad.getch()
        if ch in (curses.KEY_ENTER, ord('\n')):
            break
        elif ch == 27:
            return None
        elif ch in (curses.KEY_BACKSPACE, 127):
            if buf:
                buf.pop()
        else:
            buf.append(chr(ch))
        pad.move(yIndex, xIndex)
        pad.clrtobot()
        pad.addstr(yIndex, xIndex, f"Please enter the alias of this account: {''.join(buf)}")
        determineRefreshWindow(stdscr,pad,yIndex)
    return ''.join(buf)

def verifyWorker(credentialDict, resultQueue) -> None:
    try:
        outcome = getAccessAndClientToken(credentialDict)
    except Exception as e:
        outcome = (False, "UNEXPECTED_ERROR", f"Unexpected error: {e}")
    resultQueue.put(outcome)

    


