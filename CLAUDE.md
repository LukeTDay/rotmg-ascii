# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Role

Your primary purpose in this project is research and minimal tasks — investigating, explaining, and making small, targeted changes. The majority of writing/implementation should be left to the user; don't take on large or open-ended implementation work unprompted.

## What this is

A terminal-based ASCII client for Realm of the Mad God (rotmg-ascii). It authenticates against the real RotMG account API, pulls the player's char/friends/guild/server data, and renders it through a `curses`-based UI. The packet-decoding layer for the live game protocol (`Networking/Packets/`, `Data/`, `Crypto/`) is ported and in place, and the live socket connection is now wired up end to end (see "Connecting to the game" below) through `CREATESUCCESS` — the client can log in, connect to a server, and load a character. What's not yet implemented is everything *after* that: the ASCII map/game-state renderer and keyboard-driven movement input (`Renders/GameScreen/gameScreen.py`'s `_connectedLoop` is currently just a placeholder screen that drains the incoming queue and discards events).

## Running

```
pip install -r requirements.txt
python main.py
```

No test suite, linter, or build step exists in this repo yet.

Dependencies are `requests`, `pyfiglet` (ASCII-art banner text, see "Centered/banner rendering" below), and, on Windows only, `windows-curses` (native `curses` isn't available on Windows; Linux/macOS use the stdlib module directly).

## Architecture

### Screen state machine

`main.py` is the entire app loop: it holds a `screen: Screen` variable (`Constants/Screen.py`, an `Enum`: `accountSelect`, `enterAccountInfo`, `login`, `charSelect`, `gameScreen`, `exit`), a `handlers` dict mapping each `Screen` to its draw function, and a single shared `ctx: Context` dict. Each iteration it erases `stdscr` and calls `handlers[screen](stdscr, ctx)`, which returns the next `Screen` to transition to. The loop ends when a handler returns `Screen.exit`.

Every screen module follows the same shape and lives under `Renders/<ScreenName>/<screenName>.py`:

```python
def draw<ScreenName>(stdscr: curses.window, ctx: Context) -> Screen:
    ...
```

`Renders/EnterAccountInfo/enterAccountInfo.py` and `Renders/CharSelect/charSelect.py` also both import `determineRefreshWindow` (defined in `enterAccountInfo.py`) — the shared helper for computing the visible slice of a `curses.newpad` against the terminal size and current scroll position. Any new scrolling screen should reuse this rather than reimplementing pad-refresh math.

### Centered/banner rendering (`Renders/EnterAccountInfo/enterAccountInfo.py`)

Also defined next to `determineRefreshWindow` — the same shared-helper spot — are `drawCenteredText` and `drawCenteredBanner`, used by `login.py`, `charSelect.py`, and `gameScreen.py` for all their status text. Both re-read `stdscr.getmaxyx()` on every call and center against the terminal's *actual* width (not a hardcoded column count, and not the pad's fixed width), and both return the next free row so callers can stack more lines underneath. `drawCenteredBanner` renders big block-letter text via `pyfiglet`; `figletLineCount(text)` measures a banner's row count without drawing it, for laying out content (e.g. vertical centering) before the banner itself is drawn.

Two non-obvious gotchas these came from:
- `pyfiglet.figlet_format`/`Figlet.renderText` default to wrapping at 80 columns, which silently mangles a banner wider than that (e.g. "Select a character") onto a garbled second line instead of raising or truncating. Both helpers construct `pyfiglet.Figlet(font=font, width=1000)` to disable this, and clip each rendered line to the terminal width themselves instead.
- `pad.clrtobot()` only clears from the *current cursor position* to the bottom, not the whole pad. Every redraw that's meant to wipe a previous frame must `pad.move(0, 0)` immediately before calling it — several state transitions originally skipped this (clearing from wherever the last `addstr` left the cursor instead), leaving fragments of the previous frame's text visible behind the new centered content. If you add a new redraw/clear point, make sure `pad.move(0, 0)` precedes `pad.clrtobot()`.

### Shared context (`Models/Context.py`)

`Context` is a `TypedDict(total=False)` passed by reference through every screen, accumulating state as the flow progresses (`account`, `accessToken`, `clientToken`, `buildVersion`, `CHARLIST`, `FRIENDSLIST`, `GUILDMEMBERS`, `SERVERS`, `CURR_CHAR_ID`, plus the game-networking keys described below). Because keys are optional in the type system but guaranteed present by the time a later screen runs, use `required(ctx.get("key"), "key")` instead of `ctx["key"]` — it asserts non-`None` and narrows the type without disabling the TypedDict checker.

### Background network calls

Screens that hit the network (`Renders/Login/login.py`, `Renders/EnterAccountInfo/enterAccountInfo.py`) run the request(s) on daemon `threading.Thread`s and poll `thread.is_alive()` in the render loop, redrawing a "loading dots" animation every 0.25s while waiting. Results come back through a `queue.Queue` as tagged tuples rather than exceptions — success/failure is `(True, ...)` / `(False, errReason, errText)` for single calls (see `TokenSuccess`/`TokenFailure` in `authentication/getAccessAndClientToken.py`), or `(True, tagName, response)` for the fan-out in `login.py`'s `gatherData`/`parseHandler`. Follow this convention for new async work instead of raising.

### Talking to RotMG's real API

`authentication/getAccessAndClientToken.py` and `Constants/ApiPoints.py` replicate the Unity client's login flow: it derives a `clientToken` as `md5(email + password)` and posts to the real `realmofthemadgod.com` account endpoints with the Unity `User-Agent`/`X-Unity-Version` headers. `Utils/XML/parse*.py` each parse one endpoint's XML response (`xml.etree.ElementTree`) into a `Models/` type, defensively skipping any `<Char>`/etc. element missing an expected field rather than raising.

The game build version sent in the `HELLO` handshake (see below) comes from a local `gameVersion.txt` at the repo root, not a network call — `Constants.ApiPoints.VERSION` (a third-party mirror) turned out to return a stale Unix timestamp rather than a real version string, and pyrelay itself never used it for this either (that project reads its own local `gameVersion.txt`). `login.py` reads the file into `ctx["buildVersion"]` right after `accessToken`/`clientToken` are set. If the game server ever starts rejecting the connection with a `FAILURE` packet whose `errorDescription` is `"s.update_client"`, this file is out of date and needs bumping by hand.

### Game networking threads (`Networking/Sender.py`, `Listener.py`, `Ticker.py`, `Connect.py`)

Once past char select, the client runs 4 concurrent workers with strict ownership boundaries — nothing latency-critical ever waits on the render loop's frame cadence, and nothing that draws ever blocks on the network:

- **`Sender`** owns the socket's write side. Its `start()` just blocks on `outgoingQueue.get()` and `sendall`s each packet (RC4-encrypted with the outgoing key) — it's the *only* thing that ever calls `send` on the socket.
- **`Listener`** owns the socket's read side. Its `start()` blocks on `recv()`, decodes each packet inline, and for a handful of packet types that need a fast protocol-level reply (`PING`→`PONG`, `UPDATE`→`UPDATEACK`, `GOTO`→`GOTOACK`, `SERVERPLAYERSHOOT`→`SHOOTACK` when it's this client's own shot, `ENEMYSHOOT`→`ENEMYSHOOTACK`, and `NEWTICK`→ a `MOVE` flush built from `Ticker.drainRecords()`) enqueues that reply onto the outbound queue **immediately, from this thread** — never routed through the renderer first, since RotMG drops clients that don't ack fast enough. It also tracks `self.objectId` (captured off `CREATESUCCESS`) so it knows which `GOTO`/`UPDATE`/`SERVERPLAYERSHOOT` events are about this client's own character. Every decoded packet (except `RECONNECT`, see below) is also forwarded as-is onto the incoming queue for the renderer.
- **`Ticker`** does local movement dead-reckoning on its own steady 10Hz timer (`RepeatTimer`, defined inline in `Ticker.py`), independent of the network and render loop — it never touches the socket or either queue itself. `setPos`/`setTarget`/`drainRecords` are its thread-safe entry points (`setPos` called by `Listener` on authoritative position updates, `setTarget` meant to be called by the renderer on keyboard input once movement input exists, `drainRecords` called by `Listener` on each `NEWTICK`). Its per-tick movement speed is currently a placeholder constant — there's no live `PlayerData`/condition-effect state object wired up during an active connection yet to read the real speed stat from.
- **Renderer** (main thread, `gameScreen.py`) is meant to own all game state, draining the incoming queue completely every frame (not one event per frame), applying each event, then pushing outbound actions — but the actual game-state model and keyboard-driven movement don't exist yet (see "What this is").

Two `queue.Queue`s carry events between these: `ctx["INCOMINGQUEUE"]` (network → renderer) and `ctx["OUTGOINGQUEUE"]` (renderer/Listener → Sender). Thread-safe by construction; no manual locks needed around them. A `RECONNECT` packet is the one exception to "Listener forwards every packet as-is" — the listener thread can't cleanly join/replace itself mid-`recv()`, so it just pushes a `("connecting", mapName)` tuple onto the incoming queue instead of the packet object; anything reading that queue has to handle both packet objects and this tuple shape. Actually tearing down and reopening the socket on reconnect isn't implemented yet.

### Connecting to the game (`Renders/GameScreen/gameScreen.py`)

`drawGame` runs the connection in three stages, each a separate function:

1. `_establishConnection` — if `ctx["LISTENER"]` isn't set yet, runs `Networking.Connect.connectToGame` on a daemon thread (same async convention as "Background network calls" above: tagged-tuple result via a `queue.Queue`, never raises). That function resolves a server host from `ctx["SERVERS"]` (currently just the first entry — there's no server-select screen yet, so this is a placeholder), opens the TCP socket, and builds the `Ticker`/`Sender`/`Listener` trio. On success, `gameScreen.py` stores them all into `ctx`, starts their three threads, and sends the `HELLO` packet (`gameId` from `Constants/GameIds.py`, `buildVersion` from `ctx`).
2. `_handshake` — drains the incoming queue until `CREATESUCCESS`: replies to `MAPINFO` with a `LOAD` for `ctx["CURR_CHAR_ID"]` (there's no "create a new character" path wired up — `charSelect.py` only ever lets you pick an existing one), and bails out to `Screen.charSelect` on a `FAILURE` packet.
3. Once past the handshake, `_connectedLoop` is a placeholder screen (see "What this is") that still watches for a post-login `FAILURE`.

`_handleFailure` is shared by stages 2 and 3: stops all three worker threads, closes the socket, deletes the `LISTENER`/`SENDER`/`TICKER`/`INCOMINGQUEUE`/`OUTGOINGQUEUE` keys back out of `ctx` (so a retry through `_establishConnection` reconnects cleanly), and bounces to `Screen.charSelect`.

### Credentials

Stored locally at `Credentials/account_credentials.json` (gitignored — the repo ships `account_credentials.jsonEXAMPLE` as the template) and loaded via `Utils/json/accCredLoader.py`. `enterAccountInfo.py` writes new entries with a tempfile-then-`os.replace` pattern for an atomic write, not a direct overwrite.

### Game protocol packet layer (`Networking/Packets/`, `Data/`, `Crypto/`)

This layer was ported wholesale from two external sibling projects (local checkouts, not submodules — `pyrelay/` currently sits untracked inside this repo as leftover source material): first from `pyrelay` (a Python RotMG bot library), then re-ported from `rotmg_mitm_py` (a MITM proxy project with a more current packet list — 137 packet classes vs pyrelay's 102, including party/enchanting/blacksmith/crucible/chest-reward/mission/stasis packets pyrelay never added). When pulling in more packet coverage from an external source in the future, prefer whatever's most current over pyrelay specifically.

Packet registration is fully dynamic — dropping a new file into `Networking/Packets/Incoming/` or `Outgoing/` is enough to wire it up, no manual registration step:
- `Incoming/__init__.py` / `Outgoing/__init__.py` `importlib`-import every `.py` file in their directory and expose the class of the same name (a file `PingPacket.py` must define class `PingPacket`).
- `Networking/Packets/PacketTypes.py` then builds a `packet_dict` from those modules by stripping `"Packet"` off each class name and upper-casing it (`PingPacket` → `"PING"`), keyed against `Constants/PacketIds.py`'s `idToType` map.
- `Networking/PacketHelper.py`'s `createPacket(packetType)` is the single entry point for instantiating a packet by its `idToType` string name; `Networking/Reader.py`/`Writer.py` handle the binary framing (`readCompressedInt`, `readStr`, etc.) each packet's `read`/`write` methods call into.
- A handful of `Constants/PacketIds.py` entries (pet/arena packets — `DELETEPET`, `ENTERARENA`, `HATCHPET`, etc.) have no corresponding packet class in either source project; `createPacket` will raise `ValueError` if one is ever actually received.

`Constants/StatTypes.py` was hand-merged rather than straight-copied from `rotmg_mitm_py`: that project's enum renames/adds many stat IDs but leaves 3 gaps (`HEALTHPOTIONSTACKSTAT`=69, `MAGICPOTIONSTACKSTAT`=70, `HASBACKPACKSTAT`=79) that `Models/PlayerData.py` already depended on, so those 3 were backfilled under their original names rather than dropped. `Data/StatData.py` deliberately does **not** carry over `rotmg_mitm_py`'s `readIfRelevant()`/`RELEVANT_STAT_TYPES` optimization (that project is a proxy that only decodes stats its own plugins care about) — this client needs every stat for real game-state rendering, so `StatData.read()` always fully decodes.

`Crypto/RC4.py` implements the RC4 stream cipher (KSA + PRGA) that RotMG's protocol is encrypted with; `Crypto/rotmg_keys.py` holds the two hardcoded hex keys (`OUTGOING_KEY`/`INCOMING_KEY`) it's seeded with — these are RotMG's own published protocol keys, not a project secret.

### Class IDs

`Constants/ClassIds.py` maps RotMG's numeric `objectType` class IDs to/from display names (`idToClass`/`classToId`, `ID_TO_CLASS`/`CLASS_TO_ID`). Used wherever a character's class needs to be shown (e.g. `charSelect.py`).

### Color rendering: raw ANSI, not curses palettes

Glyph color is meant to be done with raw 24-bit ANSI truecolor escape sequences (`\x1b[38;2;r;g;bm`) printed directly, **not** `curses.init_color()`/`curses.color_pair()`. Testing (see `Debug/`) showed curses' palette-remap API gets routed through the legacy Windows console buffer and silently quantizes/scrambles requested RGB values on Windows (confirmed via `curses.color_content()` read-back mismatches), while raw ANSI escapes render correctly on both native Windows and WSL. `curses` is still the right tool for window/pad layout and keyboard input — just not for color.

The full CP437 character set — plain ASCII (0x20–0x7E) plus the extended range (0x80–0xFF: box-drawing, shading blocks, accented letters, math/card symbols, decoded via Python's `cp437` codec) — is confirmed working as glyphs on **both Windows and Linux**, drawn through `curses.addstr()` (requires `locale.setlocale(locale.LC_ALL, "")` before `curses.wrapper`/`initscr`, otherwise the window's `.encoding` falls back to a codepage like cp1252 that can't represent most of that range). Bytes 0x00–0x1F and 0x7F are excluded: Python's `cp437` codec maps those to literal ASCII control characters, not the historical CP437 graphic glyphs, so they aren't safe to print/addstr directly. Pairing that full glyph set with the native 8-color palette (`curses.COLOR_*` + `init_pair()`, normal and bold, no RGB remap) is also confirmed correct on both platforms — see `Debug/cp437_full_charset_16color_test.py`.

Pairing that glyph set with `curses.init_color()`-based RGB remapping is a known trap, not just "quantized on Windows": `curses.COLOR_RED`..`curses.COLOR_WHITE` are literally the integers 1–7, the same slots the base named-color pairs (and most terminals' default/unpaired text) use. A custom-color allocator that starts handing out slots at 1 will, on a terminal where `init_color()` actually works (confirmed on Linux — Windows mostly no-ops/quantizes it, per above), silently overwrite those shared registers, e.g. turning default text green partway through. If RGB remapping via curses is ever revisited, custom slots must start at 8+ to stay clear of the base ANSI registers. Raw ANSI truecolor sidesteps this whole category of problem, which is the actual reason it's used for real glyph color instead of curses palettes.

`Debug/cp437_full_charset_16color_test.py` is a standalone, non-interactive-input diagnostic script (waits on a keypress to exit, takes no other input) that renders every usable glyph against every native 16-color combination in a scrollable curses pad. It's not part of the app; run it directly (`python Debug/cp437_full_charset_16color_test.py`) as a starting point if a user reports glyph/color rendering issues.
