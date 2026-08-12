"""
Standalone proof-of-concept for the Kitty keyboard protocol (the extended
CSI-u key reporting scheme), not part of the app -- same pattern as
cp437_full_charset_16color_test.py.

Demonstrates what movementInput.py could gain from this on Linux: real
press/repeat/release events per key, so simultaneous keys (e.g. W+D held
together) can be tracked as actual held state instead of
inputRouter.resolveDirection()'s "last key seen this frame" heuristic --
the same class of problem _pollHeldDirection() solves on Windows via
GetAsyncKeyState, but sourced from terminal protocol events instead of an
OS API, so no focus-proxy trust-window hack is needed.

Talks to the terminal directly via termios/raw stdin rather than curses,
since curses doesn't parse CSI-u sequences -- it would mangle them trying
to interpret the escape bytes itself.

Only WASD is decoded (their key codes are just ASCII codepoints --
unambiguous). Arrow keys use Kitty's separate functional-key-code table;
left as a TODO, see https://sw.kovidgoyal.net/kitty/keyboard-protocol/
for the numbers before wiring them in.

Run in a terminal that implements the protocol (kitty, foot, wezterm,
ghostty, contour, rio):
    python Debug/kitty_keyboard_protocol_poc.py
Hold WASD in any combination and watch the live held-key set / derived
movement vector update. Press q to quit (Ctrl+C is captured by the
protocol as a plain keystroke, not SIGINT, once enabled).
"""

import os
import re
import select
import sys
import termios
import time
import tty

# Progressive-enhancement flags: disambiguate escape codes (1) + report
# event types incl. release (2) + report every key as an escape code (8),
# the last one so plain unmodified letters aren't sent as raw UTF-8 bytes
# alongside CSI-u sequences for everything else -- one consistent format.
ENABLE_FLAGS = 0b1011

QUERY_SUPPORT = "\x1b[?u"
PUSH_FLAGS = f"\x1b[>{ENABLE_FLAGS}u"
POP_FLAGS = "\x1b[<u"
PRIMARY_DA = "\x1b[c"

# CSI unicode-key-code[:alt-codes] [;modifiers[:event-type]] u
KEY_EVENT_RE = re.compile(r"\x1b\[(\d+)(?::\d+)*(?:;(\d+)(?::(\d+))?)?u")

DIRECTION_BY_CHAR = {
    "w": (0, -1),
    "s": (0, 1),
    "a": (-1, 0),
    "d": (1, 0),
}


SUPPORT_REPLY_RE = re.compile(r"\x1b\[\?(\d+)u")
DA_REPLY_RE = re.compile(r"\x1b\[\?[\d;]*c")


def _detect_support(fd, timeout_seconds=0.5):
    """Standard Kitty-recommended detection: race the ?u query against a
    primary Device Attributes query. Whichever reply appears earlier in the
    accumulated buffer is the one that arrived first, and that decides
    support -- checked by match position, not by "buffer ends with", since
    both replies can land in the same os.read() chunk together and then
    the trailing character no longer tells you which came first.

    Reads via os.read() on the raw fd rather than sys.stdin.read() --
    sys.stdin is a buffered TextIOWrapper, and select() only watches the
    underlying fd. If a whole reply arrives in one packet, stdin's internal
    buffer can silently swallow it all on the first read() while handing
    back just 1 char, leaving select() with nothing left to report ready
    and the loop timing out having seen only a fragment."""
    os.write(fd, (QUERY_SUPPORT + PRIMARY_DA).encode())
    buf = ""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select([fd], [], [], max(remaining, 0))
        if not ready:
            break
        buf += os.read(fd, 4096).decode(errors="ignore")
        support_match = SUPPORT_REPLY_RE.search(buf)
        da_match = DA_REPLY_RE.search(buf)
        if support_match and (not da_match or support_match.start() < da_match.start()):
            return True, buf
        if da_match and (not support_match or da_match.start() < support_match.start()):
            return False, buf
    return False, buf


def main():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setraw(fd)
    try:
        supported, raw = _detect_support(fd)
        if not supported:
            sys.stdout.write(
                "\r\nThis terminal doesn't appear to support the Kitty keyboard protocol.\r\n"
                f"\r\n(raw bytes seen during detection: {raw!r})\r\n"
            )
            return

        sys.stdout.write(PUSH_FLAGS)
        sys.stdout.flush()

        held = set()
        buf = ""
        sys.stdout.write("\r\nHold WASD (any combination). Press q to quit.\r\n")
        while True:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if not ready:
                continue
            buf += os.read(fd, 4096).decode(errors="ignore")

            matches = list(KEY_EVENT_RE.finditer(buf))
            if not matches:
                if len(buf) > 64:
                    buf = ""
                continue
            buf = buf[matches[-1].end():]

            quit_requested = False
            for match in matches:
                code = int(match.group(1))
                event_type = int(match.group(3)) if match.group(3) else 1  # 1=press 2=repeat 3=release
                char = chr(code).lower()

                if char == "q" and event_type == 1:
                    quit_requested = True
                    break
                if char not in DIRECTION_BY_CHAR:
                    continue

                if event_type in (1, 2):
                    held.add(char)
                elif event_type == 3:
                    held.discard(char)
            if quit_requested:
                break

            dx = sum(DIRECTION_BY_CHAR[c][0] for c in held)
            dy = sum(DIRECTION_BY_CHAR[c][1] for c in held)
            sys.stdout.write(f"\rheld={sorted(held)!s:<20} vector=({dx:+d},{dy:+d})   ")
            sys.stdout.flush()
    finally:
        sys.stdout.write(POP_FLAGS)
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\r\n")


if __name__ == "__main__":
    main()
