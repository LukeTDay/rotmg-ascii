# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Role

Your primary purpose in this project is research and minimal tasks — investigating, explaining, and making small, targeted changes. The majority of writing/implementation should be left to the user; don't take on large or open-ended implementation work unprompted.

## What this is

A terminal-based ASCII client for Realm of the Mad God (rotmg-ascii). It authenticates against the real RotMG account API, pulls the player's char/friends/guild/server data, and renders it through a `curses`-based UI. The packet-decoding layer for the live game protocol (`Networking/Packets/`, `Data/`, `Crypto/`) is ported and in place, and the live socket connection is now wired up end to end (see "Connecting to the game" below) through `CREATESUCCESS` — the client can log in, connect to a server, and load a character. What's not yet implemented is everything *after* that: the ASCII map/game-state renderer and keyboard-driven movement input (`Renders/GameScreen/gameScreen.py`'s `_connectedLoop` is currently just a placeholder screen that drains the incoming queue and discards events).

`Resources/renderMap.json` (see "Asset pipeline" below) already has the `objectType -> {name, chars, color}` data a future map renderer would need, generated from the real game files — but nothing in the app loads it yet.

## Running

```
pip install -r requirements.txt
python main.py
```

No test suite, linter, or build step exists in this repo yet.

`main.py`'s `if __name__ == "__main__"` wraps `curses.wrapper(main)` in a try/except: `curses.wrapper` already restores the terminal on an exception before re-raising, so the except block prints a normal `traceback.print_exc()` to stdout/stderr and exits 1, instead of dumping a raw traceback over a half-torn-down terminal.

Dependencies are `requests`, `pyfiglet` (ASCII-art banner text, see "Centered/banner rendering" below), and, on Windows only, `windows-curses` (native `curses` isn't available on Windows; Linux/macOS use the stdlib module directly).

`Scripts/AssetPipeline/` (see below) has its own separate `requirements.txt` (`UnityPy`, `Pillow`, `flatbuffers`) — only needed if you're running the asset pipeline itself, not for the client app, so it's kept out of the root `requirements.txt`.

## Architecture

### Screen state machine

`main.py` is the entire app loop: it holds a `screen: Screen` variable (`Constants/Screen.py`, an `Enum`: `accountSelect`, `enterAccountInfo`, `login`, `charSelect`, `serverSelect`, `gameScreen`, `exit`), a `handlers` dict mapping each `Screen` to its draw function, and a single shared `ctx: Context` dict. Each iteration it erases `stdscr` and calls `handlers[screen](stdscr, ctx)`, which returns the next `Screen` to transition to. The loop ends when a handler returns `Screen.exit`.

Every screen module follows the same shape and lives under `Renders/<ScreenName>/<screenName>.py`:

```python
def draw<ScreenName>(stdscr: curses.window, ctx: Context) -> Screen:
    ...
```

`Renders/EnterAccountInfo/enterAccountInfo.py` and `Renders/CharSelect/charSelect.py` also both import `determineRefreshWindow` (defined in `enterAccountInfo.py`) — the shared helper for computing the visible slice of a `curses.newpad` against the terminal size and current scroll position. Any new scrolling screen should reuse this rather than reimplementing pad-refresh math.

Every screen's `curses.newpad(rows, cols)` is sized generously wide (500 columns) rather than to any expected content width. Centering math sizes against the terminal's *actual* width (see below), and a pad narrower than that will throw `_curses.error: addwstr() returned ERR` the moment a centered `x` position (or its clipped write) exceeds the pad's own column count — this actually happened (pads were originally 150 columns) once a terminal was made wide enough. If you add a new `curses.newpad` call, don't hardcode a narrow column count.

### Centered/banner rendering (`Renders/EnterAccountInfo/enterAccountInfo.py`)

Also defined next to `determineRefreshWindow` — the same shared-helper spot — are `drawCenteredText` and `drawCenteredBanner`, used by every screen for their status text. Both re-read `stdscr.getmaxyx()` on every call and center against the terminal's *actual* width (not a hardcoded column count, and not the pad's fixed width), and both return the next free row so callers can stack more lines underneath. `drawCenteredBanner` renders big block-letter text via `pyfiglet`; `figletLineCount(text)` measures a banner's row count without drawing it, for laying out content (e.g. vertical centering) before the banner itself is drawn.

For a line that gets redrawn every keystroke (live email/password/alias input echo in `enterAccountInfo.py`), `drawCenteredText` is the wrong tool: recentering from the current (growing/shrinking) buffer length every frame makes the whole line visibly shift as you type. `centeredX(stdscr, text)` and `drawTextAt(stdscr, pad, y, x, text, attr)` split centering into two steps instead — compute `x` once from a fixed-length anchor string (the static prompt, not the live buffer), then keep redrawing at that same `x` every keystroke. Reuse this pair for any future live-editable field instead of `drawCenteredText`.

Two non-obvious gotchas these came from:
- `pyfiglet.figlet_format`/`Figlet.renderText` default to wrapping at 80 columns, which silently mangles a banner wider than that (e.g. "Select a character") onto a garbled second line instead of raising or truncating. Both helpers construct `pyfiglet.Figlet(font=font, width=1000)` to disable this, and clip each rendered line to the terminal width themselves instead.
- `pad.clrtobot()` only clears from the *current cursor position* to the bottom, not the whole pad. Every redraw that's meant to wipe a previous frame must `pad.move(0, 0)` immediately before calling it — several state transitions originally skipped this (clearing from wherever the last `addstr` left the cursor instead), leaving fragments of the previous frame's text visible behind the new centered content. If you add a new redraw/clear point, make sure `pad.move(0, 0)` precedes `pad.clrtobot()`.

### Shared context (`Models/Context.py`)

`Context` is a `TypedDict(total=False)` passed by reference through every screen, accumulating state as the flow progresses (`account`, `accessToken`, `clientToken`, `buildVersion`, `CHARLIST`, `FRIENDSLIST`, `GUILDMEMBERS`, `SERVERS`, `CURR_CHAR_ID`, plus the game-networking keys described below). Because keys are optional in the type system but guaranteed present by the time a later screen runs, use `required(ctx.get("key"), "key")` instead of `ctx["key"]` — it asserts non-`None` and narrows the type without disabling the TypedDict checker.

### Centralized debug logging (`Debug/Debugger.py`, `ctx["DEBUGGER"]`)

A single `Debugger` instance (stdlib `logging` + `logging.handlers.RotatingFileHandler`, writing to `Debug/debug.txt`, capped at 2MB × 3 backups) is created once in `main.py` right before `curses.wrapper(...)` and stored in `ctx["DEBUGGER"]` — any screen already threading `ctx` pulls it out with `required(ctx.get("DEBUGGER"), "DEBUGGER")` like any other key. `debug/info/warning/error/exception()` just enqueue onto an internal `queue.Queue`; a background daemon thread does the actual (blocking) file write, so no caller ever stalls on log I/O — same producer/consumer convention as `Sender`/`Listener` below. `flush()`/`stop()` block until the queue drains, which matters on the crash path in `main.py`'s outer `except Exception:` (the crash line has to actually be on disk before `sys.exit`).

Modules that don't receive `ctx` (`Sender`, `Listener`, `Ticker`, `authentication/getAccessAndClientToken.py`, `Utils/XML/parse*.py`) take the `Debugger` instance as an explicit constructor/function parameter instead, threaded down by whichever `ctx`-having caller constructs/calls them (`Networking/Connect.py` for the three game-networking workers; `login.py`/`enterAccountInfo.py` for auth and XML parsing) — this repo has no hidden global state anywhere else, so the debugger doesn't introduce any either.

Logging is deliberately sparse on hot paths: screen entry (once per screen visit, not per frame/keystroke) and real failure/disconnect paths are logged, but high-frequency protocol traffic (`PING`/`PONG`, `UPDATE`/`UPDATEACK`, `GOTO`/`GOTOACK`, `NEWTICK`/`MOVE`) deliberately isn't, to avoid drowning the rotated log. Once the game-state/map renderer (see "What this is") starts parsing characters/projectiles/tiles out of `UPDATE`, that's the natural next thing to log through this same debugger.

### Background network calls

Screens that hit the network (`Renders/Login/login.py`, `Renders/EnterAccountInfo/enterAccountInfo.py`) run the request(s) on daemon `threading.Thread`s and poll `thread.is_alive()` in the render loop, redrawing a "loading dots" animation every 0.25s while waiting. Results come back through a `queue.Queue` as tagged tuples rather than exceptions — success/failure is `(True, ...)` / `(False, errReason, errText)` for single calls (see `TokenSuccess`/`TokenFailure` in `authentication/getAccessAndClientToken.py`), or `(True, tagName, response)` for the fan-out in `login.py`'s `gatherData`/`parseHandler`. Follow this convention for new async work instead of raising.

### Talking to RotMG's real API

`authentication/getAccessAndClientToken.py` and `Constants/ApiPoints.py` replicate the Unity client's login flow: it derives a `clientToken` as `md5(email + password)` and posts to the real `realmofthemadgod.com` account endpoints with the Unity `User-Agent`/`X-Unity-Version` headers. `Utils/XML/parse*.py` each parse one endpoint's XML response (`xml.etree.ElementTree`) into a `Models/` type, defensively skipping any `<Char>`/etc. element missing an expected field rather than raising.

That "skip the whole element" rule is for fields the app can't function without (id, class, level, etc). Optional/non-critical fields get a softer fallback instead: `parseCharList.py`'s `<CrucibleActive>` (confirmed present on the real `char/list` response, empty when not active) just becomes `CharListData.isInCrucible = False` if the element is missing or empty, rather than dropping the character. Follow whichever pattern matches the field's importance when adding new parsed data.

The game build version sent in the `HELLO` handshake (see below) comes from `Resources/version.txt`, not a network call — `Constants.ApiPoints.VERSION` (a third-party mirror) turned out to return a stale Unix timestamp rather than a real version string. `login.py` reads the file into `ctx["buildVersion"]` right after `accessToken`/`clientToken` are set. `Resources/version.txt` is generated (not hand-maintained) by `Scripts/AssetPipeline/run.py`, which pulls the version string out of the local RotMG install's il2cpp metadata (see `Scripts/AssetPipeline/findVersion.py`) — if the game server ever starts rejecting the connection with a `FAILURE` packet whose `errorDescription` is `"s.update_client"`, this file is out of date; fix it by rerunning `python -m Scripts.AssetPipeline.run`, not by hand-editing.

### Game networking threads (`Networking/Sender.py`, `Listener.py`, `Ticker.py`, `Connect.py`)

Once past char select, the client runs 4 concurrent workers with strict ownership boundaries — nothing latency-critical ever waits on the render loop's frame cadence, and nothing that draws ever blocks on the network:

- **`Sender`** owns the socket's write side. Its `start()` just blocks on `outgoingQueue.get()` and `sendall`s each packet (RC4-encrypted with the outgoing key) — it's the *only* thing that ever calls `send` on the socket.
- **`Listener`** owns the socket's read side. Its `start()` blocks on `recv()`, decodes each packet inline, and for a handful of packet types that need a fast protocol-level reply (`PING`→`PONG`, `UPDATE`→`UPDATEACK`, `GOTO`→`GOTOACK`, `SERVERPLAYERSHOOT`→`SHOOTACK` when it's this client's own shot, `ENEMYSHOOT`→`ENEMYSHOOTACK`, and `NEWTICK`→ a `MOVE` flush built from `Ticker.drainRecords()`) enqueues that reply onto the outbound queue **immediately, from this thread** — never routed through the renderer first, since RotMG drops clients that don't ack fast enough. It also tracks `self.objectId` (captured off `CREATESUCCESS`) so it knows which `GOTO`/`UPDATE`/`SERVERPLAYERSHOOT` events are about this client's own character. Every decoded packet (except `RECONNECT`, see below) is also forwarded as-is onto the incoming queue for the renderer.
- **`Ticker`** does local movement dead-reckoning on its own steady 10Hz timer (`RepeatTimer`, defined inline in `Ticker.py`), independent of the network and render loop — it never touches the socket or either queue itself. `setPos`/`setTarget`/`drainRecords` are its thread-safe entry points (`setPos` called by `Listener` on authoritative position updates, `setTarget` meant to be called by the renderer on keyboard input once movement input exists, `drainRecords` called by `Listener` on each `NEWTICK`). Its per-tick movement speed is currently a placeholder constant — there's no live `PlayerData`/condition-effect state object wired up during an active connection yet to read the real speed stat from.
- **Renderer** (main thread, `gameScreen.py`) is meant to own all game state, draining the incoming queue completely every frame (not one event per frame), applying each event, then pushing outbound actions — but the actual game-state model and keyboard-driven movement don't exist yet (see "What this is").

Two `queue.Queue`s carry events between these: `ctx["INCOMINGQUEUE"]` (network → renderer) and `ctx["OUTGOINGQUEUE"]` (renderer/Listener → Sender). Thread-safe by construction; no manual locks needed around them. A `RECONNECT` packet is the one exception to "Listener forwards every packet as-is" — the listener thread can't cleanly join/replace itself mid-`recv()`, so it just pushes a `("connecting", mapName)` tuple onto the incoming queue instead of the packet object; anything reading that queue has to handle both packet objects and this tuple shape. Actually tearing down and reopening the socket on reconnect isn't implemented yet.

### Connecting to the game (`Renders/GameScreen/gameScreen.py`)

`drawGame` runs the connection in three stages, each a separate function:

1. `_establishConnection` — if `ctx["LISTENER"]` isn't set yet, runs `Networking.Connect.connectToGame` on a daemon thread (same async convention as "Background network calls" above: tagged-tuple result via a `queue.Queue`, never raises). That function opens a TCP socket to `ctx["CURR_SERVER"]` (the DNS host set by `Renders/ServerSelect/serverSelect.py`, keyed off `ctx["SERVERS"]`) and builds the `Ticker`/`Sender`/`Listener` trio. On success, `gameScreen.py` stores them all into `ctx`, starts their three threads, and sends the `HELLO` packet (`gameId` from `Constants/GameIds.py`, `buildVersion` from `ctx`).
2. `_handshake` — drains the incoming queue until `CREATESUCCESS`: replies to `MAPINFO` with a `LOAD` for `ctx["CURR_CHAR_ID"]` (there's no "create a new character" path wired up — `charSelect.py` only ever lets you pick an existing one), and bails out to `Screen.charSelect` on a `FAILURE` packet.
3. Once past the handshake, `_connectedLoop` is a placeholder screen (see "What this is") that still watches for a post-login `FAILURE`.

`_handleFailure` is shared by stages 2 and 3: stops all three worker threads, closes the socket, deletes the `LISTENER`/`SENDER`/`TICKER`/`INCOMINGQUEUE`/`OUTGOINGQUEUE` keys back out of `ctx` (so a retry through `_establishConnection` reconnects cleanly), and bounces to `Screen.charSelect`.

### Credentials

Stored locally at `Credentials/account_credentials.json` (gitignored — the repo ships `account_credentials.jsonEXAMPLE` as the template) and loaded via `Utils/json/accCredLoader.py`. `enterAccountInfo.py` writes new entries with a tempfile-then-`os.replace` pattern for an atomic write, not a direct overwrite.

### Game protocol packet layer (`Networking/Packets/`, `Data/`, `Crypto/`)

This layer was ported wholesale from external reference sources — not submodules, not present inside this repo itself. When pulling in more packet coverage from an external source in the future, prefer whatever's most current. See `CLAUDE.local.md`'s "Reference projects" section for what those sources are and what was ported from where.

Packet registration is fully dynamic — dropping a new file into `Networking/Packets/Incoming/` or `Outgoing/` is enough to wire it up, no manual registration step:
- `Incoming/__init__.py` / `Outgoing/__init__.py` `importlib`-import every `.py` file in their directory and expose the class of the same name (a file `PingPacket.py` must define class `PingPacket`).
- `Networking/Packets/PacketTypes.py` then builds a `packet_dict` from those modules by stripping `"Packet"` off each class name and upper-casing it (`PingPacket` → `"PING"`), keyed against `Constants/PacketIds.py`'s `idToType` map.
- `Networking/PacketHelper.py`'s `createPacket(packetType)` is the single entry point for instantiating a packet by its `idToType` string name; `Networking/Reader.py`/`Writer.py` handle the binary framing (`readCompressedInt`, `readStr`, etc.) each packet's `read`/`write` methods call into.
- A handful of `Constants/PacketIds.py` entries (pet/arena packets — `DELETEPET`, `ENTERARENA`, `HATCHPET`, etc.) have no corresponding packet class in any ported reference source; `createPacket` will raise `ValueError` if one is ever actually received.

`Constants/StatTypes.py` was hand-merged rather than straight-copied from an external reference source (see `CLAUDE.local.md`): that source's enum renames/adds many stat IDs but leaves 3 gaps (`HEALTHPOTIONSTACKSTAT`=69, `MAGICPOTIONSTACKSTAT`=70, `HASBACKPACKSTAT`=79) that `Models/PlayerData.py` already depended on, so those 3 were backfilled under their original names rather than dropped. `Data/StatData.py` deliberately does **not** carry over that source's `readIfRelevant()`/`RELEVANT_STAT_TYPES` optimization (it's a proxy that only decodes stats its own plugins care about) — this client needs every stat for real game-state rendering, so `StatData.read()` always fully decodes.

`Crypto/RC4.py` implements the RC4 stream cipher (KSA + PRGA) that RotMG's protocol is encrypted with; `Crypto/rotmg_keys.py` holds the two hardcoded hex keys (`OUTGOING_KEY`/`INCOMING_KEY`) it's seeded with — these are RotMG's own published protocol keys, not a project secret.

### Class IDs

`Constants/ClassIds.py` maps RotMG's numeric `objectType` class IDs to/from display names (`idToClass`/`classToId`, `ID_TO_CLASS`/`CLASS_TO_ID`). Used wherever a character's class needs to be shown (e.g. `charSelect.py`).

### Color rendering: native curses palette (`Constants/ColorPairs.py`), not raw ANSI or RGB remap

All UI text color in the app today (`charSelect.py`'s fame/seasonal/standard/crucible coloring) goes through curses' native palette — `curses.COLOR_*` + `curses.init_pair()`/`curses.color_pair()`, **no** `curses.init_color()` RGB remap. `Constants/ColorPairs.py` is the single source of truth for pair numbers; `main.py` calls `curses.init_pair()` for every one of them once at startup (after `curses.start_color()`), and screens just reference the numeric constants. A colored UI element that also needs to render while selected (reverse-video row highlight) gets a second `"_SELECTED"` pair — same foreground, white background instead of black — registered in `ColorPairs.SELECTED_VARIANT`; see `charSelect.py`'s `_printSplitRow` for the pattern (reverse-video on a colored pair would swap fg/bg and wash out the hue, so selected colored segments swap pairs instead of adding `A_REVERSE`).

`curses.init_color()`-based RGB remapping was considered and ruled out — it's routed through the legacy Windows console buffer and silently quantizes/scrambles requested RGB values there (confirmed via `curses.color_content()` read-back mismatches on Windows; `init_color()` actually works on Linux), and it's a trap even where it does work: `curses.COLOR_RED`..`curses.COLOR_WHITE` are literally the integers 1–7, the same slots the base named-color pairs (and most terminals' default/unpaired text) use. A custom-color allocator that starts handing out slots at 1 will silently overwrite those shared registers, e.g. turning default text green partway through. If RGB remapping via curses is ever revisited, custom slots must start at 8+ to stay clear of the base ANSI registers.

Raw 24-bit ANSI truecolor escapes (`\x1b[38;2;r;g;bm`) were tried as a way around the native palette's 8-color limit and reverted — confirmed via `pad.instr()` read-back that `curses.addstr()`/`pad.addstr()` doesn't pass the raw `0x1B` (ESC) byte through, it stores it as the two visible characters `^[`, which renders as literal garbage text (e.g. `^[[38;2;255;140;0m`) instead of an invisible color code. A working implementation would need to write the ANSI bytes straight to the terminal (e.g. `sys.stdout.write`/`os.write(1, ...)`) at an absolute cursor position, timed after the relevant `pad.refresh()` call so curses doesn't overwrite it on the next redraw — this hasn't been built anywhere in the app. If full RGB glyph color is ever needed (e.g. a future map/tile renderer wanting arbitrary game colors beyond the native palette's 8), that direct-terminal-write approach is the only one that's actually survived a real test in this repo; embedding escapes in `addstr()` calls is confirmed **not** to work.

The full CP437 character set — plain ASCII (0x20–0x7E) plus the extended range (0x80–0xFF: box-drawing, shading blocks, accented letters, math/card symbols, decoded via Python's `cp437` codec) — is confirmed working as glyphs on **both Windows and Linux**, drawn through `curses.addstr()` (requires `locale.setlocale(locale.LC_ALL, "")` before `curses.wrapper`/`initscr`, otherwise the window's `.encoding` falls back to a codepage like cp1252 that can't represent most of that range). Bytes 0x00–0x1F and 0x7F are excluded: Python's `cp437` codec maps those to literal ASCII control characters, not the historical CP437 graphic glyphs, so they aren't safe to print/addstr directly. Pairing that full glyph set with the native 8-color palette (normal and bold, no RGB remap) is also confirmed correct on both platforms — see `Debug/cp437_full_charset_16color_test.py`.

`Debug/cp437_full_charset_16color_test.py` is a standalone, non-interactive-input diagnostic script (waits on a keypress to exit, takes no other input) that renders every usable glyph against every native 16-color combination in a scrollable curses pad. It's not part of the app; run it directly (`python Debug/cp437_full_charset_16color_test.py`) as a starting point if a user reports glyph/color rendering issues.

### Asset pipeline (`Scripts/AssetPipeline/`)

A standalone pipeline, not part of the app's `main.py` loop, that regenerates `Resources/renderMap.json` and `Resources/version.txt` straight from a local RotMG Exalt install — so neither file needs manual re-derivation by hand after a game update:

```
python -m Scripts.AssetPipeline.run
```

(`python run.py` from inside `Scripts/AssetPipeline/` also works — every module in this package inserts the repo root into `sys.path` itself if it isn't already there, so scripts run correctly either as `-m` package imports or as directly-executed files.)

Each phase is its own module, run in order by `run.py`:

1. **`locateInstall.py`** — resolves the local install directory (the folder containing `resources.assets`, e.g. `~/Documents/RealmOfTheMadGod/Production/RotMG Exalt_Data` on Windows). Tries the OS default path first, then a cached path (`Scripts/AssetPipeline/.installPath.txt`, gitignored, per-machine), then falls back to a Tkinter folder-picker popup.
2. **`extractBundles.py`** — walks every file in the install directory through `UnityPy.load()` (harmless no-op on non-asset files) and dumps every `TextAsset` (classified as XML/JSON/binary by sniffing its first byte, not by a name blacklist — RotMG's own file names for these change/aren't consistent) plus the four spritesheet `Texture2D`s (`characters`, `characters_masks`, `groundTiles`, `mapObjects`) into gitignored `Resources/_generated/`. All the actual game data — object/ground XML, the sprite atlas index, the spritesheets — lives in one `resources.assets` file, not spread across the install; a `manifest.json` TextAsset (also extracted) lists exactly which of the ~230 extracted XML files belong to the "objects" category vs "tiles" (ground), including ~150/~55 per-dungeon override files respectively — that list is the authoritative source `parseGameXml.py` uses, not a filename guess.
3. **`findVersion.py`** — the game's build version isn't in any extracted XML/JSON; it's a compiled string literal inside the install's il2cpp metadata file (`<install>/il2cpp_data/Metadata/global-metadata.dat`), found by regexing for RotMG's 5-part version pattern (`\d+\.\d+\.\d+\.\d+\.\d+`) — no il2cpp dump tool needed.
4. **`spriteIndex.py`** + **`parseGameXml.py`** — the sprite-atlas index (a `spritesheetf` TextAsset) is a **binary FlatBuffers buffer**, not the JSON a prior reference implementation assumes (see `CLAUDE.local.md`). Its schema was recovered from another reference project's FlatBuffers-compiler-generated Java bindings, written out as `schemas/spritesheet.fbs`, and compiled to real Python bindings in `generated/` via `flatc --python -o Scripts/AssetPipeline/generated Scripts/AssetPipeline/schemas/spritesheet.fbs` (`generated/` is committed so using the pipeline doesn't require `flatc` installed, only regenerating the schema does). A sprite's `aId` field identifies which of the four spritesheet PNGs it lives in, fixed order: 1=`groundTiles`, 2=`characters`, 3=`characters_masks`, 4=`mapObjects`. `parseGameXml.py` parses the `<Object type="0x.." id="..">`/`<Ground ...>` XML elements (same defensive "skip element if a critical field is missing" pattern as `Utils/XML/parse*.py`) and resolves each one's `<Texture><File>/<Index>` ref through the sprite index. A `<RandomTexture>` block wrapping several `<Texture>` children (the game picks one at random for visual variety, e.g. "Wood Plank Floor" has 5 variants) means an id can resolve to multiple sprite rects — collected, not just the first.
5. **`deriveRenderInfo.py`** — maps each resolved sprite's game-computed `mostCommonColor` down to one of curses' 8 base colors via exact RGB-cube-corner thresholding (curses' 8 colors are literally the RGB cube's 8 corners, so this is exact, not nearest-neighbor). `mostCommonColor` picks the sprite's black outline on a large fraction of entities in practice (a small pixel-art icon usually has more outline pixels than fill pixels) — confirmed against real data, e.g. a metal sword computing as near-pure-black. Since `BLACK` text would be invisible on a typical black terminal background, that case falls back to searching the sprite's actual pixels outward from center for a non-outline color, and falls back further to `WHITE` if the whole sprite is genuinely dark/grey. `chars` is always a JSON list, not a single character, even though auto-derivation here always produces one element (a simple `"*"`/`"."` default per objects/ground) — the list shape exists so a hand override (see below) can assign several glyphs to one id for a future renderer to vary between (e.g. a floor tile rendering as `.` sometimes and `,` other times).
6. **`mergeOverrides.py`** — merges hand overrides on top, **per-field** (an override only needs to specify what it's changing, not the whole entry), and writes the final `Resources/renderMap.json`. Overrides follow the same tracked-template/gitignored-live-file split as `Credentials/account_credentials.json`/`.jsonEXAMPLE`: `Resources/renderMapOverrides.jsonEXAMPLE` is tracked and ships real examples; `Resources/renderMapOverrides.json` is what this module actually reads, gitignored, and not auto-created (copy the example to activate it) — so a curated override can ship in the repo without risking someone's personal override edits getting committed.

`.gitignore`'s blanket `*.json` rule (see "Credentials" above) has one negation, `!Resources/renderMap.json`, so the pipeline's actual output is the only JSON file under `Resources/` that's trackable — `renderMapOverrides.json`, everything in `Resources/_generated/`, and the per-machine install path cache all stay local.
