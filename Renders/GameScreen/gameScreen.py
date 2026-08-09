from Constants.Screen import Screen
import Constants.GameIds as GameIds

from Models.Context import Context, required

from Networking.Connect import connectToGame
import Networking.PacketHelper as PacketHelper

from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow, drawCenteredBanner, drawCenteredText

import curses, threading, queue, time


def drawGame(stdscr: curses.window, ctx: Context) -> Screen:
    stdscr.erase()
    pad = curses.newpad(1500, 150)

    pad.keypad(True)
    pad.clrtobot()
    pad.nodelay(True)

    if ctx.get("LISTENER") is None:
        failure = _establishConnection(stdscr, pad, ctx)
        if failure is not None:
            return failure

    outcome = _handshake(stdscr, pad, ctx)
    if outcome is not None:
        return outcome

    return _connectedLoop(stdscr, pad, ctx)


def _establishConnection(stdscr: curses.window, pad: curses.window, ctx: Context) -> Screen | None:
    resultQueue: queue.Queue = queue.Queue()
    connectThread = threading.Thread(target=connectToGame, args=(ctx, resultQueue), daemon=True)
    connectThread.start()

    buf = []
    while connectThread.is_alive():
        pad.move(0, 0)
        pad.clrtobot()
        y = drawCenteredBanner(stdscr, pad, 0, "Connecting")
        y = drawCenteredText(stdscr, pad, y + 1, f"to server{''.join(buf)}")
        determineRefreshWindow(stdscr, pad, y)
        time.sleep(0.25)
        if len(buf) == 5:
            buf = []
        else:
            buf.append(".")

    result = resultQueue.get()
    if not result[0]:
        pad.move(0, 0)
        pad.clrtobot()
        y = drawCenteredBanner(stdscr, pad, 0, "Failed")
        y = drawCenteredText(stdscr, pad, y + 1, f"Error: {result[1]}")
        y = drawCenteredText(stdscr, pad, y + 2, "Please press any key to try again.")
        determineRefreshWindow(stdscr, pad, y)
        _waitForKey(pad)
        return Screen.charSelect

    _, listener, sender, ticker, incomingQueue, outgoingQueue = result

    ctx["TICKER"] = ticker
    ctx["LISTENER"] = listener
    ctx["SENDER"] = sender
    ctx["INCOMINGQUEUE"] = incomingQueue
    ctx["OUTGOINGQUEUE"] = outgoingQueue

    threading.Thread(target=ticker.start, daemon=True).start()
    threading.Thread(target=listener.start, daemon=True).start()
    threading.Thread(target=sender.start, daemon=True).start()

    hello = PacketHelper.createPacket("HELLO")
    hello.gameId = GameIds.nexus
    hello.buildVersion = required(ctx.get("buildVersion"), "buildVersion")
    hello.accessToken = required(ctx.get("accessToken"), "accessToken")
    hello.keyTime = 0
    hello.key = []
    hello.userPlatform = "rotmg"
    hello.playPlatform = "rotmg"
    hello.userToken = required(ctx.get("clientToken"), "clientToken")
    outgoingQueue.put(hello)

    return None


def _handshake(stdscr: curses.window, pad: curses.window, ctx: Context) -> Screen | None:
    incomingQueue = required(ctx.get("INCOMINGQUEUE"), "INCOMINGQUEUE")
    outgoingQueue = required(ctx.get("OUTGOINGQUEUE"), "OUTGOINGQUEUE")
    mapName = ""

    while True:
        pad.move(0, 0)
        pad.clrtobot()
        y = drawCenteredBanner(stdscr, pad, 0, "Connecting")
        y = drawCenteredText(stdscr, pad, y + 1, f"to {mapName}..." if mapName else "...")
        determineRefreshWindow(stdscr, pad, y)

        try:
            while True:
                event = incomingQueue.get_nowait()

                if isinstance(event, tuple):
                    _, mapName = event
                    continue

                packetType = event.type
                if packetType == "MAPINFO":
                    mapName = event.name
                    load = PacketHelper.createPacket("LOAD")
                    load.charId = required(ctx.get("CURR_CHAR_ID"), "CURR_CHAR_ID")
                    load.isFromArena = False
                    outgoingQueue.put(load)
                elif packetType == "FAILURE":
                    return _handleFailure(stdscr, pad, ctx, event)
                elif packetType == "CREATESUCCESS":
                    return None
        except queue.Empty:
            pass

        time.sleep(0.25)


def _connectedLoop(stdscr: curses.window, pad: curses.window, ctx: Context) -> Screen:
    incomingQueue = required(ctx.get("INCOMINGQUEUE"), "INCOMINGQUEUE")

    pad.move(0, 0)
    pad.clrtobot()
    y = drawCenteredBanner(stdscr, pad, 0, "Connected")
    y = drawCenteredText(stdscr, pad, y + 1, "(map rendering not implemented yet)")
    determineRefreshWindow(stdscr, pad, y)

    while True:
        try:
            while True:
                event = incomingQueue.get_nowait()
                if not isinstance(event, tuple) and event.type == "FAILURE":
                    return _handleFailure(stdscr, pad, ctx, event)
        except queue.Empty:
            pass
        pad.getch()
        time.sleep(0.05)


def _handleFailure(stdscr: curses.window, pad: curses.window, ctx: Context, packet) -> Screen:
    listener = ctx.get("LISTENER")
    sender = ctx.get("SENDER")
    ticker = ctx.get("TICKER")

    if listener is not None:
        listener.stop()
        try:
            listener.sock.close()
        except OSError:
            pass
    if sender is not None:
        sender.stop()
    if ticker is not None:
        ticker.stop()

    for key in ("LISTENER", "SENDER", "TICKER", "INCOMINGQUEUE", "OUTGOINGQUEUE"):
        if key in ctx:
            del ctx[key]

    pad.move(0, 0)
    pad.clrtobot()
    y = drawCenteredBanner(stdscr, pad, 0, "Disconnected")
    if packet.errorDescription == "s.update_client":
        y = drawCenteredText(stdscr, pad, y + 1, "Your gameVersion.txt is outdated.")
        y = drawCenteredText(stdscr, pad, y, "Close this program and update it manually with the correct version.")
    else:
        y = drawCenteredText(stdscr, pad, y + 1, f"Error: {packet.errorDescription}")
    y = drawCenteredText(stdscr, pad, y + 2, "Please press any key to continue.")
    determineRefreshWindow(stdscr, pad, y)
    _waitForKey(pad)
    return Screen.charSelect


def _waitForKey(pad: curses.window) -> None:
    pad.nodelay(False)
    pad.getch()
    pad.nodelay(True)
