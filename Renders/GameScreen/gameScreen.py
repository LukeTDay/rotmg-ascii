from Constants.Screen import Screen
import Constants.GameIds as GameIds

from Models.Context import Context, required

from Models.GameState import GameState
from Models.PlayerData import PlayerData
from Models.ProjectileStore import ProjectileStore

from Networking.Connect import connectToGame
import Networking.PacketHelper as PacketHelper
from Networking.Ticker import computeSpeed

from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow, drawCenteredBanner, drawCenteredText
from Renders.GameScreen.mapRenderer import drawFrame
from Renders.GameScreen.movementInput import drainKeys, handleMovementInput
from Renders.GameScreen.shootInput import AutoFireState, handleShootInput

from Utils.json.projectileMapLoader import getProjectileDefinition, projectileMapLoader, resolveShotProjectileIds

import curses, threading, queue, time

# Target render-loop cadence for _connectedLoop, once past the handshake -
# tunable. The loop below times how long each iteration's own work (queue
# drain/apply, draw, input) actually took and only sleeps the remainder, so
# this is a target rate, not an on-top-of-everything-else fixed delay.
#
# Lowered from 120 to 60 (2026-08-10): actual per-frame work is ~4-7ms
# (see the drawFrame/frame-time breakdown logging below), leaving almost no
# headroom against the old 8.3ms/120fps budget - routine variance tripped
# the over-budget warning constantly. Movement (Ticker) dead-reckons on its
# own independent 60Hz clock regardless of this value, and network handling
# doesn't depend on render cadence either, so this only affects how often
# the screen visually redraws - not gameplay responsiveness. Also halves
# total drawFrame/refresh/input-polling CPU load, not just the budget.
FRAME_INTERVAL_SECONDS = 1 / 60


def drawGame(stdscr: curses.window, ctx: Context) -> Screen:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Entering gameScreen")

    stdscr.erase()
    # Unlike every other screen's 1500-row pad (sized generously for a long
    # *scrollable* list, erased/recreated at most once per screen visit),
    # this screen never scrolls - determineRefreshWindow is always called
    # with yIndex=0 (see drawFrame) - and pad.erase() runs on every single
    # frame, up to 120/sec. A 1500-row pad here was just copied from the
    # other screens without revisiting that cost. 500 matches the column
    # dimension's already-proven-safe generous sizing (see CLAUDE.md - a
    # too-narrow pad has caused real addstr() crashes before) while still
    # being a third of the original row count.
    pad = curses.newpad(500, 500)

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
                elif packetType == "ACCOUNTLIST":
                    # Sent right after login, before CREATESUCCESS - handled
                    # here too, not just in _connectedLoop's dispatch,
                    # otherwise this phase's narrow MAPINFO/FAILURE/
                    # CREATESUCCESS-only filter silently drops it.
                    _applyAccountList(ctx, event)
        except queue.Empty:
            pass

        time.sleep(0.25)


def _spawnProjectiles(store: ProjectileStore, projectileMap, ownerObjectType: int, projectileIds,
                       ownerId: int, bulletId: int, startingPos, baseAngle: float, angleInc: float,
                       numShots: int, damage: int) -> None:
    """Fan out `numShots` bullets starting at `baseAngle`, each subsequent one
    offset by `angleInc` - the server sends one shoot packet per burst, not one
    per bullet. This exact fan formula isn't documented anywhere authoritative
    (see CLAUDE.local.md); it matches every reference implementation's field
    naming (`angle` = first shot, `angleIncrement`/`angleInc` = per-shot step).

    `projectileIds` is a list, one entry per shot index - not every shot in a
    weapon's own fan necessarily uses the same projectile type (tiered bows
    fire a stronger center arrow and weaker side arrows, two distinct
    `<Projectile>` definitions on the same weapon - see
    Utils.json.projectileMapLoader.resolveShotProjectileIds). Enemy shots
    always pass the same single id repeated for every shot (their own
    `bulletType` selects one specific attack for the whole burst).
    """
    for i in range(max(1, numShots)):
        projectileId = projectileIds[i] if i < len(projectileIds) else projectileIds[-1]
        definition = getProjectileDefinition(projectileMap, ownerObjectType, projectileId)
        if definition is None:
            continue
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
            visualObjectType=definition.visualObjectType,
        )


_LOCK_LIST_ID = 0  # AccountListPacket.accountListId - 0 is the lock list, 1 is the ignore list
_LOCK_ACTION_SNAPSHOT = -1
_LOCK_ACTION_REMOVE = 0
_LOCK_ACTION_ADD = 1


def _applyAccountList(ctx: Context, event) -> None:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info(
        f"ACCOUNTLIST received: accountListId={event.accountListId} "
        f"lockAction={event.lockAction} accountIds={event.accountIds}"
    )
    if event.accountListId != _LOCK_LIST_ID:
        return  # e.g. the ignore list - not relevant to rendering
    locked = ctx.setdefault("LOCKEDACCOUNTS", set())
    if event.lockAction == _LOCK_ACTION_SNAPSHOT:
        locked.clear()
        locked.update(event.accountIds)
    elif event.lockAction == _LOCK_ACTION_ADD:
        locked.update(event.accountIds)
    elif event.lockAction == _LOCK_ACTION_REMOVE:
        locked.difference_update(event.accountIds)


def _connectedLoop(stdscr: curses.window, pad: curses.window, ctx: Context) -> Screen:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    incomingQueue = required(ctx.get("INCOMINGQUEUE"), "INCOMINGQUEUE")
    outgoingQueue = required(ctx.get("OUTGOINGQUEUE"), "OUTGOINGQUEUE")
    listener = required(ctx.get("LISTENER"), "LISTENER")
    ticker = required(ctx.get("TICKER"), "TICKER")
    state = GameState()
    player = PlayerData()
    projectiles = ProjectileStore()
    projectileMap = projectileMapLoader()
    shootState = AutoFireState()

    while True:
        frameStart = time.time()
        queueDrainStart = frameStart
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
                            ticker.setSpeed(computeSpeed(player.spd, player.spdBoost, player.condition))
                elif event.type == "NEWTICK":
                    state.applyNewTick(event)
                    for status in event.statuses:
                        if status.objectId == listener.objectId:
                            player.pos = status.pos
                            player.parseStats(status.stats)
                            ticker.setSpeed(computeSpeed(player.spd, player.spdBoost, player.condition))
                elif event.type == "SERVERPLAYERSHOOT":
                    numShots = max(1, event.bulletCount)
                    _spawnProjectiles(
                        projectiles, projectileMap, event.containerType,
                        resolveShotProjectileIds(projectileMap, event.containerType, numShots),
                        event.ownerId, event.bulletId, event.startingPos,
                        event.angle, event.bulletAngle, numShots, event.damage,
                    )
                elif event.type == "ENEMYSHOOT":
                    owner = state.objects.get(event.ownerId)
                    if owner is not None:
                        numShots = max(1, event.numShots)
                        _spawnProjectiles(
                            projectiles, projectileMap, owner.objectType, [event.bulletType] * numShots,
                            event.ownerId, event.bulletId, event.startingPos,
                            event.angle, event.angleInc, numShots, event.damage,
                        )
                elif event.type == "ACCOUNTLIST":
                    _applyAccountList(ctx, event)
        except queue.Empty:
            pass
        projectiles.prune()
        queueDrainMs = (time.time() - queueDrainStart) * 1000

        drawFrameStart = time.time()
        drawFrame(stdscr, pad, state, player, projectiles, listener, ticker, ctx)
        drawFrameMs = (time.time() - drawFrameStart) * 1000

        keysDrainStart = time.time()
        keys = drainKeys(pad)
        keysDrainMs = (time.time() - keysDrainStart) * 1000

        movementStart = time.time()
        moveDirection = handleMovementInput(keys, ticker, state)
        movementMs = (time.time() - movementStart) * 1000

        shootStart = time.time()
        handleShootInput(keys, stdscr, ticker, player, outgoingQueue, state, shootState, moveDirection, debugger,
                          projectileMap, projectiles)
        shootMs = (time.time() - shootStart) * 1000

        elapsed = time.time() - frameStart
        remaining = FRAME_INTERVAL_SECONDS - elapsed
        if remaining < 0:
            # Broken down by sub-step so an overrun is actionable straight
            # from Debug/debug.txt, without needing to reach for py-spy just
            # to find out which of these five is the actual culprit.
            debugger.warning(
                f"Frame took {elapsed * 1000:.1f}ms, over the {FRAME_INTERVAL_SECONDS * 1000:.1f}ms budget "
                f"(queueDrain={queueDrainMs:.1f}ms drawFrame={drawFrameMs:.1f}ms keysDrain={keysDrainMs:.1f}ms "
                f"movementInput={movementMs:.1f}ms shootInput={shootMs:.1f}ms)"
            )
        time.sleep(max(0.0, remaining))


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
