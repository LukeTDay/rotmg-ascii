from Constants.Screen import Screen
from Constants.StatTypes import StatTypes
import Constants.GameIds as GameIds

from Models.Context import Context, PendingReconnectHello, required

from Models.GameState import GameState
from Models.PlayerData import PlayerData
from Models.ProjectileStore import ProjectileStore

from Networking.Connect import connectToGame
import Networking.PacketHelper as PacketHelper
from Networking.Ticker import computeSpeed

from Renders.EnterAccountInfo.enterAccountInfo import determineRefreshWindow, drawCenteredBanner, drawCenteredText
from Renders.backgroundTexture import drawBackgroundTexture
from Renders.GameScreen import bottomPanel, chatPanel, inventoryPanel, itemInfoPeek, uiPanel
from Renders.GameScreen.hitDetection import HitTracker, checkProjectileHits
from Renders.GameScreen.inputRouter import NEXUS_MODE_DIRECT_CONNECT, getNexusMode, isNexusKey
from Renders.GameScreen.mapRenderer import drawFrame
from Renders.GameScreen.movementInput import drainKeys, getFrameMouseEvent, handleMovementInput
from Renders.GameScreen.panelInput import handlePanelInput
from Renders.GameScreen.shootInput import AutoFireState, handleShootInput
from Renders.PauseMenu.pauseMenu import drawPauseMenu

from Utils.json.projectileMapLoader import getProjectileDefinition, projectileMapLoader, resolveShotProjectileIds, wavyParams
from Utils.XML.parseCharList import parseNewCharacterXml

import curses, gc, threading, queue, time

# Target rate, not a fixed delay - the loop sleeps only the remainder after
# its own work. Lowered from 120 to 60: actual per-frame work left almost no
# headroom against the 120fps budget, tripping the over-budget warning
# constantly - movement/network don't depend on render cadence anyway.
FRAME_INTERVAL_SECONDS = 1 / 60

# buildVisibleTiles/shootInput rebuild dicts/lists/packets from scratch every
# frame and every shot, which trips Python's cyclic GC (see Debug/debug.txt
# analysis) at essentially random points relative to the render loop, each
# costing 10-40x a normal frame. GameObject/GameState/ProjectileStore hold no
# back-references, so real reference cycles are rare here - the automatic
# collector was mostly doing wasted scanning. Disabling it and collecting on
# our own schedule (below) turns an unpredictable per-frame stall into one
# bounded pause every 60s, run after this frame's game-affecting work is done.
GC_COLLECT_INTERVAL_SECONDS = 60.0

# Returned by _handshake/_connectedLoop when a RECONNECT was just handled -
# loop back through _establishConnection instead of leaving gameScreen.
# Distinct from None (proceed normally) and an actual Screen (leave for good).
_RECONNECT = object()

# Maps the pause menu is reachable from - matched against CURR_MAP_NAME
# (MapInfoPacket.name), not GameIds.nexus: that gameId is only ever sent in
# the very first HELLO after char select, every later map (including these)
# arrives via a server-assigned gameId echoed back through RECONNECT.
_SAFE_AREAS = {"nexus", "vault", "pet yard", "daily quest room", "grand bazaar"}


def _isSafeArea(ctx: Context) -> bool:
    return ctx.get("CURR_MAP_NAME", "").strip().lower() in _SAFE_AREAS


# The map entered right after finishing the tutorial - reaching it means the
# tutorial is done, ahead of char/list's <Account>/<TDone> actually appearing
# on a later fetch. Real MAPINFO.name is "Exalted Kitchen" (matches "Exalted
# Tutorial" for the tutorial map itself) - not "Oryx's Kitchen" as first
# guessed.
_TUTORIAL_END_MAP = "exalted kitchen"


def drawGame(stdscr: curses.window, ctx: Context) -> Screen:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Entering gameScreen")

    stdscr.erase()
    # Sized to the terminal, not a fixed oversized constant: this pad never
    # scrolls and erases every frame (see mapRenderer.drawFrame), so a bigger
    # pad than the terminal just means erase() clears cells nothing shows -
    # _syncPadSize keeps it matched to the terminal across resizes too.
    maxY, maxX = stdscr.getmaxyx()
    pad = curses.newpad(max(1, maxY), max(1, maxX))

    pad.keypad(True)
    pad.clrtobot()
    pad.nodelay(True)

    # A RECONNECT (see _handleReconnect) loops back to the top instead of
    # returning - same pad, a fresh connection underneath.
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


def _syncPadSize(stdscr: curses.window, pad: curses.window) -> None:
    """Resizes `pad` to match the terminal whenever it's changed, so a full
    pad.erase() never clears more cells than the terminal actually shows."""
    maxY, maxX = stdscr.getmaxyx()
    if pad.getmaxyx() != (maxY, maxX):
        pad.resize(max(1, maxY), max(1, maxX))


def _initialGameId(ctx: Context) -> int:
    """gameId for a fresh (non-reconnect) HELLO. CharData.tutorialDone (from
    char/list's <Account>/<TDone> presence - see CLAUDE.local.md) mirrors a
    real captured account: gameId=tutorial before TDone exists, nexus after."""
    charData = ctx.get("CHARDATA")
    if charData is not None and not charData.tutorialDone:
        return GameIds.tutorial
    return GameIds.nexus


def _establishConnection(stdscr: curses.window, pad: curses.window, ctx: Context) -> Screen | None:
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    resultQueue: queue.Queue = queue.Queue()
    connectThread = threading.Thread(target=connectToGame, args=(ctx, resultQueue), daemon=True)
    connectThread.start()

    buf = []
    while connectThread.is_alive():
        _syncPadSize(stdscr, pad)
        pad.move(0, 0)
        pad.clrtobot()
        drawBackgroundTexture(stdscr, pad, ctx)
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
    hello.gameId = pendingReconnect.gameId if pendingReconnect is not None else _initialGameId(ctx)
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
        _syncPadSize(stdscr, pad)
        pad.move(0, 0)
        pad.clrtobot()
        drawBackgroundTexture(stdscr, pad, ctx)
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
                    if mapName.strip().lower() == _TUTORIAL_END_MAP:
                        charData = ctx.get("CHARDATA")
                        if charData is not None and not charData.tutorialDone:
                            debugger.info("Reached Oryx's Kitchen - marking tutorial done")
                            charData.tutorialDone = True
                    # Popped (not just read) so a later RECONNECT (portal, death,
                    # etc.) within this same session falls through to LOAD below
                    # instead of creating a new character every time.
                    pendingNewChar = ctx.pop("PENDING_NEW_CHAR", None)
                    if pendingNewChar is not None:
                        debugger.info(f"Sending CREATE for classType={pendingNewChar.classType} "
                                      f"isSeasonal={pendingNewChar.isSeasonal}")
                        create = PacketHelper.createPacket("CREATE")
                        create.classType = pendingNewChar.classType
                        create.skinType = 0
                        create.unknownFlag = False
                        create.isSeasonal = pendingNewChar.isSeasonal
                        create.isUpgraded = True
                        outgoingQueue.put(create)
                    else:
                        load = PacketHelper.createPacket("LOAD")
                        load.charId = required(ctx.get("CURR_CHAR_ID"), "CURR_CHAR_ID")
                        load.isFromArena = False
                        outgoingQueue.put(load)
                elif packetType == "FAILURE":
                    return _handleFailure(stdscr, pad, ctx, event)
                elif packetType == "RECONNECT":
                    _handleReconnect(ctx, event)
                    return _RECONNECT
                elif packetType == "NEWCHARACTERINFORMATION":
                    # Sent right after our CREATE, ahead of CREATESUCCESS - adds
                    # the just-made character to CHARLIST/CHARDATA immediately so
                    # it shows up in charSelect without a full re-login.
                    _applyNewCharacterInformation(ctx, event, debugger)
                elif packetType == "CREATESUCCESS":
                    debugger.info(f"CREATESUCCESS - handshake complete, objectId={event.objectId}")
                    # Authoritative charId - covers both the LOAD path (already
                    # matches CURR_CHAR_ID) and the CREATE path (CURR_CHAR_ID was
                    # never set, so any later RECONNECT's LOAD needs it from here).
                    ctx["CURR_CHAR_ID"] = event.charId
                    showAllyShoot = PacketHelper.createPacket("SHOWALLYSHOOT")
                    showAllyShoot.toggle = 0
                    outgoingQueue.put(showAllyShoot)
                    return None
                elif packetType == "ACCOUNTLIST":
                    # Arrives before CREATESUCCESS - must be handled here too, or this phase's filter drops it.
                    _applyAccountList(ctx, event)
        except queue.Empty:
            pass

        time.sleep(0.25)


def _spawnProjectiles(store: ProjectileStore, projectileMap, ownerObjectType: int, projectileIds,
                       ownerId: int, bulletId: int, startingPos, baseAngle: float, angleInc: float,
                       numShots: int, damage: int) -> None:
    """Fans out `numShots` bullets from `baseAngle`, each offset by `angleInc` -
    one shoot packet covers the whole burst, not one per bullet.
    `projectileIds` is per-shot (tiered bows fire a stronger center arrow and
    weaker side arrows); enemy shots repeat the same id for every shot.
    """
    for i in range(max(1, numShots)):
        projectileId = projectileIds[i] if i < len(projectileIds) else projectileIds[-1]
        definition = getProjectileDefinition(projectileMap, ownerObjectType, projectileId)
        if definition is None:
            continue
        amplitude, frequency = wavyParams(definition)
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
            multiHit=definition.multiHit,
            armorPiercing=definition.armorPiercing,
            amplitude=amplitude,
            frequency=frequency,
            # No minDamage/maxDamage here - `damage` above is already the
            # server's own authoritative value for this echoed shot (from
            # SERVERPLAYERSHOOT/ENEMYSHOOT), better than a fresh local roll.
        )


_LOCK_LIST_ID = 0  # AccountListPacket.accountListId - 0 is the lock list, 1 is the ignore list
_LOCK_ACTION_SNAPSHOT = -1
_LOCK_ACTION_REMOVE = 0
_LOCK_ACTION_ADD = 1


def _applyNewCharacterInformation(ctx: Context, event, debugger) -> None:
    parsedChars = parseNewCharacterXml(event.charXML, debugger)
    if not parsedChars:
        debugger.warning("NEWCHARACTERINFORMATION: charXML failed to parse, CHARLIST/CHARDATA left unchanged")
        return

    # May include characters CHARLIST already has (an account with existing
    # characters gets all of them back, not just the new one) - only add ids
    # not already tracked, so an existing character never gets duplicated.
    charList = ctx.setdefault("CHARLIST", [])
    existingIds = {c.charID for c in charList}
    charData = ctx.get("CHARDATA")

    addedIds = []
    for charListEntry in parsedChars:
        if charListEntry.charID in existingIds:
            continue
        charList.append(charListEntry)
        existingIds.add(charListEntry.charID)
        addedIds.append(charListEntry.charID)
        if charData is not None and charListEntry.charID not in charData.charIds:
            charData.charIds.append(charListEntry.charID)

    debugger.info(f"NEWCHARACTERINFORMATION: added charIDs={addedIds} to CHARLIST/CHARDATA "
                  f"({len(parsedChars) - len(addedIds)} already tracked)")


def _reportHpIfPresent(hitTracker: HitTracker, objectId: int, stats, debugger) -> None:
    """Feeds any fresh HPSTAT reading (from an UPDATE's newObjs or a NEWTICK's
    statuses) to HitTracker.checkHpDrop - see hitDetection.HitTracker's
    docstring for why HP-drop watching replaced DAMAGE-packet matching."""
    hpStat = next((s for s in stats if s.statType == StatTypes.HPSTAT), None)
    if hpStat is not None:
        hitTracker.checkHpDrop(objectId, hpStat.statValue, debugger)


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
    hitTracker = HitTracker()

    # See GC_COLLECT_INTERVAL_SECONDS above - confirmed via debug.txt that
    # automatic cyclic GC was the source of the periodic drawFrame spikes.
    gc.disable()
    lastGcCollectTime = time.time()
    debugger.info(f"Cyclic GC disabled for this connection; collecting manually every "
                  f"{GC_COLLECT_INTERVAL_SECONDS:.0f}s instead")

    while True:
        frameStart = time.time()
        _syncPadSize(stdscr, pad)
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
                        _reportHpIfPresent(hitTracker, obj.status.objectId, obj.status.stats, debugger)
                elif event.type == "NEWTICK":
                    state.applyNewTick(event)
                    for status in event.statuses:
                        if status.objectId == listener.objectId:
                            player.pos = status.pos
                            player.parseStats(status.stats)
                            ticker.setSpeed(computeSpeed(player.spd, player.spdBoost, player.condition))
                        _reportHpIfPresent(hitTracker, status.objectId, status.stats, debugger)
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
                elif event.type == "TEXT":
                    chatPanel.recordIncomingText(ctx, event, listener.objectId)
                elif event.type == "ACCOUNTLIST":
                    _applyAccountList(ctx, event)
                elif event.type == "INVRESULT":
                    # Ack/nack for the last INVSWAP/USEITEM sent - unknownBool is a
                    # success flag (confirmed via rotmg_mitm_py, see CLAUDE.local.md).
                    # A successful swap already shows up via the next NEWTICK/UPDATE's
                    # stat deltas; this just logs a silent rejection.
                    if not event.unknownBool:
                        debugger.warning(
                            f"INVRESULT: swap/use REJECTED by server "
                            f"(fromSlot={event.fromSlot} toSlot={event.toSlot})"
                        )
        except queue.Empty:
            pass
        if player.objectId != 0:
            # ownerId must match what shootInput.py/_spawnProjectiles stored
            # on each Projectile (player.objectId, not listener.objectId) -
            # they converge once CREATESUCCESS/the matching UPDATE lands, but
            # player.objectId's own unset default is 0, not listener's -1.
            nowMs = int(time.time() * 1000) - ticker.connectedTime
            checkProjectileHits(projectiles, state, player.objectId, nowMs, outgoingQueue, hitTracker, debugger)
        hitTracker.pruneTimeouts(debugger)
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
        chatLayout = chatPanel.computeChatLayout(maxY, maxX)
        friendsList = ctx.get("FRIENDSLIST", set())
        guildMembers = ctx.get("GUILDMEMBERS", set())
        lockedAccounts = ctx.get("LOCKEDACCOUNTS", set())
        uiPanel.drawPanelFrame(pad, panelLayout)
        inventoryPanel.drawBars(pad, panelLayout, player)
        inventoryPanel.drawInventoryGrid(pad, panelLayout, player)
        peekedObjectType = ctx.setdefault("PEEKED_OBJECT_TYPE", None)
        peekedObjectId = ctx.setdefault("PEEKED_OBJECT_ID", None)
        itemInfoPeek.drawItemInfoPeek(pad, panelLayout, peekedObjectType, projectileMap, state, peekedObjectId)
        bottomPanel.drawBottomPanel(pad, panelLayout, ctx, state, ticker, listener.objectId, friendsList,
                                     guildMembers, lockedAccounts)
        chatPanel.drawChatPanel(pad, chatLayout, ctx)
        determineRefreshWindow(stdscr, pad, 0)
        drawFrameMs = (time.time() - drawFrameStart) * 1000

        keysDrainStart = time.time()
        keys = drainKeys(pad)
        mouseEvent = getFrameMouseEvent(keys)
        keysDrainMs = (time.time() - keysDrainStart) * 1000

        chatInputStart = time.time()
        isTyping = chatPanel.handleChatInput(keys, ctx, outgoingQueue, ticker)
        chatInputMs = (time.time() - chatInputStart) * 1000

        keybinds = ctx.get("KEYBINDS", {})

        if not isTyping and isNexusKey(keys, keybinds):
            # Checked first, ahead of the pause menu, so a panic-nexus in
            # danger is never delayed by anything else this frame.
            if getNexusMode(keybinds) == NEXUS_MODE_DIRECT_CONNECT:
                debugger.info("Nexus key pressed - direct-connect mode, tearing down client-side")
                return _directNexus(ctx)
            # ESCAPE is fire-and-forget - the server answers with a RECONNECT
            # to the Nexus, already handled generically by _handleReconnect/
            # _teardownConnection below (same path a portal/death reconnect
            # takes).
            outgoingQueue.put(PacketHelper.createPacket("ESCAPE"))
            debugger.info("Nexus key pressed - escape mode, sent ESCAPE")

        if not isTyping and 27 in keys:
            if _isSafeArea(ctx):
                result = drawPauseMenu(stdscr, ctx)
                if result is not None:
                    _teardownConnection(ctx)
                    return result
            else:
                chatPanel.pushSystemMessage(
                    ctx, "You must be in a safe area (Nexus, Vault, Pet Yard, Daily Quest Room, "
                         "or Grand Bazaar) to open this menu."
                )
            continue

        movementStart = time.time()
        moveDirection = None if isTyping else handleMovementInput(keys, ticker, state, keybinds)
        movementMs = (time.time() - movementStart) * 1000

        shootStart = time.time()
        if not isTyping:
            handleShootInput(keys, stdscr, ticker, player, outgoingQueue, shootState, moveDirection, debugger,
                              projectileMap, projectiles, mouseEvent, keybinds)
        shootMs = (time.time() - shootStart) * 1000

        panelInputStart = time.time()
        handlePanelInput(mouseEvent, stdscr, ctx, panelLayout, player, state, ticker, listener, outgoingQueue,
                          projectileMap, friendsList, guildMembers, lockedAccounts)
        panelInputMs = (time.time() - panelInputStart) * 1000

        # Run after this frame's packets are already sent/drawn, so the
        # pause never delays a movement/shoot packet - only this frame's sleep.
        gcMs = 0.0
        if time.time() - lastGcCollectTime >= GC_COLLECT_INTERVAL_SECONDS:
            gcStart = time.time()
            collected = gc.collect()
            gcMs = (time.time() - gcStart) * 1000
            lastGcCollectTime = time.time()
            debugger.debug(f"Manual gc.collect() took {gcMs:.1f}ms, collected {collected} unreachable objects")

        elapsed = time.time() - frameStart
        remaining = FRAME_INTERVAL_SECONDS - elapsed
        if remaining < 0:
            # Broken down by sub-step so an overrun is actionable straight
            # from Debug/debug.txt, without needing to reach for py-spy just
            # to find out which of these five is the actual culprit.
            debugger.warning(
                f"Frame took {elapsed * 1000:.1f}ms, over the {FRAME_INTERVAL_SECONDS * 1000:.1f}ms budget "
                f"(queueDrain={queueDrainMs:.1f}ms drawFrame={drawFrameMs:.1f}ms keysDrain={keysDrainMs:.1f}ms "
                f"chatInput={chatInputMs:.1f}ms movementInput={movementMs:.1f}ms shootInput={shootMs:.1f}ms "
                f"panelInput={panelInputMs:.1f}ms gc={gcMs:.1f}ms)"
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
    ctx["PEEKED_OBJECT_ID"] = None
    ctx["SELECTED_SLOT"] = None
    ctx["BOTTOM_PANEL_CYCLE_INDEX"] = 0
    ctx["BOTTOM_PANEL_CANDIDATE_IDS"] = frozenset()


def _directNexus(ctx: Context):
    """NEXUS_MODE_DIRECT_CONNECT: tears the connection down client-side
    immediately instead of sending ESCAPE and waiting for the server's
    RECONNECT reply - faster in a pinch, trusting the client's own state
    instead. No PENDING_RECONNECT_HELLO is set (any stale one is dropped),
    so the next _establishConnection call sends a fresh HELLO with
    gameId=GameIds.nexus/keyTime=0/key=[], exactly like the very first
    connect after server select.

    Confirmed live: reconnecting to whatever CURR_SERVER currently holds
    does NOT reliably work - once the player has gone through any RECONNECT
    (a portal, dying, etc), CURR_SERVER points at that realm/dungeon
    instance's own host, and that host just re-serves its own realm instead
    of honoring gameId=nexus. Only the original server picked in
    serverSelect.py (Context.HOME_SERVER) has been confirmed to actually
    hand back a Nexus - so CURR_SERVER is reset to it here, same host the
    very first connect after server select used.

    Returns the module-level _RECONNECT sentinel for the caller to return
    straight through."""
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Direct-connect nexus: tearing down connection client-side")
    _teardownConnection(ctx)
    ctx.pop("PENDING_RECONNECT_HELLO", None)
    ctx["CURR_SERVER"] = required(ctx.get("HOME_SERVER"), "HOME_SERVER")

    ctx["PEEKED_OBJECT_TYPE"] = None
    ctx["PEEKED_OBJECT_ID"] = None
    ctx["SELECTED_SLOT"] = None
    ctx["BOTTOM_PANEL_CYCLE_INDEX"] = 0
    ctx["BOTTOM_PANEL_CANDIDATE_IDS"] = frozenset()

    return _RECONNECT


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
