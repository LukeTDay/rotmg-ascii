from Constants.Screen import Screen

from Models.Context import Context

from Networking.Ticker import Ticker
from Networking.Listener import Listener
from Networking.Sender import Sender

import curses, threading, queue

def drawGame(stdscr : curses.window, ctx : Context) -> Screen:
    #Erasing the screen before making the pad
    stdscr.erase()
    pad = curses.newpad(1500 ,150)

    pad.keypad(True)
    pad.clrtobot()
    pad.nodelay(True)

    
    if ctx.get("LISTENER") is None:
        outgoingQueue = queue.Queue()
        ctx["OUTGOINGQUEUE"] = outgoingQueue

        incomingQueue = queue.Queue()
        ctx["INCOMINGQUEUE"] = incomingQueue

        #This 
        ticker = Ticker()
        tickerThread = threading.Thread(target=ticker.start, daemon=True)
        tickerThread.start()
        ctx["TICKER"] = ticker

        listener = Listener()
        listenerThread = threading.Thread(target=listener.start, daemon=True)
        listenerThread.start()
        ctx["LISTENER"] = listener

        sender = Sender()
        senderThread = threading.Thread(target=sender.start, daemon=True)
        senderThread.start()
        ctx["SENDER"] = sender



    while True:
        pad.getch()