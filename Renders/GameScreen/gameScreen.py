from Constants.Screen import Screen
import Constants.GameIds as GameIds

from Models.Context import Context, PendingReconnectHello, required

from Models.GameState import GameState
from Models.PlayerData import PlayerData
from Models.ProjectileStore import ProjectileStore

from Networking.Connect import connectToGame
import Networking.PacketHelper as PacketHelper
from Networking.Ticker import computeSpeed

from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow, drawCenteredBanner, drawCenteredText
from Renders.GameScreen import bottomPanel, inventoryPanel, itemInfoPeek, uiPanel
from Renders.GameScreen.mapRenderer import drawFrame
from Renders.GameScreen.movementInput import drainKeys, getFrameMouseEvent, handleMovementInput
from Renders.GameScreen.panelInput import handlePanelInput
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

# Returned by _handshake/_connectedLoop to mean "a RECONNECT was just handled
# (socket torn down, ctx["PENDING_RECONNECT_HELLO"] set) - loop back through
# _establishConnection instead of leaving gameScreen". Distinct from None
# (proceed to the next stage as normal) and an actual Screen (leave
# gameScreen for good, e.g. FAILURE -> charSelect) - neither of those two
# existing return values can double as this third case.
_RECONNECT = object()


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

    # A RECONNECT (see _handleReconnect) loops back to the top instead of
    # returning - same pad/screen, a fresh connection underneath. Nothing
    # else in this loop needs to change: _establishConnection already draws
    # its own "Connecting..." interstitial, and _handshake/_connectedLoop
    # each recreate their own local state (GameState/PlayerData/etc.) fresh
    # every call.
    while True:
        if ctx.get("LISTENER") is None:
            failure = _establishConnection(stdscr, pad, ctx)
            if failure is not None:
                return failure

        outcome = _handshake(stdscr, pad, ctx)
        if outcome is _RECONNECT:
            continue
        if outcome is not None:
            return outcome

        result = _connectedLoop(stdscr, pad, ctx)
        if result is _RECONNECT:
            continue
        return result


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

    # A RECONNECT (see _handleReconnect) stashes the gameId/keyTime/key the
    # follow-up HELLO must carry instead of a fresh login's nexus/0/[] -
    # popped (not just read) so a later *fresh* connect through this same
    # function - e.g. retrying after a FAILURE bounced back to charSelect -
    # doesn't accidentally reuse a stale reconnect's key material.
    pendingReconnect = ctx.pop("PENDING_RECONNECT_HELLO", None)

    hello = PacketHelper.createPacket("HELLO")
    hello.gameId = pendingReconnect.gameId if pendingReconnect is not None else GameIds.nexus
    hello.buildVersion = required(ctx.get("buildVersion"), "buildVersion")
    hello.accessToken = required(ctx.get("accessToken"), "accessToken")
    hello.keyTime = pendingReconnect.keyTime if pendingReconnect is not None else 0
    hello.key = pendingReconnect.key if pendingReconnect is not None else []
    hello.userPlatform = "rotmg"
    hello.playPlatform = "rotmg"
    hello.userToken = required(ctx.get("clientToken"), "clientToken")
    outgoingQueue.put(hello)

    return None


def _handshake(stdscr: curses.window, pad: curses.window, ctx: Context) -> Screen | None:
    """Returns None on success (proceed to _connectedLoop), a Screen to leave
    gameScreen entirely (FAILURE -> charSelect), or the module-level
    _RECONNECT sentinel if a RECONNECT arrived mid-handshake (rare, but the
    server could in principle bounce a client again before CREATESUCCESS) -
    the caller (drawGame) loops back through _establishConnection either way.
    """
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
                packetType = event.type

                if packetType == "MAPINFO":
                    mapName = event.name
                    ctx["CURR_MAP_NAME"] = mapName
                    debugger.info(f"MAPINFO received: {mapName}")
                    load = PacketHelper.createPacket("LOAD")
                    load.charId = required(ctx.get("CURR_CHAR_ID"), "CURR_CHAR_ID")
                    load.isFromArena = False
                    outgoingQueue.put(load)
                elif packetType == "FAILURE":
                    return _handleFailure(stdscr, pad, ctx, event)
                elif packetType == "RECONNECT":
                    _handleReconnect(ctx, event)
                    return _RECONNECT
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
    """May also return the module-level _RECONNECT sentinel (see drawGame) -
    the type hint stays Screen since Python doesn't enforce it and every
    real caller already checks for the sentinel before treating the result
    as a Screen."""
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
                if event.type == "FAILURE":
                    return _handleFailure(stdscr, pad, ctx, event)
                elif event.type == "RECONNECT":
                    _handleReconnect(ctx, event)
                    return _RECONNECT
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
                elif event.type == "INVRESULT":
                    # The server's ack/nack for the last INVSWAP/USEITEM this
                    # client sent - confirmed (rotmg_mitm_py's BuffAbility
                    # plugin, see CLAUDE.local.md's Reference projects)
                    # unknownBool is a success flag (False = silently
                    # rejected - the swap never happened server-side, no
                    # stat delta will ever follow it) and unknownByte
                    # distinguishes a swap ack (0) from a plain item-use ack
                    # (1). Not needed to actually reflect a *successful*
                    # swap - that already arrives generically via the next
                    # NEWTICK/UPDATE's ordinary INVENTORY*/BACKPACK* stat
                    # deltas (GameState.applyNewTick / PlayerData.parseStats
                    # apply to any tracked object, player or bag, with no
                    # INVSWAP-specific code needed) - logged here purely so
                    # a *rejected* swap is visible in Debug/debug.txt instead
                    # of just silently doing nothing.
                    if not event.unknownBool:
                        debugger.warning(
                            f"INVRESULT: swap/use REJECTED by server "
                            f"(fromSlot={event.fromSlot} toSlot={event.toSlot})"
                        )
        except queue.Empty:
            pass
        projectiles.prune()
        queueDrainMs = (time.time() - queueDrainStart) * 1000

        drawFrameStart = time.time()
        drawFrame(stdscr, pad, state, player, projectiles, listener, ticker, ctx)
        # Panel frame + relocated HUD bars + inventory grid + item-info peek
        # + bottom-panel widget are drawn on top of the same pad drawFrame
        # just drew the map onto - this app composites everything onto one
        # pad per frame, then blits it once (determineRefreshWindow below),
        # not once per drawing step.
        maxY, maxX = stdscr.getmaxyx()
        panelLayout = uiPanel.computePanelLayout(maxY, maxX)
        friendsList = ctx.get("FRIENDSLIST", set())
        guildMembers = ctx.get("GUILDMEMBERS", set())
        lockedAccounts = ctx.get("LOCKEDACCOUNTS", set())
        uiPanel.drawPanelFrame(pad, panelLayout)
        inventoryPanel.drawBars(pad, panelLayout, player)
        inventoryPanel.drawInventoryGrid(pad, panelLayout, player)
        peekedObjectType = ctx.setdefault("PEEKED_OBJECT_TYPE", None)
        itemInfoPeek.drawItemInfoPeek(pad, panelLayout, peekedObjectType, projectileMap)
        bottomPanel.drawBottomPanel(pad, panelLayout, ctx, state, ticker, listener.objectId, friendsList,
                                     guildMembers, lockedAccounts)
        determineRefreshWindow(stdscr, pad, 0)
        drawFrameMs = (time.time() - drawFrameStart) * 1000

        keysDrainStart = time.time()
        keys = drainKeys(pad)
        mouseEvent = getFrameMouseEvent(keys)
        keysDrainMs = (time.time() - keysDrainStart) * 1000

        movementStart = time.time()
        moveDirection = handleMovementInput(keys, ticker, state)
        movementMs = (time.time() - movementStart) * 1000

        shootStart = time.time()
        handleShootInput(keys, stdscr, ticker, player, outgoingQueue, state, shootState, moveDirection, debugger,
                          projectileMap, projectiles, mouseEvent)
        shootMs = (time.time() - shootStart) * 1000

        panelInputStart = time.time()
        handlePanelInput(mouseEvent, stdscr, ctx, panelLayout, player, state, ticker, listener, outgoingQueue,
                          projectileMap, friendsList, guildMembers, lockedAccounts)
        panelInputMs = (time.time() - panelInputStart) * 1000

        elapsed = time.time() - frameStart
        remaining = FRAME_INTERVAL_SECONDS - elapsed
        if remaining < 0:
            # Broken down by sub-step so an overrun is actionable straight
            # from Debug/debug.txt, without needing to reach for py-spy just
            # to find out which of these five is the actual culprit.
            debugger.warning(
                f"Frame took {elapsed * 1000:.1f}ms, over the {FRAME_INTERVAL_SECONDS * 1000:.1f}ms budget "
                f"(queueDrain={queueDrainMs:.1f}ms drawFrame={drawFrameMs:.1f}ms keysDrain={keysDrainMs:.1f}ms "
                f"movementInput={movementMs:.1f}ms shootInput={shootMs:.1f}ms panelInput={panelInputMs:.1f}ms)"
            )
        time.sleep(max(0.0, remaining))


def _teardownConnection(ctx: Context) -> None:
    """Stops the 3 worker threads, closes the socket, and clears the 5
    connection-related ctx keys - shared by _handleFailure (leaves
    gameScreen for charSelect) and _handleReconnect (loops back through
    _establishConnection instead, see drawGame)."""
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


def _handleReconnect(ctx: Context, packet) -> None:
    """A RECONNECT means the server wants this client on a different game
    instance - e.g. after sending USEPORTAL, or after dying/entering the
    Nexus - possibly the same physical server (packet.host/.name empty) or a
    genuinely different one. Mirrors pyrelay's Client.onReconnect/connect
    (see CLAUDE.local.md's Reference projects): only overwrite the stored
    server host when the packet actually names one, and always replace
    gameId/keyTime/key unconditionally for the follow-up HELLO. Tears the
    current connection down; the caller (_handshake/_connectedLoop) is
    responsible for returning the _RECONNECT sentinel so drawGame's loop
    re-enters _establishConnection instead of leaving gameScreen.
    """
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info(f"RECONNECT: moving to {packet.name!r} (host={packet.host!r})")
    _teardownConnection(ctx)

    if packet.host:
        ctx["CURR_SERVER"] = packet.host
    ctx["PENDING_RECONNECT_HELLO"] = PendingReconnectHello(packet.gameId, packet.keyTime, packet.key)

    # Stale references to objects on the map being left behind - clear so
    # the new map's panel starts clean instead of pointing at ids that won't
    # resolve to anything once the old GameState is discarded.
    ctx["PEEKED_OBJECT_TYPE"] = None
    ctx["SELECTED_SLOT"] = None
    ctx["BOTTOM_PANEL_CYCLE_INDEX"] = 0
    ctx["BOTTOM_PANEL_CANDIDATE_IDS"] = frozenset()


def _handleFailure(stdscr: curses.window, pad: curses.window, ctx: Context, packet) -> Screen:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.error(f"Disconnected from game server: {packet.errorDescription}")
    _teardownConnection(ctx)

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
