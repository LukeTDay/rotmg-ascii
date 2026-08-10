"""
Derives the final per-entity render info (display name, ASCII glyph(s),
curses color name) from the identity + sprite data `parseGameXml.py` and
`spriteIndex.py` produce.

Color starts from each `Sprite`'s game-computed `mostCommonColor` (found
while building `spriteIndex.py`) rather than pixel-sampling/cropping (the
plan's original approach) - but "most common pixel" turned out to pick the
sprite's black outline on ~46% of entities (confirmed against a real
install: a small pixel-art icon usually has more outline pixels than fill
pixels), which would render as invisible text on a typical black terminal
background. So whenever that thresholds to BLACK, this falls back to
actually cropping the sprite and searching its real pixels - starting at
the center and moving outward in expanding rings, since the center of an
icon is where its "identity" color lives and the outline is at the edges -
for the first non-outline (non-near-black), non-transparent pixel. If the
whole sprite is genuinely dark/grey (no such pixel exists), it falls back
to WHITE - curses' 8-color palette has no true grey, and WHITE is the
closest still-visible-on-black substitute.

The RGB-cube-corner threshold mapping itself is exact, not a
nearest-neighbor search: curses/ANSI's 8 base colors are literally the 8
corners of the RGB cube (`Constants/ColorPairs.py`'s design notes confirm
`curses.COLOR_RED`..`curses.COLOR_WHITE` are the integers 1-7 on this
project's target platforms), so thresholding each channel at its midpoint
and combining the bits *is* the nearest corner - R=bit0, G=bit1, B=bit2,
matching curses'/ANSI's own color numbering (1=RED, 2=GREEN, 4=BLUE,
3=YELLOW=R+G, 5=MAGENTA=R+B, 6=CYAN=G+B, 7=WHITE=R+G+B, 0=BLACK).

`chars` is a list per the project's design (a renderer can vary the glyph
per-instance for texture, e.g. a floor rendering as `.` sometimes and `,`
other times - see `Models/TileManager.py`'s `_pickChar`) - auto-derivation
here always produces a single-element list from a simple per-category
default glyph; assigning a curated multi-glyph list to a specific id
(floors, loot bags, etc.) is Phase 4's override file's job, not something
guessed here from pixel data. (A ground entity's `<RandomTexture>` variants
resolve to multiple sprite rects here, but only the first is used for
color - auto-generating a matching multi-glyph list from that was tried and
reverted, it read as too visually noisy across a whole floor.)
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    # allow running this file directly (`python deriveRenderInfo.py`), not
    # just via `python -m Scripts.AssetPipeline.deriveRenderInfo`
    sys.path.insert(0, _REPO_ROOT)

from Scripts.AssetPipeline.parseGameXml import ParsedEntity, resolveSpriteRects
from Scripts.AssetPipeline.spriteIndex import AID_TO_SHEET, SpriteRect

CURSES_COLOR_NAMES = ["BLACK", "RED", "GREEN", "YELLOW", "BLUE", "MAGENTA", "CYAN", "WHITE"]

DEFAULT_CHARS = {"objects": "*", "ground": "."}
PORTAL_CHAR = "^"
INTERACTIVE_NPC_CHAR = "?"
LOOT_BAG_CHAR = "$"

# Below this brightness (0-1, max channel), a pixel is treated as outline/
# shadow rather than the sprite's "identity" color, during the center-out
# pixel search fallback.
NEAR_BLACK_THRESHOLD = 0.15

VISIBLE_FALLBACK_COLOR = "WHITE"

# Loot bag sprites use colors the generic RGB-cube-corner quantizer
# (nearestCursesColor) handles badly: there's no true BROWN corner (a brown
# bag rounds to RED), and pure-magenta rounding loses indigo/purple bags
# entirely. Classified instead by nearest match against reference colors
# sampled directly from the real bag sprites - curses has no brown, so
# brown bags use YELLOW, the standard 8-color-terminal/roguelike stand-in.
_BAG_COLOR_REFERENCES = {
    "YELLOW": (0.68, 0.42, 0.18),   # brown/tan bags
    "MAGENTA": (0.65, 0.07, 0.75),  # purple bags (pink-magenta and indigo variants both land here)
    "BLUE": (0.05, 0.30, 0.75),     # blue bags
    "RED": (0.84, 0.12, 0.12),      # red bags
    "WHITE": (0.80, 0.80, 0.80),    # white/grey bags
}

@dataclass(frozen=True)
class RenderInfo:
    name: str
    chars: list[str]
    color: str
    blocksMovement: bool = False
    isEnemy: bool = False
    isLootBag: bool = False
    isPortal: bool = False
    isInteractiveNpc: bool = False


def nearestCursesColor(r: float, g: float, b: float) -> str:
    index = (1 if r >= 0.5 else 0) | (2 if g >= 0.5 else 0) | (4 if b >= 0.5 else 0)
    return CURSES_COLOR_NAMES[index]


def classifyBagColor(r: float, g: float, b: float) -> str:
    return min(
        _BAG_COLOR_REFERENCES,
        key=lambda name: sum((c1 - c2) ** 2 for c1, c2 in zip((r, g, b), _BAG_COLOR_REFERENCES[name])),
    )


def _firstAlphaChar(name: str) -> str | None:
    match = re.search(r"[A-Za-z]", name)
    return match.group(0) if match else None


def loadSheetImages(png_dir: Path) -> dict[str, Image.Image]:
    """Opens the four spritesheet PNGs once, for the center-out pixel search fallback."""
    return {sheet: Image.open(png_dir / f"{sheet}.png").convert("RGBA") for sheet in set(AID_TO_SHEET.values())}


def findRepresentativeColor(image: Image.Image, rect: SpriteRect) -> tuple[float, float, float] | None:
    """
    Search a sprite's real pixels for its "identity" color: start at the
    crop's center and expand outward, skipping transparent pixels and
    near-black (outline/shadow) pixels. Returns None if every opaque pixel
    in the sprite is near-black (a genuinely dark/grey sprite).
    """
    crop = image.crop((rect.x, rect.y, rect.x + rect.w, rect.y + rect.h))
    px = crop.load()
    w, h = crop.size
    cx, cy = (w - 1) / 2, (h - 1) / 2

    opaque_pixels = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a >= 128:
                opaque_pixels.append((x, y, r / 255, g / 255, b / 255))
    opaque_pixels.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)

    for _x, _y, r, g, b in opaque_pixels:
        if max(r, g, b) >= NEAR_BLACK_THRESHOLD:
            return (r, g, b)
    return None


def deriveRenderInfo(
    category: str,
    entity: ParsedEntity,
    sprite_index: dict[str, dict[int, SpriteRect]],
    sheet_images: dict[str, Image.Image],
) -> RenderInfo | None:
    rects = resolveSpriteRects(entity, sprite_index)
    if not rects:
        return None
    rect = rects[0]
    r, g, b, _a = rect.color

    # Both branches below are ordered to match the map renderer's own tier
    # priority (Models/TileManager.py's _TIER_PRIORITY: self > enemy > loot
    # bag > wall > portal > interactive NPC > other player) - a handful of
    # entities are flagged as more than one of these (e.g. a "DPS Guill"
    # training-dummy object is both Enemy and Merchant-class), and whichever
    # branch is checked first here has to be the one that actually wins the
    # tile at render time, or the glyph baked in here won't match what
    # `classifyObject` renders it as.
    if entity.isEnemy:
        # A letter from the monster's own name reads at a glance far better
        # than a generic '*' once there are hundreds of enemy types on
        # screen - lowercase by default, uppercase for HealthBarBoss-flagged
        # bosses (the same flag the real client uses for the big boss
        # health-bar UI), matching the classic roguelike convention.
        color = nearestCursesColor(r, g, b)
        if color == "BLACK":
            found = findRepresentativeColor(sheet_images[rect.sheet], rect)
            if found is not None:
                color = nearestCursesColor(*found)
            # Either nothing but near-black pixels exist, or the best pixel
            # found is still grey/dark enough to classify as BLACK -
            # genuinely a dark/grey sprite either way. Substitute a color
            # that's still visible on a black terminal background.
            if color == "BLACK":
                color = VISIBLE_FALLBACK_COLOR
        letter = _firstAlphaChar(entity.name)
        chars = [letter.upper() if entity.isBoss else letter.lower()] if letter else [DEFAULT_CHARS.get(category, "?")]
    elif entity.isLootBag:
        # Bag color signals rarity/contents to the player - it's the whole
        # point of the glyph, so it's classified from the sprite's real
        # color instead of going through the generic BLACK/center-out-search
        # fallback path (which exists for sprites where color is cosmetic,
        # not informational).
        color = classifyBagColor(r, g, b)
        chars = [LOOT_BAG_CHAR]
    else:
        color = nearestCursesColor(r, g, b)
        if color == "BLACK":
            found = findRepresentativeColor(sheet_images[rect.sheet], rect)
            if found is not None:
                color = nearestCursesColor(*found)
            if color == "BLACK":
                color = VISIBLE_FALLBACK_COLOR

        if entity.isPortal:
            chars = [PORTAL_CHAR]
        elif entity.isInteractiveNpc:
            chars = [INTERACTIVE_NPC_CHAR]
        else:
            chars = [DEFAULT_CHARS.get(category, "?")]

    return RenderInfo(
        name=entity.name,
        chars=chars,
        color=color,
        blocksMovement=entity.blocksMovement,
        isEnemy=entity.isEnemy,
        isLootBag=entity.isLootBag,
        isPortal=entity.isPortal,
        isInteractiveNpc=entity.isInteractiveNpc,
    )


def deriveAll(
    parsed: dict, sprite_index: dict[str, dict[int, SpriteRect]], sheet_images: dict[str, Image.Image]
) -> dict[str, dict[int, RenderInfo]]:
    result: dict[str, dict[int, RenderInfo]] = {"objects": {}, "ground": {}}
    for category in ("objects", "ground"):
        for entity_id, entity in parsed[category].items():
            info = deriveRenderInfo(category, entity, sprite_index, sheet_images)
            if info is not None:
                result[category][entity_id] = info
    return result


if __name__ == "__main__":
    import time

    from Scripts.AssetPipeline.parseGameXml import GENERATED_ROOT, parseAll
    from Scripts.AssetPipeline.spriteIndex import loadSpriteIndex

    parsed = parseAll()
    sprite_index = loadSpriteIndex(GENERATED_ROOT / "spritesheetf.bin")
    sheet_images = loadSheetImages(GENERATED_ROOT / "png")

    t0 = time.time()
    derived = deriveAll(parsed, sprite_index, sheet_images)
    print(f"Derived in {time.time() - t0:.1f}s")

    print(f"Derived render info for {len(derived['objects'])} objects, {len(derived['ground'])} ground types")

    color_counts: dict[str, int] = {}
    for category in ("objects", "ground"):
        for info in derived[category].values():
            color_counts[info.color] = color_counts.get(info.color, 0) + 1
    print(f"Color distribution: {color_counts}")

    for entity_id, name in [(2594, "Health Potion"), (0, "Black Water"), (29997, "O3 Longsword")]:
        for category in ("objects", "ground"):
            info = derived[category].get(entity_id)
            if info is not None:
                print(f"  [{category}] {entity_id} ({name}): {info}")
