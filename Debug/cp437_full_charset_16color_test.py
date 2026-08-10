"""
Every usable glyph (ASCII 32-126 + CP437 extended 128-255) x the native
8-color palette (normal + bold = 16 columns).

Unlike cp437_full_charset_color_test.py, this only uses curses.COLOR_* +
curses.init_pair(), never init_color() -- avoids that script's bug where
custom color slots starting at 1 collided with curses.COLOR_RED..WHITE
(also 1-7) and corrupted default text color on Linux.

Controls: arrow keys / hjkl to scroll, q or Esc to quit.
Run: python cp437_full_charset_16color_test.py
"""

import curses
import locale

# 0x00-0x1F and 0x7F decode to literal ASCII control chars under cp437, not
# the historical CP437 graphic glyphs, so they're excluded.
CHAR_CODES = list(range(0x20, 0x7F)) + list(range(0x80, 0x100))

NAMED_COLORS = [
    ("BLACK", curses.COLOR_BLACK, "K"),
    ("RED", curses.COLOR_RED, "R"),
    ("GREEN", curses.COLOR_GREEN, "G"),
    ("YELLOW", curses.COLOR_YELLOW, "Y"),
    ("BLUE", curses.COLOR_BLUE, "U"),
    ("MAGENTA", curses.COLOR_MAGENTA, "M"),
    ("CYAN", curses.COLOR_CYAN, "C"),
    ("WHITE", curses.COLOR_WHITE, "W"),
]

CELL_WIDTH = 4
LABEL_WIDTH = 8


def build_columns():
    """One curses pair per named color, reused for both the normal and bold column."""
    columns = []
    for i, (_name, color, initial) in enumerate(NAMED_COLORS, start=1):
        curses.init_pair(i, color, curses.COLOR_BLACK)
        columns.append((initial, i, 0))
        columns.append((initial + "'", i, curses.A_BOLD))
    return columns


def draw_pad(columns):
    pad_rows = 1 + len(CHAR_CODES)
    pad_cols = LABEL_WIDTH + len(columns) * CELL_WIDTH
    pad = curses.newpad(pad_rows, pad_cols)

    col = LABEL_WIDTH
    for header, _pair_num, _attr in columns:
        pad.addstr(0, col, header.ljust(CELL_WIDTH))
        col += CELL_WIDTH

    for row, code in enumerate(CHAR_CODES, start=1):
        ch = bytes([code]).decode("cp437")
        label = f"{code:3d}:{ch}"
        try:
            pad.addstr(row, 0, label.ljust(LABEL_WIDTH))
        except curses.error:
            pass
        col = LABEL_WIDTH
        for _header, pair_num, extra_attr in columns:
            attr = curses.color_pair(pair_num) | extra_attr
            try:
                pad.addstr(row, col, f" {ch}  ", attr)
            except curses.error:
                pass  # bottom-right pad cell write is a known curses quirk
            col += CELL_WIDTH

    return pad, pad_rows, pad_cols


def main(stdscr):
    curses.curs_set(0)
    curses.start_color()

    columns = build_columns()
    pad, pad_rows, pad_cols = draw_pad(columns)

    HEADER_LINES = 4
    stdscr.addstr(0, 0, "CP437 full charset x native 16-color palette (8 colors x normal/bold).")
    stdscr.addstr(1, 0, f"{len(CHAR_CODES)} glyphs x {len(columns)} color columns. No RGB remap involved.")
    stdscr.addstr(2, 0, "Cols: K R G Y U M C W (normal) then same again with ' = bold. K=BLACK is invisible.")
    stdscr.addstr(3, 0, "Arrows/hjkl to scroll, q/Esc to quit.")
    stdscr.refresh()

    top, left = 0, 0
    prev_top, prev_left = None, None
    while True:
        max_y, max_x = stdscr.getmaxyx()
        view_height = max(1, max_y - HEADER_LINES)
        view_width = max(1, max_x)
        top = max(0, min(top, max(0, pad_rows - view_height)))
        left = max(0, min(left, max(0, pad_cols - view_width)))

        if (top, left) != (prev_top, prev_left):
            pad.refresh(top, left, HEADER_LINES, 0, HEADER_LINES + view_height - 1, view_width - 1)
            prev_top, prev_left = top, left

        key = stdscr.getch()
        if key in (ord("q"), 27):
            break
        elif key in (curses.KEY_DOWN, ord("j")):
            top += 1
        elif key in (curses.KEY_UP, ord("k")):
            top -= 1
        elif key in (curses.KEY_RIGHT, ord("l")):
            left += CELL_WIDTH
        elif key in (curses.KEY_LEFT, ord("h")):
            left -= CELL_WIDTH
        elif key == curses.KEY_NPAGE:
            top += view_height
        elif key == curses.KEY_PPAGE:
            top -= view_height


if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "")
    curses.wrapper(main)
