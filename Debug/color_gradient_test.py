"""
Standalone test for the console color-gradient question we were discussing:
  - How many distinct color "slots" does this terminal actually give us?
  - Can we redefine those slots' RGB values (curses.init_color)?
  - What happens when we ask for more gradient shades than we have slots?

This tries to build 4 shades each of 7 base hues (28 swatches total) by
remapping the curses color palette. On a 16-color Windows console
(windows-curses) you'll only get ~15 usable slots -- index 0 is left alone
so the diagnostic text stays readable -- so roughly half the requested
swatches fall back to a plain dim attribute instead of a real color. On a
256-color Linux terminal, all 28 should get their own distinct RGB with
room to spare, which is exactly the Windows-vs-Linux difference we were
talking about.

Run: python color_gradient_test.py
"""

import curses

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


def rgb_to_curses(r, g, b):
    """Convert 0-255 RGB to curses' 0-1000 scale."""
    return (int(r / 255 * 1000), int(g / 255 * 1000), int(b / 255 * 1000))


def main(stdscr):
    curses.curs_set(0)
    curses.start_color()

    can_change = curses.can_change_color()
    total_colors = curses.COLORS
    total_pairs = curses.COLOR_PAIRS

    # Reserve slot 0 (COLOR_BLACK) so the default pair our own UI text uses
    # doesn't get repainted out from under us mid-test.
    usable_slots = list(range(1, total_colors))

    swatches = []  # (hue_name, frac, attr, ok, requested_rgb, actual_rgb)
    next_slot_i = 0
    for name, base in HUES:
        for frac in SHADES:
            r, g, b = (int(c * frac) for c in base)
            ok = False
            attr = curses.A_DIM  # fallback look when no slot is available
            requested = (r, g, b)
            actual = None
            if next_slot_i < len(usable_slots):
                slot = usable_slots[next_slot_i]
                pair_num = next_slot_i + 1  # pair numbers 1..len(usable_slots)
                next_slot_i += 1
                try:
                    if can_change:
                        cr, cg, cb = rgb_to_curses(r, g, b)
                        curses.init_color(slot, cr, cg, cb)
                        ok = True
                        # Read back what the terminal actually stored, in
                        # case init_color was silently ignored or the
                        # channels got scrambled on the way in.
                        ar, ag, ab = curses.color_content(slot)
                        actual = tuple(int(v / 1000 * 255) for v in (ar, ag, ab))
                    brightness = (r + g + b) / 3
                    fg = curses.COLOR_BLACK if brightness > 140 else curses.COLOR_WHITE
                    curses.init_pair(pair_num, fg, slot)
                    attr = curses.color_pair(pair_num)
                except curses.error:
                    ok = False
            swatches.append((name, frac, attr, ok, requested, actual))

    stdscr.clear()
    row = 0
    stdscr.addstr(row, 0, "Color gradient test: 7 hues x 4 shades = 28 requested swatches")
    row += 1
    stdscr.addstr(
        row, 0,
        f"COLORS={total_colors}  COLOR_PAIRS={total_pairs}  "
        f"can_change_color={can_change}  usable_slots={len(usable_slots)}",
    )
    row += 2

    ok_count = sum(1 for s in swatches if s[3])
    stdscr.addstr(row, 0, f"Got a unique color for {ok_count} / {len(swatches)} requested swatches.")
    row += 2

    current = None
    col = 9
    for name, frac, attr, ok, _requested, _actual in swatches:
        if name != current:
            row += 1 if current is not None else 0
            stdscr.addstr(row, 0, f"{name:<8}")
            col = 9
            current = name
        label = f" {int(frac * 100):3d}%{'' if ok else '!'} "
        try:
            stdscr.addstr(row, col, label, attr)
        except curses.error:
            pass
        col += len(label) + 1

    row += 3
    stdscr.addstr(row, 0, "'!' = no free slot / redefinition failed -> drawn dim instead of a real color.")
    row += 1
    stdscr.addstr(row, 0, "Press any key to continue (a plain-text report prints after you exit).")
    stdscr.refresh()
    stdscr.getch()

    return {
        "colors": total_colors,
        "pairs": total_pairs,
        "can_change_color": can_change,
        "usable_slots": len(usable_slots),
        "swatches": [
            (name, frac, ok, requested, actual)
            for name, frac, _, ok, requested, actual in swatches
        ],
    }


if __name__ == "__main__":
    result = curses.wrapper(main)

    # curses.wrapper has already restored the normal terminal by the time
    # we get here, so a plain print() report is what actually stays on
    # screen / in scrollback once the program exits.
    print(f"COLORS={result['colors']}  COLOR_PAIRS={result['pairs']}  "
          f"can_change_color={result['can_change_color']}  usable_slots={result['usable_slots']}")
    print()
    print(f"  {'HUE':<8} {'SHADE':>6}  {'STATUS':<6} {'REQUESTED RGB':<16} ACTUAL RGB (read back)")
    mismatches = 0
    for name, frac, ok, requested, actual in result["swatches"]:
        status = "OK" if ok else "FAIL"
        actual_str = str(actual) if actual is not None else "-"
        match_flag = ""
        if ok and actual is not None:
            # Allow a little slack for 0-1000 <-> 0-255 rounding.
            if any(abs(a - r) > 15 for a, r in zip(actual, requested)):
                match_flag = "  <-- MISMATCH"
                mismatches += 1
        print(f"  {name:<8} {int(frac * 100):>5}%  {status:<6} {str(requested):<16} {actual_str}{match_flag}")

    ok_count = sum(1 for _, _, ok, _, _ in result["swatches"] if ok)
    print()
    print(f"{ok_count} / {len(result['swatches'])} swatches got a color slot assigned.")
    if mismatches:
        print(f"{mismatches} of those had a requested-vs-actual RGB mismatch after read-back -- "
              f"init_color() reported success but the terminal stored a different color than asked.")
    elif ok_count:
        print("Read-back RGB matched what was requested for every assigned swatch -- "
              "so if the on-screen colors still looked wrong, it's a rendering/display issue "
              "(e.g. console font/ClearType color smoothing, or a stale repaint) rather than "
              "curses failing to set the palette.")
