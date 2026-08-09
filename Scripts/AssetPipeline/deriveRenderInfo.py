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

`chars` is a list per the project's design (a future renderer can vary the
glyph per-instance for texture, e.g. a floor rendering as `.` sometimes and
`,` other times) - auto-derivation here always produces a single-element
list from a simple per-category default glyph; assigning a curated
multi-glyph list to a specific id (floors, loot bags, etc.) is Phase 4's
override file's job, not something guessed here from pixel data.
"""

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

# Below this brightness (0-1, max channel), a pixel is treated as outline/
# shadow rather than the sprite's "identity" color, during the center-out
# pixel search fallback.
NEAR_BLACK_THRESHOLD = 0.15

VISIBLE_FALLBACK_COLOR = "WHITE"


@dataclass(frozen=True)
class RenderInfo:
    name: str
    chars: list[str]
    color: str
    blocksMovement: bool = False
    isEnemy: bool = False
    isLootBag: bool = False


def nearestCursesColor(r: float, g: float, b: float) -> str:
    index = (1 if r >= 0.5 else 0) | (2 if g >= 0.5 else 0) | (4 if b >= 0.5 else 0)
    return CURSES_COLOR_NAMES[index]


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
    color = nearestCursesColor(r, g, b)

    if color == "BLACK":
        found = findRepresentativeColor(sheet_images[rect.sheet], rect)
        if found is not None:
            color = nearestCursesColor(*found)
        # Either nothing but near-black pixels exist, or the best pixel found
        # is still grey/dark enough to classify as BLACK - genuinely a
        # dark/grey sprite either way. Substitute a color that's still
        # visible on a black terminal background.
        if color == "BLACK":
            color = VISIBLE_FALLBACK_COLOR

    return RenderInfo(
        name=entity.name,
        chars=[DEFAULT_CHARS.get(category, "?")],
        color=color,
        blocksMovement=entity.blocksMovement,
        isEnemy=entity.isEnemy,
        isLootBag=entity.isLootBag,
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
