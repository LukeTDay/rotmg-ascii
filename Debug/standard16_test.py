"""
Prints the 16-color palette we're settling on: the 8 named curses colors,
each in a normal and a bold ("bright") variant, with NO init_color/RGB
remapping involved. This is the fixed set that renders natively -- no
ConPTY quantization, no palette-index translation -- so it should look
identical on Windows (VS Code terminal, standalone Windows Terminal,
legacy conhost) and Linux/WSL.

Note: BLACK on the default black background will look invisible/blank --
that's expected and not a bug, it's just color 0 on color 0. Bold black
usually renders as a dark gray instead.

Run: python standard16_test.py
"""

import curses

NAMED_COLORS = [
    ("BLACK",   curses.COLOR_BLACK),
    ("RED",     curses.COLOR_RED),
    ("GREEN",   curses.COLOR_GREEN),
    ("YELLOW",  curses.COLOR_YELLOW),
    ("BLUE",    curses.COLOR_BLUE),
    ("MAGENTA", curses.COLOR_MAGENTA),
    ("CYAN",    curses.COLOR_CYAN),
    ("WHITE",   curses.COLOR_WHITE),
]

SWATCH = "############"


def main(stdscr):
    curses.curs_set(0)
    curses.start_color()

    # One pair per named color, foreground = that color, background =
    # default black. No init_color() calls anywhere -- these are the
    # console's native 8 colors, untouched.
    for i, (_name, color) in enumerate(NAMED_COLORS, start=1):
        curses.init_pair(i, color, curses.COLOR_BLACK)

    stdscr.clear()
    row = 0
    stdscr.addstr(row, 0, "Standard 16-color palette test (8 named colors x normal/bold, no RGB remap)")
    row += 2

    stdscr.addstr(row, 0, "NORMAL:")
    row += 1
    for i, (name, _color) in enumerate(NAMED_COLORS, start=1):
        stdscr.addstr(row, 0, f"  {name:<8}")
        stdscr.addstr(row, 11, SWATCH, curses.color_pair(i))
        row += 1

    row += 1
    stdscr.addstr(row, 0, "BOLD / BRIGHT:")
    row += 1
    for i, (name, _color) in enumerate(NAMED_COLORS, start=1):
        stdscr.addstr(row, 0, f"  {name:<8}")
        stdscr.addstr(row, 11, SWATCH, curses.color_pair(i) | curses.A_BOLD)
        row += 1

    row += 2
    stdscr.addstr(row, 0, "BLACK's swatch being invisible against the default black background is")
    row += 1
    stdscr.addstr(row, 0, "expected -- bold black usually shows as dark gray instead.")
    row += 2
    stdscr.addstr(row, 0, "Press any key to exit.")
    stdscr.refresh()
    stdscr.getch()


if __name__ == "__main__":
    curses.wrapper(main)
