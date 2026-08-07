from Constants.Screen import Screen
from Utils.json.accCredLoader import credential_loader
from authentication.getAccessAndClientToken import getAccessAndClientToken

import curses, json, time
from typing import List


def enterAccountInfo(stdscr : curses.window, ctx) -> Screen:
    try:
        storedAccounts = credential_loader()
    except FileNotFoundError:
        storedAccounts = {}

    stdscr.erase()
    pad = curses.newpad(100,100)
    pad.keypad(True)

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
        yIndex += 1
        pad.addstr(yIndex,0,"**If your account_credentials.json does not exist or is empty you will be redirected back here directly**")
        yIndex += 2

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
    buf: List[str] = []
    while True:
        if email is None:
            raise RuntimeError("Email is None. This should not be possible")
        if password is None:
            raise RuntimeError("Password is None. This should not be possible")
        pad.move(yIndex,0)
        pad.clrtobot()
        pad.addstr(yIndex,0,f"Verifying ROTMG account{''.join(buf)}")
        determineRefreshWindow(stdscr,pad,yIndex)
        credentialDict = {
            "email" : email,
            "password"  : password
        }
        time.sleep(0.25)
        if len(buf) == 5:
            buf = []
        else:
            buf.append(".")

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



    


