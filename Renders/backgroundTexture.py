import curses
import random
import time
from typing import Tuple

from Constants import ColorPairs
from Models.Context import Context

# Printable ASCII punctuation/symbols (0x21-0x7E, excluding letters/digits) -
# letters or numbers scattered as texture would read as garbled text next to
# real UI content.
DEFAULT_TEXTURE_CHARS: Tuple[str, ...] = tuple(
    chr(c) for c in range(0x21, 0x7F) if not chr(c).isalnum()
)

# MAP_* color pairs (Constants/ColorPairs.py) - excludes MAP_BLACK, which
# would be invisible against a typical black terminal background.
_TEXTURE_COLOR_PAIRS: Tuple[int, ...] = (
    ColorPairs.MAP_RED, ColorPairs.MAP_GREEN, ColorPairs.MAP_YELLOW, ColorPairs.MAP_BLUE,
    ColorPairs.MAP_MAGENTA, ColorPairs.MAP_CYAN, ColorPairs.MAP_WHITE,
)

# Fraction of the screen's cells covered, randomized within this range each
# regeneration - keeps it a sparse scatter, never a solid fill.
_MIN_DENSITY = 0.02
_MAX_DENSITY = 0.06

DEFAULT_REGEN_INTERVAL_SECONDS = 2.0


def drawBackgroundTexture(stdscr: curses.window, pad: curses.window, ctx: Context,
                           chars: Tuple[str, ...] = DEFAULT_TEXTURE_CHARS,
                           regenIntervalSeconds: float = DEFAULT_REGEN_INTERVAL_SECONDS,
                           dim: bool = True) -> None:
    """Scatters a random low-density field of texture glyphs, each an
    independently random char/color pair, across the pad - call once per
    frame, before a screen draws its own content on top (the content just
    overwrites whatever texture cells it uses).

    Re-rolled on a wall-clock timer (every `regenIntervalSeconds`, default 2s)
    rather than a call count - screens redraw at very different cadences
    (gameScreen's ~120Hz loop vs. a menu screen blocking on getch() per
    keystroke), so a call-count threshold would regenerate at wildly
    different real-world rates depending on which screen calls this.
    """
    maxY, maxX = stdscr.getmaxyx()
    rng = ctx.setdefault("RNG", random.Random())

    now = time.time()
    cache = ctx.get("BACKGROUND_TEXTURE_CACHE")
    cachedDims = ctx.get("BACKGROUND_TEXTURE_DIMS")
    lastRegen = ctx.get("BACKGROUND_TEXTURE_LAST_REGEN", 0.0)
    needsRegen = cache is None or cachedDims != (maxY, maxX) or now - lastRegen >= regenIntervalSeconds

    if needsRegen:
        count = round(maxY * maxX * rng.uniform(_MIN_DENSITY, _MAX_DENSITY))
        cache = [
            (rng.randrange(maxY), rng.randrange(maxX), rng.choice(chars), rng.choice(_TEXTURE_COLOR_PAIRS))
            for _ in range(count)
        ]
        ctx["BACKGROUND_TEXTURE_CACHE"] = cache
        ctx["BACKGROUND_TEXTURE_DIMS"] = (maxY, maxX)
        ctx["BACKGROUND_TEXTURE_LAST_REGEN"] = now

    dimAttr = curses.A_DIM if dim else curses.A_NORMAL
    for row, col, char, colorPair in cache:
        try:
            pad.addstr(row, col, char, curses.color_pair(colorPair) | dimAttr)
        except curses.error:
            pass
