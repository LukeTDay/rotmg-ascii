# CLAUDE.md

Guidance for Claude Code when working in this repo.

## What this is

A terminal ASCII client for Realm of the Mad God, built against the **real** RotMG account/game servers (not a private server). It logs into a real account, pulls char/friends/guild/server data over HTTP, then opens a live game-protocol socket connection and renders actual gameplay — movement, collision, enemies, projectiles, other players — as curses ASCII art.

## Role

- Purpose here is **research and small, targeted changes** — investigate, explain, make minor edits.
- Leave most writing/implementation to the user. Don't take on large or open-ended work unprompted.

## Code style

- **Comments: keep them short.** No overly verbose or wordy comments — a single terse line only when the *why* isn't obvious from the code itself.

## Running

```
pip install -r requirements.txt
python main.py
```

- No test suite, linter, or build step yet.
- Deps: `requests`, `pyfiglet` (banner text), and `windows-curses` on Windows only (native `curses` isn't available there).
- `Scripts/AssetPipeline/` has its own `requirements.txt` (`UnityPy`, `Pillow`, `flatbuffers`) — only needed to run the asset pipeline, kept out of the root file.

## How the app fits together

`main.py` is the entire loop: a `screen: Screen` variable (`Constants/Screen.py`), a `handlers` dict mapping each `Screen` to a draw function, and one shared `ctx: Context` dict passed by reference to every screen. Each iteration calls `handlers[screen](stdscr, ctx)`, gets back the next `Screen`, and repeats until `Screen.exit`. There is no other state-passing mechanism in the app — if you're looking for where some piece of state lives, it's either a local in the screen currently running, or a key in `ctx`.

The rest of this file walks the directory tree, folder by folder, explaining what each file is for and what its key functions do.

---

## `main.py`

Entry point. Builds the `Debugger`, registers every curses color pair (see `Constants/ColorPairs.py` below) via `curses.init_pair()`, builds the initial `ctx`, and runs the screen loop described above inside `curses.wrapper(...)`. The outer `try/except` exists because `curses.wrapper` already restores the terminal before re-raising — so on a crash it's safe to just `traceback.print_exc()` normally instead of dumping a raw traceback over a half-torn-down terminal.

---

## `Constants/`

Small, mostly-static lookup tables and enums. No logic to speak of — just data other modules import.

- **`Screen.py`** — the `Screen` enum (`accountSelect`, `enterAccountInfo`, `login`, `charSelect`, `serverSelect`, `gameScreen`, `exit`) that drives `main.py`'s state machine.
- **`ApiPoints.py`** — every real `realmofthemadgod.com` HTTP endpoint this app calls (`VERIFY`, `CHAR`, `SERVERS`, `FRIENDSLIST`, `GUILDMEMBERS`, etc.), plus the Unity `User-Agent`/`X-Unity-Version` headers needed to look like the real client.
- **`ClassIds.py`** — numeric `objectType` ↔ display-name maps for character classes. `idToClass(id)` / `classToId(name)`.
- **`ColorPairs.py`** — every curses color-pair *number* used in the app (menu pairs, `MAP_*` pairs for the map renderer, `FILL_*` pairs for HUD bars, `SELECTED_VARIANT` for highlighted rows). The pairs themselves are registered once in `main.py`; this file is just the numbering.
- **`GameIds.py`** — special map ids sent in the `HELLO` handshake (`nexus`, `vault`, `randomRealm`, etc.).
- **`PacketIds.py`** — `idToType` / `typeToId`: the wire packet-id byte ↔ packet type name (`"PING"`, `"UPDATE"`, ...) mapping, used by `Networking/Listener.py` and `Networking/Sender.py`.
- **`Servers.py`** — a hardcoded server name ↔ IP table. Largely superseded by the live `account/servers` HTTP endpoint (`Utils/XML/parseServersXML.py`), kept around as a fallback/reference.
- **`StatTypes.py`** — the `StatTypes` class: every numeric player/object stat id (`HPSTAT`, `LEVELSTAT`, `NAMESTAT`, ...) the game protocol sends. `nameOf(statType)` reverse-looks-up the id back to its constant name for debugging.
- **`StatusEffects.py`** — numeric condition-effect bit ids (`SLOWED`, `DAZED`, `BERSERK`, `PARALYZED`, ...), consumed via `Models/ConditionEffect.hasEffect(condition, *effects)`.

---

## `Models/`

The app's core in-memory data structures — player stats, live game state, the map renderer, and the shared `ctx` dict's type definition.

- **`Context.py`** — defines `Context` (a `TypedDict(total=False)`) and `AccountData`. Every key ever stored in `ctx` is declared here (`account`, `accessToken`, `CHARLIST`, `TICKER`, `INCOMINGQUEUE`, `RNG`, `TILE_CHAR_CACHE`, etc.). `required(ctx.get("key"), "key")` asserts a key is non-`None` and narrows its type — use this instead of `ctx["key"]` anywhere a key is guaranteed present by that point in the flow but is still `Optional` in the type system.
- **`PlayerData.py`** — the local player's full stat block (HP/MP, ATK/DEF/SPD/DEX/VIT/WIS, inventory, guild, exaltations, potions, ...). `parse(obj)` reads an initial `CREATESUCCESS`/`UPDATE` object; `parseStats(stats)` is a big `StatTypes`-keyed if/elif chain applying incremental stat updates from `NEWTICK`.
- **`GameState.py`** — `GameObject` (one live entity: position, stats, and enough history to interpolate motion) and `GameState` (the single source of truth for every tracked object + ground tile, owned solely by the render thread). `applyUpdate`/`applyNewTick` mutate it from incoming packets. `GameObject.renderPos(now)` interpolates between the last two *observed* positions for smooth between-tick rendering (deliberately interpolates rather than extrapolates — see the docstring for why extrapolation was tried and reverted).
- **`TileManager.py`** — turns `GameState` + `ProjectileStore` into what actually gets drawn each frame.
  - `buildVisibleTiles(...)` — rebuilds the visible tile window from scratch every frame (not incrementally synced): buckets every in-range object/projectile by tile, then resolves one `RenderCell` (char + color) per tile via the render-hierarchy precedence below.
  - `classifyObject(...)` — single-pass tier classification: `Self > Enemy > Loot bag > Projectile > Wall > Portal > Interactive NPC > Other player (friend/guild/locked only) > Floor`. Anything matching no tier is excluded entirely, not drawn as a lower one.
  - `isTileBlocked(state, blockedTiles, tileX, tileY)` — movement-collision check shared with rendering's WALL tier, so both always agree on what's impassable. Takes a precomputed `blockedTiles` set (see `buildBlockedTileIndex` below) rather than scanning `state.objects` itself.
  - `buildBlockedTileIndex(state)` — one O(n) pass over `state.objects` producing the `{(tileX, tileY)}` set `isTileBlocked` checks against. Built once per movement-input frame in `movementInput.handleMovementInput` so its up-to-3 per-frame collision queries don't each rescan every object from scratch.
  - `_pickChar(...)` — picks between a multi-glyph tile's texture variants, cached per-tile in `ctx["TILE_CHAR_CACHE"]` so the choice doesn't flicker every frame.
- **`ProjectileStore.py`** — client-side-simulated in-flight bullets (RotMG never re-sends a projectile's position after the shot packet). `Projectile.posAt(now)` computes current position from `startingPos`/`angle`/`speed`; `ProjectileStore.spawn`/`remove`/`prune` manage the store, keyed by `(ownerId, bulletId, shotIndex)`. No client-side hit detection yet — `prune()` only removes expired bullets, never ones that actually hit something (see its docstring TODO).
- **`CharData.py`** — a small, currently-lightly-used holder for char-list metadata (`charIds`, `nextCharId`, `maxNumChars`).
- **`CharListData.py`** — one parsed `<Char>` entry from `char/list` (id, class, fame, level, equipment, seasonal/crucible flags) — what `charSelect.py` displays per character slot.
- **`ConditionEffect.py`** — `hasEffect(condition, *effects)`: bitmask test against `Constants/StatusEffects.py`'s ids, used by `Ticker.computeSpeed`, `shootInput._attackPeriodMs`, and anywhere else a condition bit needs checking.
- **`GroundTypeData.py`** — plain dataclass-style holder for one ground type's gameplay data (`speed`, `minDamage`/`maxDamage`, `noWalk`, `sink`) — see `Utils/XML/parseGroundTypes.py` for where it's populated from.

---

## `Data/`

Wire-format structs for the game protocol — every class here follows the same shape: `read(reader)` / `write(writer)` (binary (de)serialization via `Networking/Reader.py`/`Writer.py`), and usually `clone()`. These are the building blocks packet classes in `Networking/Packets/` assemble into full packets.

- **`WorldPosData.py`** — an (x, y) world position. `dist`/`squareDist`/`distTo` for distance math, `clone()`, operator `__add__`.
- **`StatData.py`** — one `(statType, value)` pair as sent on the wire. `isStringStat()` decides whether `statValue` (int) or `strStatValue` (string) is the live field for a given `statType`.
- **`ObjectData.py`** / **`ObjectStatusData.py`** — a full object as sent in an `UPDATE`/`NEWTICK`: `ObjectData` wraps an `objectType` + `ObjectStatusData`; `ObjectStatusData` is `objectId` + `WorldPosData` + a list of `StatData`.
- **`GroundTileData.py`** — one `(x, y, groundType)` tile entry, as sent in `UPDATE`'s tile list.
- **`MoveRecord.py`** — one `(time, pos)` sample sent back to the server in a `MOVE` packet, sourced from `Ticker.drainRecords()`.
- **`FameData.py`, `PartyData.py`, `PartyPlayerData.py`, `QuestData.py`, `SlotObjectData.py`, `TradeItem.py`** — smaller wire structs for features not yet wired into the render/input layer (fame stats, parties, quests, trading, inventory slots). Same `read`/`write`/`clone` shape as above; consulted by the relevant packet classes in `Networking/Packets/` but nothing in `Renders/` reads them yet.

---

## `Networking/`

Everything that talks to the game socket, plus the packet protocol layer itself. See `CLAUDE.local.md`/git history for the concurrency model in depth; summary below.

- **`Connect.py`** — `connectToGame(ctx, resultQueue)`: opens the TCP socket (real game server, port 2050) and constructs the `Ticker`/`Sender`/`Listener` trio, but does **not** start their threads or touch `ctx`/curses itself — that's `gameScreen.py`'s job once this returns successfully.
- **`Listener.py`** — owns the socket's *read* side. `start()` loops on `recv()`, decodes each packet, and for a handful of latency-critical types replies immediately from this thread rather than waiting on the render loop: `PING`→`PONG`, `UPDATE`→`UPDATEACK`, `GOTO`→`GOTOACK`, `SERVERPLAYERSHOOT`→`SHOOTACK` (if it's this client's own shot), `ENEMYSHOOT`→`ENEMYSHOOTACK`, `NEWTICK`→ a `MOVE` built from `Ticker.drainRecords()`. Tracks `self.objectId` (from `CREATESUCCESS`) so it knows which events are about the local player. Forwards every decoded packet onto the incoming queue too — except `RECONNECT`, which becomes a `("connecting", mapName)` tuple instead (the listener thread can't cleanly tear itself down mid-`recv()`).
- **`Sender.py`** — owns the socket's *write* side. Blocks on `outgoingQueue.get()`, RC4-encrypts, `sendall`s. The only thing that ever calls `send()` on the game socket.
- **`Ticker.py`** — local movement dead-reckoning on its own steady 60Hz timer, independent of the network/render loop. `computeSpeed(spd, spdBoost, condition)` is RotMG's real movement-speed formula. `setPos`/`setTarget`/`setSpeed`/`drainRecords` are its thread-safe entry points, called respectively by `Listener` (authoritative position), `movementInput` (keyboard target), `gameScreen`/`shootInput` (stat resync), and `Listener` again (per-`NEWTICK` flush).
- **`PacketHelper.py`** — `createPacket(packetType)`: the single entry point for instantiating a packet class by its string type name (`"PING"`, `"MOVE"`, ...). Raises `ValueError` for an unregistered type.
- **`Reader.py`** / **`Writer.py`** — low-level binary framing primitives (`readInt32`, `writeStr`, `readCompressedInt`, `writeCompressedInt`, ...) every packet's `read()`/`write()` method calls into. Not game-specific — just RotMG's wire format.

### `Networking/Packets/`

- **`Packet.py`** — base `Packet` class: `read(reader)`/`write(writer)` no-ops for subclasses to override, plus a `send` flag and a debug `__str__`.
- **`PacketTypes.py`** — builds `packet_dict` (type name → class) by scanning everything `Incoming/__init__.py`/`Outgoing/__init__.py` expose.
- **`Incoming/`, `Outgoing/`** — one file per packet type (~85 incoming, ~50 outgoing — e.g. `NewTickPacket.py`, `PlayerShootPacket.py`, `UpdatePacket.py`), each just a `Packet` subclass defining that packet's specific fields and `read`/`write`. **Registration is fully automatic**: `__init__.py` in each folder `importlib`-imports every `.py` file in the directory and exposes the same-named class, so dropping a new packet file in is enough to wire it up — no manual registration step, no list to update.

---

## `Renders/`

Where the main files handling rendering reside — one subfolder per `Screen`, each exporting a `draw<ScreenName>(stdscr, ctx) -> Screen` function that `main.py` calls each loop iteration.

### `EnterAccountInfo/enterAccountInfo.py`

Interactive curses form for entering a new account's email/password/alias, verifying it against the real API before saving. Also the home of the small helper functions **every other screen imports**:

- `determineRefreshWindow(stdscr, pad, yIndex)` — computes the pad's visible scroll slice against the terminal's actual size and calls `pad.refresh(...)`. Every screen's redraw loop ends with this.
- `drawCenteredText(stdscr, pad, y, text, attr)` — writes one line centered against the terminal's *actual* width (not the pad's fixed width), returns the next free row.
- `centeredX(stdscr, text)` — returns the column a given piece of text would need to start at to be centered, without drawing anything.
- `drawTextAt(stdscr, pad, y, x, text, attr)` — writes text at a fixed column instead of recentering it. Paired with `centeredX`: for text that gets redrawn every keystroke (live email/password input echo), compute `x` once from a fixed-length anchor string and keep reusing it — recentering from the live (growing/shrinking) buffer every frame would make the whole line visibly jitter as you type.
- `drawCenteredBanner(stdscr, pad, y, text, font, attr)` — renders big block-letter text via `pyfiglet`, each line centered, returns the next free row.
- `figletLineCount(text, font)` — row count a banner would take up, without drawing it (for laying out content around a banner before rendering it).
- `verifyWorker(credentialDict, resultQueue, debugger)` — background-thread helper: calls `authentication/getAccessAndClientToken.py` and puts the tagged-tuple result on a queue. Shared by this screen and `Login/login.py`.

### `AccountSelect/accountSelect.py`

Lists saved accounts from `Credentials/account_credentials.json` (scrollable, arrow/WASD navigation), lets the user pick one (→ `Screen.login`) or add a new one (→ `Screen.enterAccountInfo`).

### `Login/login.py`

Re-verifies the selected account's token, then fans out 4 daemon threads (`gatherFriend`/`gatherGuild`/`gatherChar`/`gatherServer`) hitting `FRIENDSLIST`/`GUILDMEMBERS`/`CHAR`/`SERVERS` in parallel while the main thread redraws a loading spinner. `parseHandler` routes each result to its `Utils/XML/parse*.py` parser and stores it in `ctx`.

### `CharSelect/charSelect.py`

Lists the account's characters (sorted by fame, scrollable), colored by seasonal/crucible/standard status. `_buildEquipmentRow`/`_equipSlotText` resolve each character's first 4 equipment slots to item names via `Utils/json/objectNameLoader.objectIdToName`. Selecting a character sets `ctx["CURR_CHAR_ID"]` and moves to `Screen.serverSelect`.

### `ServerSelect/serverSelect.py`

Grid of server names (from `ctx["SERVERS"]`) plus two navigation buttons, 2-column keyboard-navigable layout. Selecting a server sets `ctx["CURR_SERVER"]` and moves to `Screen.gameScreen`.

### `GameScreen/`

The actual live-gameplay screen — by far the most involved part of the app.

- **`gameScreen.py`** — `drawGame` runs the connection in 3 stages: `_establishConnection` (opens the socket, starts the `Ticker`/`Sender`/`Listener` threads, sends `HELLO`), `_handshake` (drains packets until `CREATESUCCESS`, replying to `MAPINFO` with `LOAD`), then `_connectedLoop` — the real game loop: drains the incoming queue, applies `UPDATE`/`NEWTICK`/`SERVERPLAYERSHOOT`/`ENEMYSHOOT`/`ACCOUNTLIST` events to `GameState`/`PlayerData`/`ProjectileStore`, calls `mapRenderer.drawFrame`, then `movementInput.handleMovementInput` and `shootInput.handleShootInput`. Frame-time-aware pacing (`FRAME_INTERVAL_SECONDS = 1/120`): times its own work and only sleeps the remainder, logging a warning if a frame overruns budget. `_handleFailure` tears down all 3 worker threads/queues on disconnect and bounces back to `Screen.charSelect`.
- **`mapRenderer.py`** — turns `TileManager.buildVisibleTiles`'s output into actual `pad.addstr()` calls, plus the HP/MP/Fame HUD.
  - `computeScale(stdscr)` — figures out how much world to show and at what per-tile size: grows the view radius to fill available terminal space first (up to `VIEW_RADIUS_TILES`), only magnifying tile size once that cap is hit. Returns `(scaleX, scaleY, mapAreaRows, mapAreaCols, viewRadius)`.
  - `screenToWorld(stdscr, ticker, screenRow, screenCol)` — inverse of the map's tile placement; turns a mouse event's screen coordinates into a world position (used by `shootInput.py` for mouse aiming).
  - `_drawMap` — writes each visible tile's glyph as a `scaleX × scaleY` block of characters.
  - `_drawBar` / `_drawSolidBar` — HP/MP proportional bars and the Fame solid box, text rendered *inside* the bar.
  - `drawFrame(...)` — the per-frame entry point `gameScreen.py` calls: centers on `ticker.pos` (not `player.pos`, which only updates on `NEWTICK`), nudges the local player's `GameState` entry to match, builds the visible-tile dict, draws map + HUD, refreshes the pad.
- **`movementInput.py`** — keyboard movement + wall/ground collision.
  - `drainKeys(pad)` — drains every pending keypress this frame into a list (shared between this and `shootInput.py`, since curses' input buffer only yields each key once).
  - `handleMovementInput(keys, ticker, state)` — resolves this frame's movement direction (last directional key on non-Windows; real physical key state via `_pollHeldDirection` on Windows, enabling true diagonal movement), builds a `TileManager.buildBlockedTileIndex` once, then nudges `Ticker`'s target one tile further unless the tile ahead is blocked — checked per-axis so a diagonal move blocked on one side still slides along the other.
  - `_pollHeldDirection` (Windows only) — reads `GetAsyncKeyState` directly, gated by a recent real `getch()` event as a focus proxy (see the function's docstring for why two more "obvious" focus-detection approaches were tried and reverted).
- **`shootInput.py`** — mouse aiming + auto-fire.
  - `AutoFireState` — small per-connection dataclass (`autoFire`, `lastShotTime`, `nextShotId`, `lastMouseWorld`, `lastMoveDirection`).
  - `_attackPeriodMs(player, rateOfFire)` — RotMG's real DEX-based attack-frequency formula, condition-adjusted (`DAZED` clamps to slowest, `BERSERK` multiplies by 1.5).
  - `_resolveAimPoint(state, mouseWorld)` — "soft aim": snaps to the nearest enemy within 1 tile of the mouse's world position, else aims at the raw mouse position.
  - `handleShootInput(...)` — toggles auto-fire, tracks mouse-aim position, and while auto-fire is on and off cooldown, builds one `PLAYERSHOOT` packet **per projectile** in the weapon's fan (matching real client behavior confirmed via packet capture) and spawns each shot into `ProjectileStore` immediately (client-side prediction) rather than waiting for the server to echo it back.

---

## `Utils/`

Small loader/parser modules with no state of their own beyond an internal cache.

### `Utils/json/`

- **`accCredLoader.py`** — `credential_loader()`: reads `Credentials/account_credentials.json` into a list of `AccountData`.
- **`objectNameLoader.py`** — cached lookups into `Resources/renderMap.json`. `objectRenderInfo(objectType)` / `groundRenderInfo(groundType)` return an `ObjectRenderInfo`/`GroundRenderInfo` (name, chars, color, blocksMovement/isEnemy/isLootBag/isPortal/isInteractiveNpc). `objectIdToName(objectType)` is a thin name-only wrapper. Loaded once, cached in module-level dicts.
- **`projectileMapLoader.py`** — cached lookups into `Resources/projectileMap.json`. `projectileMapLoader()` loads the whole file; `getProjectileDefinition(map, ownerObjectType, projectileId)` looks up one; `resolveShotProjectileIds(map, ownerObjectType, numProjectiles)` figures out which projectile id each shot in a multi-shot fan actually uses (tiered bows fire a stronger center arrow + weaker side arrows from two distinct definitions — see the function's docstring for how the ranking works).

### `Utils/XML/`

One parser per account-data HTTP endpoint's XML response, all following the same defensive shape (skip an element missing a *required* field, log and continue rather than raising):

- **`parseCharList.py`** — `parseCharList(response, debugger)` → `List[CharListData]`.
- **`parseFriendsList.py`** — `parseFriendsList(response, debugger)` → `Set[str]` of friend account names.
- **`parseGuildmembers.py`** — `parseGuildMembers(response, debugger)` → `Set[str]` of guild member names.
- **`parseServersXML.py`** — `parseServersXML(response, debugger)` → `Dict[serverName, dns]`.
- **`parseGroundTypes.py`** — different from the four above: not an HTTP parser, a **runtime loader** for ground gameplay data. `groundIdToData(groundType)` merges every ground-type XML file listed in `Resources/_generated/json/manifest.json`'s `"tiles"` list into `GroundTypeData` (speed, noWalk, sink, damage) — this is what `TileManager.isTileBlocked` and the NoWalk/Sink render tiers read.

---

## `Crypto/`

- **`RC4.py`** — the RC4 stream cipher (KSA + PRGA) RotMG's protocol is encrypted with. `RC4(key)` then `.process(data)`.
- **`rotmg_keys.py`** — `OUTGOING_KEY`/`INCOMING_KEY`, the two hardcoded hex seeds `Listener`/`Sender` construct their `RC4` instances with. RotMG's own published protocol keys, not a project secret.
- **`RSA.py`** — `encrypt(msg)`: RSA-encrypts a string against a hardcoded RotMG public key. Not currently called from anywhere in the app — likely needed for a future account-management flow (e.g. password change/reset) that isn't wired up yet.

---

## `authentication/`

- **`getAccessAndClientToken.py`** — `getAccessAndClientToken(accountDict, debugger)`: the actual login flow. Derives `clientToken = md5(email + password)`, POSTs to `account/verify` to get an `AccessToken`, then POSTs to `account/verifyAccessTokenClient` to confirm it's valid. Returns a tagged tuple (`(True, (accessToken, clientToken))` or `(False, errReason, errText)`) — never raises, matching this repo's async-result convention.

---

## `Debug/`

- **`Debugger.py`** — the centralized logger (`ctx["DEBUGGER"]`). Every `debug/info/warning/error/exception()` call just enqueues onto an internal queue; a background daemon thread does the actual (blocking) rotating-file write, so no caller ever stalls on disk I/O. `flush()`/`stop()` block until the queue drains — used on the crash path so the crash line is guaranteed on disk before `sys.exit`.
- **`cp437_full_charset_16color_test.py`** — standalone diagnostic, not part of the app. Renders every usable CP437 glyph against every native 16-color combination in a scrollable pad. Run directly if glyph/color rendering ever misbehaves: `python Debug/cp437_full_charset_16color_test.py`.
- **`debug.txt`** — the actual rotating log file (gitignored), capped at 2MB × 3 backups.

---

## `Scripts/AssetPipeline/`

A standalone pipeline (not part of `main.py`'s loop) that regenerates `Resources/renderMap.json`, `Resources/projectileMap.json`, and `Resources/version.txt` straight from a local RotMG install. Run via `python -m Scripts.AssetPipeline.run`. Each phase is its own module, run in order by `run.py`:

- **`locateInstall.py`** — `findInstallPath()`: finds the local RotMG install folder (OS default path → cached path → Tkinter folder-picker fallback).
- **`extractBundles.py`** — `extractAll(...)`: walks the install through `UnityPy`, dumping every `TextAsset` (game XML/JSON) and the 4 spritesheet `Texture2D`s into gitignored `Resources/_generated/`.
- **`findVersion.py`** — `findGameVersion(install_path)`: regexes the game's build-version string straight out of the install's IL2CPP metadata file.
- **`spriteIndex.py`** — `loadSpriteIndex(path)`: parses the binary FlatBuffers sprite-atlas index into `{textureName: {id: SpriteRect}}`, using the compiled bindings in `generated/`.
- **`parseGameXml.py`** — `parseAll(...)`: parses every `<Object>`/`<Ground>` XML element (name, sprite refs, `blocksMovement`/`isEnemy`/`isLootBag` flags) plus `<Projectile>` definitions (`ParsedProjectile`), resolving each to its sprite rect via `resolveSpriteRects`.
- **`deriveRenderInfo.py`** — `deriveAll(...)`: turns each resolved sprite into a `RenderInfo` (glyph + one of curses' 8 base colors, via `nearestCursesColor`/`classifyBagColor`/`_firstAlphaChar` for enemy-letter derivation).
- **`mergeOverrides.py`** — `mergeOverrides(derived, overrides)` + `writeRenderMap(...)`: merges hand overrides from `Resources/renderMapOverrides.json` (gitignored; `.jsonEXAMPLE` is the tracked template) on top of the derived data, per-field, and writes the final `Resources/renderMap.json`.
- **`writeProjectileMap.py`** — `buildProjectileMap(...)` + `writeProjectileMap(...)`: resolves each weapon/enemy's `ParsedProjectile` definitions to their visual `objectType` and writes `Resources/projectileMap.json`.
- **`run.py`** — `run()`: calls every phase above in order.
- **`generated/`** — compiled FlatBuffers Python bindings for the sprite-index schema (`schemas/spritesheet.fbs`). Committed so running the pipeline doesn't require `flatc` installed locally — only regenerating the schema does.

---

## `Resources/`

Not code — the generated data files the app reads at runtime.

- **`renderMap.json`** — the only trackable JSON under `Resources/` (`.gitignore` has a blanket `*.json` rule with one negation for this file). `objectType`/`groundType` → `{name, chars, color, blocksMovement, isEnemy, isLootBag, isPortal, isInteractiveNpc}`. Generated by the asset pipeline; read via `Utils/json/objectNameLoader.py`.
- **`projectileMap.json`** — weapon/enemy `objectType` → projectile definitions (speed, damage, lifetime, rate of fire, fan-out). Generated by `writeProjectileMap.py`; read via `Utils/json/projectileMapLoader.py`.
- **`renderMapOverrides.jsonEXAMPLE`** — tracked template for hand overrides; copy to `renderMapOverrides.json` (gitignored) to activate.
- **`version.txt`** — the game build version sent in the `HELLO` handshake. Generated by the asset pipeline from the local install's IL2CPP metadata, not fetched from a network call (the third-party mirror in `Constants/ApiPoints.py` returns a stale value).

---

## `Credentials/`

- **`account_credentials.json`** (gitignored) — saved accounts (`alias`/`email`/`password`), written atomically (tempfile + `os.replace`) by `enterAccountInfo.py`, read by `Utils/json/accCredLoader.py`.
- **`account_credentials.jsonEXAMPLE`** — tracked template showing the expected shape.

---

## Vendored, not imported

- **`pyrelay/`** — a separate, independently git-tracked project (its own `.git/`, README, license) vendored in-tree as a possible future packet-level connection layer. Not currently imported or called from anywhere in `main.py`/`Renders/`.
- **`exalt-extractor/`** — a third-party tool (github.com/rotmg-network/exalt-extractor) used manually and out-of-band to extract `Equip.xml` from a local game install. Not imported or called from this codebase. Has no LICENSE (`license: null` on GitHub) — fine to run locally, but don't commit it into this repo's history or redistribute it.
