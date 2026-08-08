"""
Second test, bypassing curses entirely.

Theory: color_gradient_test.py showed init_color()/color_content() agreeing
with each other (curses thinks the palette got set correctly), but the
on-screen colors were still wrong. The likely cause is that Windows Terminal
renders through ConPTY, and the legacy "remap this palette index's RGB" API
(SetConsoleScreenBufferInfoEx, which is what curses.init_color calls under
the hood) is only partially honored across that layer -- Windows Terminal
tends to fall back to its own theme colors regardless of what was requested.

This script skips that API completely and prints real 24-bit ANSI truecolor
escape sequences directly, which Windows Terminal supports natively. If
these render correctly where the curses version didn't, that confirms the
legacy palette API is the broken link, not "Windows can't do gradients".

Run: python ansi_truecolor_test.py
"""

import sys

HUES = [
    ("RED",     (255,  60,  60)),
    ("GREEN",   ( 60, 255,  60)),
    ("YELLOW",  (255, 255,  60)),
    ("BLUE",    ( 70, 110, 255)),
    ("MAGENTA", (255,  70, 255)),
    ("CYAN",    ( 70, 255, 255)),
    ("WHITE",   (255, 255, 255)),
]

SHADES = [0.30, 0.55, 0.80, 1.00]  # dark -> light

RESET = "\x1b[0m"


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


def fg(r, g, b):
    return f"\x1b[38;2;{r};{g};{b}m"


def main():
    enable_vt_processing()

    print("ANSI truecolor test: 7 hues x 4 shades, no curses/palette-index involved.")
    print("Black background (the terminal default), colored glyph text via \\x1b[38;2;r;g;bm --")
    print("this is how it'll actually look in-game: colored characters on a black background.\n")

    for name, base in HUES:
        row = f"{name:<8}"
        for frac in SHADES:
            r, g, b = (int(c * frac) for c in base)
            label = f" {int(frac * 100):3d}% "
            row += fg(r, g, b) + label + RESET + " "
        print(row)

    print()
    print("If these gradients look correct (and the curses ones didn't), "
          "the legacy console palette-remap API is the broken link -- "
          "direct ANSI truecolor is the way to go for this project.")


if __name__ == "__main__":
    main()
