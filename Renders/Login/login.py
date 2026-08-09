from Constants.Screen import Screen
from Constants.ApiPoints import *

from Utils.XML.parseServersXML import parseServersXML
from Utils.XML.parseCharList import parseCharList
from Utils.XML.parseFriendsList import parseFriendsList
from Utils.XML.parseGuildmembers import parseGuildMembers

from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow, verifyWorker
from Models.Context import Context, required

import curses, threading, queue, time, requests,os
from typing import List

def drawLogin(stdscr : curses.window, ctx : Context) -> Screen:
    """
    The goal of this screen is to give the user something 
    to look at while all of their information is fetched
    from backend API endpoints.
    """

    #Erasing the screen before making the pad
    stdscr.erase()
    pad = curses.newpad(1500 ,150)

    pad.keypad(True)
    pad.clrtobot()

    #yIndex for printing to the pad throughout the function
    yIndex = 0

    pad.addstr(yIndex,0,"Checking ")
    determineRefreshWindow(stdscr,pad,yIndex)

    #Loading the account so that it can be verified
    currentAccount = required(ctx.get("account"), "account")

    resultQueue = queue.Queue()
    tokenThread = threading.Thread(target=verifyWorker, args=(currentAccount, resultQueue), daemon=True)
    tokenThread.start()

    buf : List[str] = []
    while tokenThread.is_alive():
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
        return Screen.accountSelect
    
    pad.clrtobot()
    pad.addstr(yIndex,0, "Account successfully verified.")
    determineRefreshWindow(stdscr,pad,yIndex)

    ctx["accessToken"] = success[1][0]
    ctx["clientToken"] = success[1][1]

    with open("gameVersion.txt", "r", encoding="utf-8") as f:
        ctx["buildVersion"] = f.read().strip()

    yIndex += 2

    groupQueue = queue.Queue()
    threadList = gatherData(ctx, groupQueue)

    while checkThreads(threadList): 
        pad.move(yIndex,0)
        pad.clrtobot()
        pad.addstr(yIndex,0,f"Gathering the rest of the data{''.join(buf)}")
        determineRefreshWindow(stdscr,pad,yIndex)
        time.sleep(0.25)
        if len(buf) == 5:
            buf = []
        else:
            buf.append(".")
    moveOn = True
    for x in range(len(threadList)):
        yIndex += 2
        result = groupQueue.get()
        if not result[0]:
            pad.addstr(yIndex,0,f"There was an error receiving {result[1]}")
            yIndex += 1
            pad.addstr(yIndex,0,f"Error: {result[2]}")
            moveOn = False
        elif result[0]:
            pad.addstr(yIndex, 0, f"Recevied {result[1]}")
            parseHandler(ctx, result)
        determineRefreshWindow(stdscr,pad,yIndex)

    time.sleep(2)

    if moveOn:
        return Screen.charSelect
    else:
        yIndex += 2
        pad.addstr(yIndex,0,"There was an error when fetching information about your account. Exiting to account selection")
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
    match result[1]:
        case "FRIENDSLIST":
            ctx["FRIENDSLIST"] = parseFriendsList(result[2])
        case "GUILDMEMBERS":
            ctx["GUILDMEMBERS"] = parseGuildMembers(result[2])
        case "CHARLIST":
            ctx["CHARLIST"] = parseCharList(result[2])
        case "SERVERS":
            ctx["SERVERS"] = parseServersXML(result[2])

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
        outcome = (False, FRIENDSLIST, "UNEXPECTED_ERROR", f"Unexpected Error: {e}")
    queue.put((True, "FRIENDSLIST", outcome))

def gatherGuild(ctx : Context, queue : queue.Queue):
    try:
        outcome = requests.post(url=GUILDMEMBERS, params={"accessToken" : required(ctx.get("accessToken"), "accessToken")})
    except Exception as e:
        outcome = (False, "GUILDMEMBERS", "UNEXPECTED_ERROR", f"Unexpected Error: {e}")
    queue.put((True, "GUILDMEMBERS", outcome))

def gatherChar(ctx : Context, queue : queue.Queue):
    try:
        outcome = requests.post(url=CHAR, params={"accessToken" : required(ctx.get("accessToken"), "accessToken")})
    except Exception as e:
        outcome = (False, "CHARLIST", "UNEXPECTED_ERROR", f"Unexpected Error: {e}")
    queue.put((True, "CHARLIST", outcome))

def gatherServer(ctx : Context, queue : queue.Queue):
    try:
        outcome = requests.post(url=SERVERS, params={"accessToken" : required(ctx.get("accessToken"), "accessToken")})
    except Exception as e:
        outcome = (False, "SERVERS", "UNEXPECTED_ERROR", f"Unexpected Error: {e}")
    queue.put((True, "SERVERS", outcome))
    


    