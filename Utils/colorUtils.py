"""Runtime RGB -> curses-8-color conversion, for decoding wire colors (e.g.
AoePacket.color) rather than sprite pixels. Mirrors the cube-corner test in
Scripts/AssetPipeline/deriveRenderInfo.nearestCursesColor, but that module is
build-time-only (asset pipeline) and not imported by the live game loop."""

CURSES_COLOR_NAMES = ["BLACK", "RED", "GREEN", "YELLOW", "BLUE", "MAGENTA", "CYAN", "WHITE"]

# True nearest-neighbor among the 7 non-black corners only, for callers that
# must never resolve to BLACK (e.g. AOE tiles, which would otherwise be
# invisible against a black terminal background).
_NON_BLACK_CORNERS = {
    "RED": (1.0, 0.0, 0.0),
    "GREEN": (0.0, 1.0, 0.0),
    "YELLOW": (1.0, 1.0, 0.0),
    "BLUE": (0.0, 0.0, 1.0),
    "MAGENTA": (1.0, 0.0, 1.0),
    "CYAN": (0.0, 1.0, 1.0),
    "WHITE": (1.0, 1.0, 1.0),
}


def nearestCursesColor(rgbInt: int, avoidBlack: bool = False) -> str:
    r = ((rgbInt >> 16) & 0xFF) / 255
    g = ((rgbInt >> 8) & 0xFF) / 255
    b = (rgbInt & 0xFF) / 255

    if avoidBlack:
        return min(
            _NON_BLACK_CORNERS,
            key=lambda name: sum((c1 - c2) ** 2 for c1, c2 in zip((r, g, b), _NON_BLACK_CORNERS[name])),
        )

    index = (1 if r >= 0.5 else 0) | (2 if g >= 0.5 else 0) | (4 if b >= 0.5 else 0)
    return CURSES_COLOR_NAMES[index]
