# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Role

Your primary purpose in this project is research and minimal tasks — investigating, explaining, and making small, targeted changes. The majority of writing/implementation should be left to the user; don't take on large or open-ended implementation work unprompted.

## What this is

A terminal-based ASCII client for Realm of the Mad God (rotmg-ascii). It authenticates against the real RotMG account API, pulls the player's char/friends/guild/server data, and renders it through a `curses`-based UI. The actual in-game networking/rendering (`Renders/GameScreen/gameScreen.py`) is not yet implemented — it's a stub — though `Models/PlayerData.py`, `Models/CharData.py`, `Models/ConditionEffect.py`, and the `Constants/PacketIds.py` / `Constants/GameIds.py` / `Constants/StatusEffects.py` scaffolding show the direction: a future packet-parsing layer for the live game protocol (per the README, "powered by a pyrelay headless connection" — not yet wired in or in `requirements.txt`).

## Running

```
pip install -r requirements.txt
python main.py
```

No test suite, linter, or build step exists in this repo yet.

Dependencies are `requests` and, on Windows only, `windows-curses` (native `curses` isn't available on Windows; Linux/macOS use the stdlib module directly).

## Architecture

### Screen state machine

`main.py` is the entire app loop: it holds a `screen: Screen` variable (`Constants/Screen.py`, an `Enum`: `accountSelect`, `enterAccountInfo`, `login`, `charSelect`, `gameScreen`, `exit`), a `handlers` dict mapping each `Screen` to its draw function, and a single shared `ctx: Context` dict. Each iteration it erases `stdscr` and calls `handlers[screen](stdscr, ctx)`, which returns the next `Screen` to transition to. The loop ends when a handler returns `Screen.exit`.

Every screen module follows the same shape and lives under `Renders/<ScreenName>/<screenName>.py`:

```python
def draw<ScreenName>(stdscr: curses.window, ctx: Context) -> Screen:
    ...
```

`Renders/EnterAccountInfo/enterAccountInfo.py` and `Renders/CharSelect/charSelect.py` also both import `determineRefreshWindow` (defined in `enterAccountInfo.py`) — the shared helper for computing the visible slice of a `curses.newpad` against the terminal size and current scroll position. Any new scrolling screen should reuse this rather than reimplementing pad-refresh math.

### Shared context (`Models/Context.py`)

`Context` is a `TypedDict(total=False)` passed by reference through every screen, accumulating state as the flow progresses (`account`, `accessToken`, `clientToken`, `CHARLIST`, `FRIENDSLIST`, `GUILDMEMBERS`, `SERVERS`, `CURR_CHAR_ID`). Because keys are optional in the type system but guaranteed present by the time a later screen runs, use `required(ctx.get("key"), "key")` instead of `ctx["key"]` — it asserts non-`None` and narrows the type without disabling the TypedDict checker.

### Background network calls

Screens that hit the network (`Renders/Login/login.py`, `Renders/EnterAccountInfo/enterAccountInfo.py`) run the request(s) on daemon `threading.Thread`s and poll `thread.is_alive()` in the render loop, redrawing a "loading dots" animation every 0.25s while waiting. Results come back through a `queue.Queue` as tagged tuples rather than exceptions — success/failure is `(True, ...)` / `(False, errReason, errText)` for single calls (see `TokenSuccess`/`TokenFailure` in `authentication/getAccessAndClientToken.py`), or `(True, tagName, response)` for the fan-out in `login.py`'s `gatherData`/`parseHandler`. Follow this convention for new async work instead of raising.

### Talking to RotMG's real API

`authentication/getAccessAndClientToken.py` and `Constants/ApiPoints.py` replicate the Unity client's login flow: it derives a `clientToken` as `md5(email + password)` and posts to the real `realmofthemadgod.com` account endpoints with the Unity `User-Agent`/`X-Unity-Version` headers. `Utils/XML/parse*.py` each parse one endpoint's XML response (`xml.etree.ElementTree`) into a `Models/` type, defensively skipping any `<Char>`/etc. element missing an expected field rather than raising.

### Credentials

Stored locally at `Credentials/account_credentials.json` (gitignored — the repo ships `account_credentials.jsonEXAMPLE` as the template) and loaded via `Utils/json/accCredLoader.py`. `enterAccountInfo.py` writes new entries with a tempfile-then-`os.replace` pattern for an atomic write, not a direct overwrite.

### Class IDs

`Constants/ClassIds.py` maps RotMG's numeric `objectType` class IDs to/from display names (`idToClass`/`classToId`, `ID_TO_CLASS`/`CLASS_TO_ID`). Used wherever a character's class needs to be shown (e.g. `charSelect.py`).

### Color rendering: raw ANSI, not curses palettes

Glyph color is meant to be done with raw 24-bit ANSI truecolor escape sequences (`\x1b[38;2;r;g;bm`) printed directly, **not** `curses.init_color()`/`curses.color_pair()`. Testing (see `Debug/`) showed curses' palette-remap API gets routed through the legacy Windows console buffer and silently quantizes/scrambles requested RGB values on Windows (confirmed via `curses.color_content()` read-back mismatches), while raw ANSI escapes render correctly on both native Windows and WSL. `curses` is still the right tool for window/pad layout and keyboard input — just not for color.

The full CP437 character set — plain ASCII (0x20–0x7E) plus the extended range (0x80–0xFF: box-drawing, shading blocks, accented letters, math/card symbols, decoded via Python's `cp437` codec) — is confirmed working as glyphs on **both Windows and Linux**, drawn through `curses.addstr()` (requires `locale.setlocale(locale.LC_ALL, "")` before `curses.wrapper`/`initscr`, otherwise the window's `.encoding` falls back to a codepage like cp1252 that can't represent most of that range). Bytes 0x00–0x1F and 0x7F are excluded: Python's `cp437` codec maps those to literal ASCII control characters, not the historical CP437 graphic glyphs, so they aren't safe to print/addstr directly. Pairing that full glyph set with the native 8-color palette (`curses.COLOR_*` + `init_pair()`, normal and bold, no RGB remap) is also confirmed correct on both platforms — see `Debug/cp437_full_charset_16color_test.py`.

Pairing that glyph set with `curses.init_color()`-based RGB remapping is a known trap, not just "quantized on Windows": `curses.COLOR_RED`..`curses.COLOR_WHITE` are literally the integers 1–7, the same slots the base named-color pairs (and most terminals' default/unpaired text) use. A custom-color allocator that starts handing out slots at 1 will, on a terminal where `init_color()` actually works (confirmed on Linux — Windows mostly no-ops/quantizes it, per above), silently overwrite those shared registers, e.g. turning default text green partway through. If RGB remapping via curses is ever revisited, custom slots must start at 8+ to stay clear of the base ANSI registers. Raw ANSI truecolor sidesteps this whole category of problem, which is the actual reason it's used for real glyph color instead of curses palettes.

`Debug/cp437_full_charset_16color_test.py` is a standalone, non-interactive-input diagnostic script (waits on a keypress to exit, takes no other input) that renders every usable glyph against every native 16-color combination in a scrollable curses pad. It's not part of the app; run it directly (`python Debug/cp437_full_charset_16color_test.py`) as a starting point if a user reports glyph/color rendering issues.
