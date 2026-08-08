"""
Tests the CP437 "extended" range (bytes 128-255): box-drawing, shading blocks,
accented letters, card suits, etc. CLAUDE.md flags these as unproven -- plain
ASCII (32-126) is confirmed safe on both platforms, but this upper range hasn't
been checked.

Bytes 0-31 are deliberately excluded: Python's cp437 codec maps those to real
ASCII control characters (NUL, ESC, ...), not the graphical glyphs CP437
historically drew for them, so printing them would hit the terminal's control
handling instead of showing a symbol.

Each cell is "code:glyph". Run on both Windows and WSL/Linux and compare --
any code point that shows as a box, a question mark, or the wrong shape on
either one isn't safe to use as a game glyph. Cross-reference against
https://en.wikipedia.org/wiki/Code_page_437 to see what a code is supposed
to look like.

Run: python cp437_extended_test.py
"""

import sys


def enable_vt_processing():
    """Legacy conhost needs ENABLE_VIRTUAL_TERMINAL_PROCESSING turned on
    before it will interpret ANSI escape codes at all. Windows Terminal
    already has this on, so this is a no-op there, but it's what makes
    plain 'python foo.py' in a classic cmd.exe window work too."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass  # best-effort; if this fails we'll just see raw escape junk


def main():
    enable_vt_processing()

    # Python picks stdout's encoding from the console codepage at startup (cp1252
    # on a default Windows console), which can't represent most of this range and
    # raises UnicodeEncodeError. Force UTF-8 out so the bytes are always correct --
    # if the terminal itself isn't in a UTF-8 codepage it'll show mojibake instead
    # of a crash, which is still a legible "this isn't safe" signal.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("CP437 extended range test (bytes 128-255, decoded via Python's 'cp437' codec).")
    print("These are the characters CLAUDE.md flags as unproven -- if a cell renders as a")
    print("box, a question mark, or garbage instead of a real symbol, that code point isn't")
    print("safe to use as a glyph on this terminal/font.\n")

    for row_start in range(128, 256, 16):
        cells = [f"{code:3d}:{bytes([code]).decode('cp437')}" for code in range(row_start, row_start + 16)]
        print("  ".join(cells))

    print("\nCompare this output between Windows and WSL/Linux terminals -- only keep code")
    print("points that look correct AND identical on both.")


if __name__ == "__main__":
    main()
