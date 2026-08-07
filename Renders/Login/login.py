from Constants.Screen import Screen
from Constants.ApiPoints import *

from Utils.XML.parserServersXML import parseServersXML

from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow, verifyWorker

import curses, threading, queue, time, requests
from typing import List, Dict

def drawLogin(stdscr : curses.window, ctx) -> Screen:
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
    currentAccount = ctx["account"]
    alias = currentAccount["alias"]
    email = currentAccount["email"]
    password = currentAccount["password"]

    resultQueue = queue.Queue()
    tokenThread = threading.Thread(target=verifyWorker, args=(ctx["account"], resultQueue), daemon=True)
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

    for x in range(len(threadList)):
        yIndex += 2
        result = groupQueue.get()
        if not result[0]:
            pad.addstr(yIndex,0,f"There was an error receiving {result[1]}")
            yIndex += 1
            pad.addstr(yIndex,0,f"Error: {result[2]}")
        elif result[0]:
            pad.addstr(yIndex, 0, f"Recevied {result[1]}")
            ctx[result[1]] = parseServersXML(result[2])
            #yIndex += 1
            #pad.addstr(yIndex, 0, f"Data {result[2].text}")
        determineRefreshWindow(stdscr,pad,yIndex)
        


    while True:
        pad.getch() # Temp to pause program

def checkThreads(threadList : List[threading.Thread]) -> bool:
    result = True
    for thread in threadList:
        if thread.is_alive():
            return False
    return result


    

def gatherData(ctx : Dict[str,str],
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


def gatherFriend(ctx : Dict[str, str], queue : queue.Queue):
    try:
        outcome = requests.post(url=FRIENDSLIST, params={"accessToken" : ctx["accessToken"]})
    except Exception as e:
        outcome = (False, FRIENDSLIST, "UNEXPECTED_ERROR", f"Unexpected Error: {e}")
    queue.put((True, "FRIENDSLIST", outcome))

def gatherGuild(ctx : Dict[str, str], queue : queue.Queue):
    try:
        outcome = requests.post(url=GUILDMEMBERS, params={"accessToken" : ctx["accessToken"]})
    except Exception as e:
        outcome = (False, "GUILDMEMBERS", "UNEXPECTED_ERROR", f"Unexpected Error: {e}")
    queue.put((True, "GUILDMEMBERS", outcome))

def gatherChar(ctx : Dict[str, str], queue : queue.Queue):
    try:
        outcome = requests.post(url=CHAR, params={"accessToken" : ctx["accessToken"]})
    except Exception as e:
        outcome = (False, "CHARLIST", "UNEXPECTED_ERROR", f"Unexpected Error: {e}")
    queue.put((True, "CHARLIST", outcome))

def gatherServer(ctx : Dict[str, str], queue : queue.Queue):
    try:
        outcome = requests.post(url=SERVERS, params={"accessToken" : ctx["accessToken"]})
    except Exception as e:
        outcome = (False, "SERVERS", "UNEXPECTED_ERROR", f"Unexpected Error: {e}")
    queue.put((True, "SERVERS", outcome))
    


    