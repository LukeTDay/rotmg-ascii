import socket
import queue
import time

from Models.Context import Context, required
from Networking.Ticker import Ticker
from Networking.Sender import Sender
from Networking.Listener import Listener

PORT = 2050


def connectToGame(ctx: Context, resultQueue: "queue.Queue") -> None:
    """Runs on a daemon thread - opens the game socket and builds the worker
    objects, but never starts their threads or touches ctx/curses itself."""
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    try:
        host = required(ctx.get("CURR_SERVER"), "CURR_SERVER")
        debugger.info(f"Connecting to game server {host}:{PORT}")

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, PORT))
        connectedTime = int(time.time() * 1000)

        incomingQueue: queue.Queue = queue.Queue()
        outgoingQueue: queue.Queue = queue.Queue()
        ticker = Ticker(connectedTime, debugger)
        sender = Sender(sock, outgoingQueue, debugger)
        listener = Listener(sock, incomingQueue, outgoingQueue, ticker, connectedTime, debugger)

        debugger.info(f"Socket connected to {host}:{PORT}")
        resultQueue.put((True, listener, sender, ticker, incomingQueue, outgoingQueue))
    except Exception as e:
        debugger.exception("Failed to connect to game server")
        resultQueue.put((False, str(e)))
