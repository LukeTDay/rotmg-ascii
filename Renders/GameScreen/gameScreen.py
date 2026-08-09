from Constants.Screen import Screen
import Constants.GameIds as GameIds

from Models.Context import Context, required

from Models.GameState import GameState
from Models.PlayerData import PlayerData
from Models.ProjectileStore import ProjectileStore

from Networking.Connect import connectToGame
import Networking.PacketHelper as PacketHelper

from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow, drawCenteredBanner, drawCenteredText

from Utils.json.projectileMapLoader import getProjectileDefinition, projectileMapLoader

import curses, threading, queue, time


def drawGame(stdscr: curses.window, ctx: Context) -> Screen:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Entering gameScreen")

    stdscr.erase()
    pad = curses.newpad(1500, 500)

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
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
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
        debugger.warning(f"Connection to game server failed: {result[1]}")
        pad.move(0, 0)
        pad.clrtobot()
        y = drawCenteredBanner(stdscr, pad, 0, "Failed")
        y = drawCenteredText(stdscr, pad, y + 1, f"Error: {result[1]}")
        y = drawCenteredText(stdscr, pad, y + 2, "Please press any key to try again.")
        determineRefreshWindow(stdscr, pad, y)
        _waitForKey(pad)
        return Screen.charSelect

    _, listener, sender, ticker, incomingQueue, outgoingQueue = result
    debugger.info("Connected to game server, worker threads starting")

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
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
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
                    debugger.info(f"MAPINFO received: {mapName}")
                    load = PacketHelper.createPacket("LOAD")
                    load.charId = required(ctx.get("CURR_CHAR_ID"), "CURR_CHAR_ID")
                    load.isFromArena = False
                    outgoingQueue.put(load)
                elif packetType == "FAILURE":
                    return _handleFailure(stdscr, pad, ctx, event)
                elif packetType == "CREATESUCCESS":
                    debugger.info(f"CREATESUCCESS - handshake complete, objectId={event.objectId}")
                    showAllyShoot = PacketHelper.createPacket("SHOWALLYSHOOT")
                    showAllyShoot.toggle = 0
                    outgoingQueue.put(showAllyShoot)
                    return None
        except queue.Empty:
            pass

        time.sleep(0.25)


def _spawnProjectiles(store: ProjectileStore, projectileMap, ownerObjectType: int, projectileId: int,
                       ownerId: int, bulletId: int, startingPos, baseAngle: float, angleInc: float,
                       numShots: int, damage: int) -> None:
    """Fan out `numShots` bullets starting at `baseAngle`, each subsequent one
    offset by `angleInc` - the server sends one shoot packet per burst, not one
    per bullet. This exact fan formula isn't documented anywhere authoritative
    (see CLAUDE.local.md); it matches every reference implementation's field
    naming (`angle` = first shot, `angleIncrement`/`angleInc` = per-shot step).
    """
    definition = getProjectileDefinition(projectileMap, ownerObjectType, projectileId)
    if definition is None:
        return
    for i in range(max(1, numShots)):
        store.spawn(
            bulletId=bulletId,
            ownerId=ownerId,
            startingPos=startingPos,
            angle=baseAngle + angleInc * i,
            speed=definition.speed,
            damage=damage,
            lifetimeMS=definition.lifetimeMS,
            size=definition.size,
            shotIndex=i,
        )


def _connectedLoop(stdscr: curses.window, pad: curses.window, ctx: Context) -> Screen:
    incomingQueue = required(ctx.get("INCOMINGQUEUE"), "INCOMINGQUEUE")
    listener = required(ctx.get("LISTENER"), "LISTENER")
    state = GameState()
    player = PlayerData()
    projectiles = ProjectileStore()
    projectileMap = projectileMapLoader()

    pad.move(0, 0)
    pad.clrtobot()
    y = drawCenteredBanner(stdscr, pad, 0, "Connected")
    y = drawCenteredText(stdscr, pad, y + 1, "(map rendering not implemented yet)")
    determineRefreshWindow(stdscr, pad, y)

    while True:
        try:
            while True:
                event = incomingQueue.get_nowait()
                if isinstance(event, tuple):
                    continue
                if event.type == "FAILURE":
                    return _handleFailure(stdscr, pad, ctx, event)
                elif event.type == "UPDATE":
                    state.applyUpdate(event)
                    for obj in event.newObjs:
                        if obj.status.objectId == listener.objectId:
                            player.parse(obj)
                elif event.type == "NEWTICK":
                    state.applyNewTick(event)
                    for status in event.statuses:
                        if status.objectId == listener.objectId:
                            player.pos = status.pos
                            player.parseStats(status.stats)
                elif event.type == "SERVERPLAYERSHOOT":
                    _spawnProjectiles(
                        projectiles, projectileMap, event.containerType, 0,
                        event.ownerId, event.bulletId, event.startingPos,
                        event.angle, event.bulletAngle, event.bulletCount, event.damage,
                    )
                elif event.type == "ENEMYSHOOT":
                    owner = state.objects.get(event.ownerId)
                    if owner is not None:
                        _spawnProjectiles(
                            projectiles, projectileMap, owner.objectType, event.bulletType,
                            event.ownerId, event.bulletId, event.startingPos,
                            event.angle, event.angleInc, event.numShots, event.damage,
                        )
        except queue.Empty:
            pass
        projectiles.prune()
        pad.getch()
        time.sleep(0.05)


def _handleFailure(stdscr: curses.window, pad: curses.window, ctx: Context, packet) -> Screen:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.error(f"Disconnected from game server: {packet.errorDescription}")
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
        y = drawCenteredText(stdscr, pad, y + 1, "Your Resources/version.txt is outdated.")
        y = drawCenteredText(stdscr, pad, y, "Update/launch RotMG Exalt so it downloads the latest game files,")
        y = drawCenteredText(stdscr, pad, y, "then close this program and run: python -m Scripts.AssetPipeline.run")
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
