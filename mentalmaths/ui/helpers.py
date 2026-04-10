import curses


def _push(stdscr) -> None:
    stdscr.noutrefresh()
    curses.doupdate()


def _center(stdscr, y: int, text: str, attr: int = 0) -> None:
    _, w = stdscr.getmaxyx()
    x = max(0, (w - len(text)) // 2)
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass


def _box(stdscr) -> None:
    try:
        stdscr.box()
    except curses.error:
        pass


def _confirm_quit(stdscr) -> bool:
    h, w = stdscr.getmaxyx()
    msg = "  Quit?   y / n  "
    bw = len(msg) + 4
    bx = max(0, (w - bw) // 2)
    by = h // 2 - 1
    for dy in range(3):
        try:
            stdscr.addstr(by + dy, bx, " " * bw, curses.A_REVERSE)
        except curses.error:
            pass
    try:
        stdscr.addstr(by + 1, bx + 2, msg, curses.A_REVERSE | curses.A_BOLD)
    except curses.error:
        pass
    stdscr.noutrefresh()
    curses.doupdate()
    stdscr.nodelay(False)
    while True:
        key = stdscr.getch()
        if key in (ord("y"), ord("Y")):
            return True
        if key in (ord("n"), ord("N"), 27):
            return False
