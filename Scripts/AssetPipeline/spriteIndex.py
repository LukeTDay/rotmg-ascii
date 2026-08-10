"""
Decodes `spritesheetf.bin` (from `extractBundles.py`) - the binary file
mapping a sprite-sheet name + index (from XML `<Texture><File>/<Index>`
refs) to a pixel rect in one of the four spritesheet PNGs.

FlatBuffers buffer with no bundled schema; `schemas/spritesheet.fbs` was
recovered from RealmShark's compiled Java bindings and confirmed by
decoding real sprites (e.g. cropping Health Potion) at the resulting coords.

`generated/` (committed) holds the flatc-compiled Python bindings - only
regenerate them (`flatc` needed, not in requirements.txt) if
spritesheet.fbs changes:

    flatc --python -o Scripts/AssetPipeline/generated Scripts/AssetPipeline/schemas/spritesheet.fbs

`aId` on a Sprite selects which spritesheet PNG it lives in, fixed order:
1=groundTiles, 2=characters, 3=characters_masks, 4=mapObjects.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

GENERATED_DIR = Path(__file__).resolve().parent / "generated"
if str(GENERATED_DIR) not in sys.path:
    # flatc's codegen uses flat same-directory imports, not package-relative ones.
    sys.path.insert(0, str(GENERATED_DIR))

from SpriteSheetRoot import SpriteSheetRoot  # noqa: E402

AID_TO_SHEET = {1: "groundTiles", 2: "characters", 3: "characters_masks", 4: "mapObjects"}


@dataclass(frozen=True)
class SpriteRect:
    sheet: str  # one of AID_TO_SHEET's values ("groundTiles", "characters", ...)
    x: int
    y: int
    w: int
    h: int
    color: tuple[float, float, float, float]  # (r, g, b, a), each 0.0-1.0


def _rect_from_sprite(sprite) -> SpriteRect | None:
    a_id = sprite.AId()
    position = sprite.Position()
    if position is None or a_id not in AID_TO_SHEET:
        return None
    color = sprite.MostCommonColor()
    rgba = (color.R(), color.G(), color.B(), color.A()) if color is not None else (0.0, 0.0, 0.0, 0.0)
    return SpriteRect(
        sheet=AID_TO_SHEET[a_id],
        x=int(position.X()),
        y=int(position.Y()),
        w=int(position.W()),
        h=int(position.H()),
        color=rgba,
    )


def loadSpriteIndex(path: Path) -> dict[str, dict[int, SpriteRect]]:
    """
    Parse `spritesheetf.bin` into `{spriteSheetName: {index: SpriteRect}}`,
    matching the `<Texture><File>name</File><Index>index</Index></Texture>`
    references found in the game's object/ground XML.
    """
    buf = path.read_bytes()
    root = SpriteSheetRoot.GetRootAs(buf, 0)

    index: dict[str, dict[int, SpriteRect]] = {}

    for i in range(root.SpritesLength()):
        sheet = root.Sprites(i)
        sheet_name_bytes = sheet.Name()
        if sheet_name_bytes is None:
            continue
        # generated Table.String() returns raw bytes, not str
        bucket = index.setdefault(sheet_name_bytes.decode("utf-8"), {})
        for j in range(sheet.SpritesLength()):
            sprite = sheet.Sprites(j)
            rect = _rect_from_sprite(sprite)
            if rect is not None:
                bucket[sprite.Index()] = rect

    for i in range(root.AnimatedSpritesLength()):
        anim = root.AnimatedSprites(i)
        name_bytes = anim.Name()
        sprite = anim.Sprites()
        if name_bytes is None or sprite is None:
            continue
        rect = _rect_from_sprite(sprite)
        if rect is not None:
            index.setdefault(name_bytes.decode("utf-8"), {})[anim.Index()] = rect

    return index


if __name__ == "__main__":
    default_path = Path(__file__).resolve().parents[2] / "Resources" / "_generated" / "spritesheetf.bin"
    sprite_index = loadSpriteIndex(default_path)
    total_sprites = sum(len(v) for v in sprite_index.values())
    print(f"Parsed {len(sprite_index)} sprite sheets, {total_sprites} total sprites.")
    for name in sorted(sprite_index)[:10]:
        sample_index = next(iter(sprite_index[name]))
        print(f"  {name} ({len(sprite_index[name])} sprites) e.g. [{sample_index}] -> {sprite_index[name][sample_index]}")
