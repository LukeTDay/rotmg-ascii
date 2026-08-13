import curses

from Constants import ColorPairs
from Constants.StatTypes import StatTypes
from Models.GameState import GameState
from Renders.GameScreen.hitDetection import EnemyTargetTracker
from Renders.GameScreen.mapRenderer import computeScale
from Utils.json.objectNameLoader import objectRenderInfo

BAR_ROW = 1  # name on row 0, bar on row 1 - top-left corner of the map area


def _shortNumber(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}m"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _drawHpBar(pad: curses.window, row: int, col: int, width: int, current: int, maximum: int) -> None:
    """Same proportional-fill look as inventoryPanel._drawBar, but with
    shortened numbers - raw HP text would overflow the bar for anything with
    HP in the hundreds of thousands (common for real bosses)."""
    filled = 0 if maximum <= 0 else round(width * max(0, min(current, maximum)) / maximum)
    filled = max(0, min(width, filled))
    text = f"{_shortNumber(current)}/{_shortNumber(maximum)}"[:width].center(width)
    try:
        if filled > 0:
            pad.addstr(row, col, text[:filled], curses.color_pair(ColorPairs.FILL_RED))
        if filled < width:
            pad.addstr(row, col + filled, text[filled:], curses.color_pair(ColorPairs.MAP_RED))
    except curses.error:
        pass


def drawEnemyHealthBar(pad: curses.window, stdscr: curses.window, state: GameState,
                        targetTracker: EnemyTargetTracker, nowMs: float) -> None:
    """Overlays a name+HP-bar strip on the map area's top-left corner for
    whichever enemy targetTracker currently points at - drawn directly over
    the map (not carved out of mapRenderer.computeScale's row budget), same
    pad as everything else gameScreen.py composites post-drawFrame."""
    targetId = targetTracker.targetId
    if targetId is None:
        return

    obj = state.objects.get(targetId)
    if obj is None:
        # Enemy died (removed from state.objects via UPDATE's drops list) -
        # bar disappears, and the next hit picks a fresh target immediately.
        targetTracker.clear()
        return

    hpStat = obj.stats.get(StatTypes.HPSTAT)
    maxHpStat = obj.stats.get(StatTypes.MAXHPSTAT)
    if hpStat is None or maxHpStat is None:
        return
    hp, maxHp = hpStat.statValue, maxHpStat.statValue
    if hp <= 0:
        targetTracker.clear()
        return

    info = objectRenderInfo(obj.objectType)
    name = info.name if info is not None else str(obj.objectType)

    _, _, _, mapAreaCols, _, mapStartCol = computeScale(stdscr)
    nameColor = ColorPairs.MAP_YELLOW if targetTracker.isBossTarget else ColorPairs.MAP_WHITE
    try:
        pad.addstr(0, mapStartCol, name[:mapAreaCols].center(mapAreaCols), curses.color_pair(nameColor))
    except curses.error:
        pass
    _drawHpBar(pad, BAR_ROW, mapStartCol, mapAreaCols, hp, maxHp)
