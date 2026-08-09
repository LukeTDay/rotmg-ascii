"""
Decodes `spritesheetf.bin` (extracted by `extractBundles.py`) — the binary
file that maps a logical sprite-sheet name + index (e.g. the "lofiObj3"/0x555
in an XML `<Texture><File>lofiObj3</File><Index>0x555</Index></Texture>`
reference) to a pixel rect within one of the four real spritesheet PNGs.

It's a FlatBuffers buffer with no bundled schema. `schemas/spritesheet.fbs`
is a schema recovered from the sibling reference project RealmShark's
FlatBuffers-compiler-generated Java bindings (`assets/flattbuffer/*.java` —
see CLAUDE.local.md's "Reference projects" section), independently confirmed
by manually walking the wire format against real extracted bytes, then
verified end to end by cropping known sprites (e.g. the Health Potion) out
of the real PNGs at the decoded coordinates.

`Scripts/AssetPipeline/generated/` (committed) holds the actual Python
bindings `flatc` compiled from that schema — regenerate them if
`spritesheet.fbs` ever needs to change:

    flatc --python -o Scripts/AssetPipeline/generated Scripts/AssetPipeline/schemas/spritesheet.fbs

`flatc` itself is only needed for that regeneration step, not to run the
pipeline day to day — hence it's not in `requirements.txt`, only
`flatbuffers` (the runtime the generated code imports) is.

`aId` on a `Sprite` identifies which of the four spritesheet PNGs it lives
in, 1-indexed in this fixed order (confirmed via RealmShark's
`ImageBuffer.java`): 1=groundTiles, 2=characters, 3=characters_masks,
4=mapObjects.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

GENERATED_DIR = Path(__file__).resolve().parent / "generated"
if str(GENERATED_DIR) not in sys.path:
    # flatc's Python codegen emits flat, same-directory `from X import X`
    # imports between the generated modules rather than package-relative
    # ones, so it expects its own output directory to be importable directly.
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
