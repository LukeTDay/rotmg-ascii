from Constants.Screen import Screen
from Constants.ApiPoints import *

from Utils.XML.parseServersXML import parseServersXML
from Utils.XML.parseCharList import parseCharList
from Utils.XML.parseFriendsList import parseFriendsList
from Utils.XML.parseGuildmembers import parseGuildMembers

from Renders.EnterAccountInfo.enterAccountInfo import centeredX, determineRefreshWindow, drawCenteredBanner, drawCenteredText, drawTextAt, verifyWorker
from Models.Context import Context, required

import curses, threading, queue, time, requests,os
from typing import List

def drawLogin(stdscr : curses.window, ctx : Context) -> Screen:
    """Screen shown while account/friends/guild/char/server data is fetched."""

    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Entering login screen")

    stdscr.erase()
    pad = curses.newpad(1500 ,500)

    pad.keypad(True)
    pad.clrtobot()

    yIndex = drawCenteredBanner(stdscr, pad, 0, "Checking")
    determineRefreshWindow(stdscr,pad,yIndex)

    currentAccount = required(ctx.get("account"), "account")

    resultQueue = queue.Queue()
    tokenThread = threading.Thread(target=verifyWorker, args=(currentAccount, resultQueue, debugger), daemon=True)
    tokenThread.start()

    verifyingTextX = centeredX(stdscr, "ROTMG account.....")
    buf : List[str] = []
    while tokenThread.is_alive():
        pad.move(0,0)
        pad.clrtobot()
        yIndex = drawCenteredBanner(stdscr, pad, 0, "Verifying")
        yIndex = drawTextAt(stdscr, pad, yIndex + 1, verifyingTextX, f"ROTMG account{''.join(buf)}")
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
        debugger.warning(f"Login verify failed ({errReason}): {errText}")
        pad.move(0,0)
        pad.clrtobot()
        if errReason == "TOKEN_ERROR":
            yIndex = drawCenteredBanner(stdscr, pad, 0, "Token Error")
            yIndex = drawCenteredText(stdscr, pad, yIndex + 1, "Incorrect email or password")
        elif errReason == "VERIFY_TOKEN_ERROR":
            yIndex = drawCenteredBanner(stdscr, pad, 0, "Verify Error")
            yIndex = drawCenteredText(stdscr, pad, yIndex + 1, f"Error Message: {errText}")
        elif errReason == "UNEXPECTED_ERROR":
            yIndex = drawCenteredBanner(stdscr, pad, 0, "Error")
            yIndex = drawCenteredText(stdscr, pad, yIndex + 1, f"Error Message: {errText}")
        else:
            yIndex = 0
        yIndex = drawCenteredText(stdscr, pad, yIndex + 2, "Please press any key to try again.")
        determineRefreshWindow(stdscr,pad,yIndex)
        pad.getch()
        return Screen.accountSelect

    debugger.info("Account token verified")
    pad.move(0,0)
    pad.clrtobot()
    yIndex = drawCenteredBanner(stdscr, pad, 0, "Verified")
    determineRefreshWindow(stdscr,pad,yIndex)

    ctx["accessToken"] = success[1][0]
    ctx["clientToken"] = success[1][1]

    with open("Resources/version.txt", "r", encoding="utf-8") as f:
        ctx["buildVersion"] = f.read().strip()

    groupQueue = queue.Queue()
    threadList = gatherData(ctx, groupQueue)

    gatheringTextX = centeredX(stdscr, "the rest of the data.....")
    buf = []
    while checkThreads(threadList):
        pad.move(0,0)
        pad.clrtobot()
        yIndex = drawCenteredBanner(stdscr, pad, 0, "Gathering")
        yIndex = drawTextAt(stdscr, pad, yIndex + 1, gatheringTextX, f"the rest of the data{''.join(buf)}")
        determineRefreshWindow(stdscr,pad,yIndex)
        time.sleep(0.25)
        if len(buf) == 5:
            buf = []
        else:
            buf.append(".")
    moveOn = True
    for x in range(len(threadList)):
        yIndex += 1
        result = groupQueue.get()
        if not result[0]:
            yIndex = drawCenteredText(stdscr, pad, yIndex, f"There was an error receiving {result[1]}")
            yIndex = drawCenteredText(stdscr, pad, yIndex, f"Error: {result[2]}")
            moveOn = False
        elif result[0]:
            yIndex = drawCenteredText(stdscr, pad, yIndex, f"Received {result[1]}")
            parseHandler(ctx, result)
        determineRefreshWindow(stdscr,pad,yIndex)

    time.sleep(2)

    if moveOn:
        debugger.info("Login complete - proceeding to charSelect")
        return Screen.charSelect
    else:
        debugger.warning("Login data gathering failed - returning to accountSelect")
        yIndex = drawCenteredText(stdscr, pad, yIndex + 2, "There was an error when fetching information about your account. Exiting to account selection")
        determineRefreshWindow(stdscr,pad,yIndex)
        time.sleep(3)
        return Screen.accountSelect

def checkThreads(threadList : List[threading.Thread]) -> bool:
    result = True
    for thread in threadList:
        if thread.is_alive():
            return False
    return result

def parseHandler(ctx : Context, result) -> None:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    match result[1]:
        case "FRIENDSLIST":
            ctx["FRIENDSLIST"] = parseFriendsList(result[2], debugger)
        case "GUILDMEMBERS":
            ctx["GUILDMEMBERS"] = parseGuildMembers(result[2], debugger)
        case "CHARLIST":
            ctx["CHARLIST"] = parseCharList(result[2], debugger)
        case "SERVERS":
            ctx["SERVERS"] = parseServersXML(result[2], debugger)

def gatherData(ctx : Context,
               queue : queue.Queue) -> List[threading.Thread]:
    friendThread = threading.Thread(target=gatherFriend,args=(ctx, queue), daemon=True)
    guildThread  = threading.Thread(target=gatherGuild,args=(ctx, queue), daemon=True)
    charThread   = threading.Thread(target=gatherChar,args=(ctx, queue), daemon=True)
    serverThread = threading.Thread(target=gatherServer,args=(ctx, queue), daemon=True)
    friendThread.start()
    guildThread.start()
    charThread.start()
    serverThread.start()
    return [friendThread,guildThread,charThread,serverThread]

def gatherFriend(ctx : Context, queue : queue.Queue):
    try:
        outcome = requests.post(url=FRIENDSLIST, params={"accessToken" : required(ctx.get("accessToken"), "accessToken")})
    except Exception as e:
        required(ctx.get("DEBUGGER"), "DEBUGGER").exception("Failed to fetch FRIENDSLIST")
        outcome = (False, FRIENDSLIST, "UNEXPECTED_ERROR", f"Unexpected Error: {e}")
    queue.put((True, "FRIENDSLIST", outcome))

def gatherGuild(ctx : Context, queue : queue.Queue):
    try:
        outcome = requests.post(url=GUILDMEMBERS, params={"accessToken" : required(ctx.get("accessToken"), "accessToken")})
    except Exception as e:
        required(ctx.get("DEBUGGER"), "DEBUGGER").exception("Failed to fetch GUILDMEMBERS")
        outcome = (False, "GUILDMEMBERS", "UNEXPECTED_ERROR", f"Unexpected Error: {e}")
    queue.put((True, "GUILDMEMBERS", outcome))

def gatherChar(ctx : Context, queue : queue.Queue):
    try:
        outcome = requests.post(url=CHAR, params={"accessToken" : required(ctx.get("accessToken"), "accessToken")})
    except Exception as e:
        required(ctx.get("DEBUGGER"), "DEBUGGER").exception("Failed to fetch CHARLIST")
        outcome = (False, "CHARLIST", "UNEXPECTED_ERROR", f"Unexpected Error: {e}")
    queue.put((True, "CHARLIST", outcome))

def gatherServer(ctx : Context, queue : queue.Queue):
    try:
        outcome = requests.post(url=SERVERS, params={"accessToken" : required(ctx.get("accessToken"), "accessToken")})
    except Exception as e:
        required(ctx.get("DEBUGGER"), "DEBUGGER").exception("Failed to fetch SERVERS")
        outcome = (False, "SERVERS", "UNEXPECTED_ERROR", f"Unexpected Error: {e}")
    queue.put((True, "SERVERS", outcome))
    


    