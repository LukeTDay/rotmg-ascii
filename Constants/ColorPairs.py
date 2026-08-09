# Curses color pair numbers, allocated once via curses.init_pair() in main.py.
# Native curses.COLOR_* palette only (no init_color/RGB remap) - the approach
# Debug/cp437_full_charset_16color_test.py confirmed renders identically on
# Windows and Linux. See CLAUDE.md's "Color rendering" section for why raw
# ANSI truecolor isn't used instead (it doesn't survive curses.addstr).

DEFAULT = 1
FAME = 2
SEASONAL = 3
STANDARD = 4
CRUCIBLE = 5

# "_SELECTED" variants: same foreground, white background - used instead of
# the base pair when the row is highlighted, so colored text stays its own
# hue with a highlight behind it instead of being reverse-video'd flat.
FAME_SELECTED = 6
SEASONAL_SELECTED = 7
STANDARD_SELECTED = 8
CRUCIBLE_SELECTED = 9

SELECTED_VARIANT = {
    FAME: FAME_SELECTED,
    SEASONAL: SEASONAL_SELECTED,
    STANDARD: STANDARD_SELECTED,
    CRUCIBLE: CRUCIBLE_SELECTED,
}
