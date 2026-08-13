"""
Derives final render info (name, glyph(s), curses color) from parseGameXml.py
+ spriteIndex.py's identity/sprite data.

Color starts from each Sprite's `mostCommonColor`, which picks the sprite's
black outline ~46% of the time (confirmed against a real install) - when
that thresholds to BLACK, falls back to searching real pixels outward from
center for the first non-outline, non-transparent color, then to WHITE if
the whole sprite is genuinely dark/grey.

RGB-cube-corner threshold is exact (not nearest-neighbor): curses' 8 colors
are literally the cube's 8 corners.

`chars` is always a list so a hand override can assign multiple glyphs for
per-tile variety (see `Models/TileManager.py`'s `_pickChar`) - auto-derivation
here only ever produces one. Auto-generating multi-glyph variety from a
ground entity's `<RandomTexture>` variants was tried and reverted (too
visually noisy across a whole floor).
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
BEACON_MARKER_CHAR = "%"  # matches the minimap's teleport-target glyph

# Below this brightness (max channel), a pixel counts as outline/shadow,
# not identity color, during the center-out fallback search.
NEAR_BLACK_THRESHOLD = 0.15

VISIBLE_FALLBACK_COLOR = "YELLOW"  # matches brown/tan loot bags, see _BAG_COLOR_REFERENCES below

# nearestCursesColor handles bag colors badly (no true BROWN corner, indigo/
# purple bags collapse into magenta) - classified instead against reference
# colors sampled from real bag sprites. Brown bags use YELLOW (curses has no
# brown; standard roguelike stand-in).
_BAG_COLOR_REFERENCES = {
    "YELLOW": (0.68, 0.42, 0.18),   # brown/tan bags
    "MAGENTA": (0.65, 0.07, 0.75),  # purple bags (pink-magenta and indigo variants both land here)
    "BLUE": (0.05, 0.30, 0.75),     # blue bags
    "RED": (0.84, 0.12, 0.12),      # red bags
    "WHITE": (0.80, 0.80, 0.80),    # white/grey bags
}

# `bagColorTier` is a heuristic stand-in for RotMG's real per-item <BagType>
# field (which actually drives an item's drop-bag color in game and isn't
# fully reverse-engineered in this repo - see CLAUDE.md's asset-pipeline
# notes) - approximated instead from an item's numeric <Tier>, bucketed into
# the same 5 curses-color names `_BAG_COLOR_REFERENCES` already uses for
# real loot-bag sprite classification, reused here rather than inventing a
# second color vocabulary. RotMG item tiers run roughly 0 through the mid-
# teens; cutoffs below are an even split of that range into ascending
# "value" buckets (brown -> blue -> red -> purple), with items carrying no
# <Tier> at all (very common for UT/ability items) mapped to the top bucket,
# WHITE, since untiered items are typically the most valuable ones in game.
_TIER_COLOR_CUTOFFS = (
    (2, "YELLOW"),  # T0-T2: common/early-game gear
    (5, "BLUE"),    # T3-T5: mid-tier gear
    (8, "RED"),     # T6-T8: high-tier gear
)
_TIER_COLOR_DEFAULT = "MAGENTA"  # T9+: top tiered gear
_UNTIERED_BAG_COLOR = "WHITE"    # no <Tier> at all (UT/ability items)


def deriveBagColorTier(tier: int | None) -> str:
    if tier is None:
        return _UNTIERED_BAG_COLOR
    for maxTier, colorName in _TIER_COLOR_CUTOFFS:
        if tier <= maxTier:
            return colorName
    return _TIER_COLOR_DEFAULT


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
    isBeacon: bool = False
    isBeaconMarker: bool = False
    weaponLabel: str = ""
    bagColorTier: str = _UNTIERED_BAG_COLOR
    # Item-info-peek fields, straight from ParsedEntity - see that dataclass's
    # own field comments for what each one means/when it's absent.
    tier: int | None = None
    mpCost: int | None = None
    mpEndCost: int | None = None
    description: str = ""
    # Hit-detection fields, straight from ParsedEntity - see that dataclass's
    # own field comment for what these mean.
    baseSize: int = 100
    hitboxScale: float | None = None


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
    if entity.isBeacon:
        # Real teleportable beacons use an "invisible" texture by design (see
        # parseGameXml's textureRefs carve-out for isBeacon) - nothing to
        # derive a sprite color from, and nothing ever draws them on the main
        # map. Only the isBeacon flag itself matters downstream.
        return RenderInfo(
            name=entity.name,
            chars=[DEFAULT_CHARS.get(category, "?")],
            color="WHITE",
            blocksMovement=entity.blocksMovement,
            isBeacon=True,
            weaponLabel=entity.weaponLabel,
            bagColorTier=deriveBagColorTier(entity.tier),
            tier=entity.tier,
            mpCost=entity.mpCost,
            mpEndCost=entity.mpEndCost,
            description=entity.description,
            baseSize=entity.baseSize,
            hitboxScale=entity.hitboxScale,
        )

    rects = resolveSpriteRects(entity, sprite_index)
    if not rects:
        return None
    rect = rects[0]
    r, g, b, _a = rect.color

    # Branch order must match TileManager._TIER_PRIORITY (enemy > loot bag >
    # wall > portal > NPC) - some entities are flagged as more than one
    # (e.g. "DPS Guill" is both Enemy and Merchant), and whichever check
    # wins here must match what classifyObject renders at runtime.
    #
    # isBeaconMarker checked first, ahead of even isEnemy: a few "Captured
    # Beacon *" variants incidentally carry <Enemy/> too (see
    # ParsedEntity.isBeaconMarker), but every beacon marker should render as
    # '%' consistently, not sometimes fall back to an enemy letter-glyph.
    # classifyObject still tiers an Enemy-flagged one as Tier.ENEMY (that
    # only affects render precedence when sharing a tile, not the glyph
    # itself, which is fixed here regardless of tier).
    if entity.isBeaconMarker:
        color = nearestCursesColor(r, g, b)
        if color == "BLACK":
            found = findRepresentativeColor(sheet_images[rect.sheet], rect)
            if found is not None:
                color = nearestCursesColor(*found)
            if color == "BLACK":
                color = VISIBLE_FALLBACK_COLOR
        chars = [BEACON_MARKER_CHAR]
    elif entity.isEnemy:
        # Name-derived letter reads better than a generic '*' at scale;
        # uppercase for HealthBarBoss bosses (roguelike convention).
        color = nearestCursesColor(r, g, b)
        if color == "BLACK":
            found = findRepresentativeColor(sheet_images[rect.sheet], rect)
            if found is not None:
                color = nearestCursesColor(*found)
            # Genuinely dark/grey sprite either way - substitute a visible color.
            if color == "BLACK":
                color = VISIBLE_FALLBACK_COLOR
        letter = _firstAlphaChar(entity.name)
        chars = [letter.upper() if entity.isBoss else letter.lower()] if letter else [DEFAULT_CHARS.get(category, "?")]
    elif entity.isLootBag:
        # Bag color signals rarity - classified from real sprite color
        # directly, skipping the BLACK/center-out fallback (that's for
        # sprites where color is merely cosmetic).
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
        isBeaconMarker=entity.isBeaconMarker,
        weaponLabel=entity.weaponLabel,
        bagColorTier=deriveBagColorTier(entity.tier),
        tier=entity.tier,
        mpCost=entity.mpCost,
        mpEndCost=entity.mpEndCost,
        description=entity.description,
        baseSize=entity.baseSize,
        hitboxScale=entity.hitboxScale,
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
