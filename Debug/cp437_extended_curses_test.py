"""
Curses counterpart to cp437_extended_test.py.

Printing straight to stdout and drawing through curses.addstr() are two
different pipelines -- CLAUDE.md documents exactly this split already for
color (raw ANSI truecolor works; curses' init_color()/color_pair() gets
mangled on Windows because it's routed through the legacy console palette
API instead of ConPTY). The same kind of divergence is possible for glyphs:
curses.window.addstr() encodes the string using the window's `.encoding`
(derived from the process locale, not "whatever the terminal happens to
accept"), and on Windows that locale is very often NOT UTF-8 -- so a
character that printed fine in cp437_extended_test.py can still fail, get
silently replaced, or raise here.

This prints each CP437 extended code point (128-255) through addstr() and
reports which ones actually succeeded, so "it printed fine raw" claims can
be checked against "it also works through curses" rather than assumed.

Run: python cp437_extended_curses_test.py
"""

import curses
import locale


def main(stdscr):
    curses.curs_set(0)
    stdscr.clear()

    stdscr.addstr(0, 0, "CP437 extended range test -- via curses.addstr(), not raw print().")
    stdscr.addstr(1, 0, f"curses window encoding: {stdscr.encoding}")

    cols = 8
    cell_width = 8
    grid_top = 3
    failed = []

    row = grid_top
    col = 0
    for code in range(128, 256):
        ch = bytes([code]).decode("cp437")
        label = f"{code:3d}:{ch}"
        try:
            stdscr.addstr(row, col, label)
        except (curses.error, UnicodeEncodeError, UnicodeDecodeError):
            stdscr.addstr(row, col, f"{code:3d}:?")
            failed.append(code)
        col += cell_width
        if col >= cols * cell_width:
            col = 0
            row += 1

    row += 2
    if failed:
        stdscr.addstr(row, 0, f"{len(failed)} code point(s) failed through curses (shown as '?'):")
        row += 1
        stdscr.addstr(row, 0, ", ".join(str(c) for c in failed)[:curses.COLS - 1])
        row += 1
    else:
        stdscr.addstr(row, 0, "All 128 code points rendered through curses without error.")
        row += 1

    row += 1
    stdscr.addstr(row, 0, "Compare each glyph here against cp437_extended_test.py's raw-print output --")
    row += 1
    stdscr.addstr(row, 0, "any mismatch or '?' means that code point isn't safe to use via curses.addstr().")
    row += 2
    stdscr.addstr(row, 0, "Press any key to exit.")
    stdscr.refresh()
    stdscr.getch()


if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "")
    curses.wrapper(main)
