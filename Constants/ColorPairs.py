# Curses color pair numbers, allocated once via curses.init_pair() in main.py.
# Native curses.COLOR_* palette only - RGB remap/raw ANSI don't survive addstr on both platforms.

DEFAULT = 1
FAME = 2
SEASONAL = 3
STANDARD = 4
CRUCIBLE = 5

# Same foreground, white background - avoids reverse-video washing out the hue.
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

# Generic pairs for the map/HUD renderer, independent of the semantic menu pairs above.
MAP_BLACK = 10
MAP_RED = 11
MAP_GREEN = 12
MAP_YELLOW = 13
MAP_BLUE = 14
MAP_MAGENTA = 15
MAP_CYAN = 16
MAP_WHITE = 17

MAP_COLOR_TO_PAIR = {
    "BLACK": MAP_BLACK,
    "RED": MAP_RED,
    "GREEN": MAP_GREEN,
    "YELLOW": MAP_YELLOW,
    "BLUE": MAP_BLUE,
    "MAGENTA": MAP_MAGENTA,
    "CYAN": MAP_CYAN,
    "WHITE": MAP_WHITE,
}

# Black text on solid color, for the filled portion of HUD bars - text sits inside the bar.
FILL_RED = 18
FILL_BLUE = 19
FILL_YELLOW = 20
FILL_WHITE = 21
