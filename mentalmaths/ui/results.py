import curses
import math
from typing import List

from ..models import Question
from .helpers import _push, _center, _box
from .viz import show_viz


def _q_line(q: Question) -> str:
    line = f"[{'+' if q.correct else '-'}]  {q.display} = {q.answer_str}"
    if not q.correct:
        line += f"  (you: {q.user_answer})"
    return line


def show_results(
    stdscr,
    questions: List[Question],
    sessions: list,
    guest_mode: bool = False,
    save_error: bool = False,
) -> str:
    """Returns 'again', 'menu', or 'quit'."""
    curses.curs_set(0)
    stdscr.nodelay(False)
    total = len(questions)
    row_scroll = 0

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _box(stdscr)

        correct = sum(1 for q in questions if q.correct)
        pct = correct / total * 100 if total else 0
        _center(stdscr, 1, " RESULTS ", curses.A_BOLD | curses.color_pair(2))
        _center(stdscr, 3, f"{correct} / {total} correct  ({pct:.0f}%)", curses.A_BOLD)
        if guest_mode:
            _center(stdscr, 4, "(guest mode — results not saved)", curses.color_pair(4))
        elif save_error:
            _center(stdscr, 4, "(warning: session could not be saved)", curses.color_pair(3))

        list_y = 5
        list_h = h - 8

        if total:
            lines = [_q_line(q) for q in questions]
            max_lw = max(len(line) for line in lines)
            col_gap = 4
            col_w = max_lw + col_gap
            usable_w = w - 4
            num_cols = max(1, usable_w // col_w)
            num_rows = math.ceil(total / num_cols)
            needs_scroll = num_rows > list_h
            max_scroll = max(0, num_rows - list_h) if needs_scroll else 0
            row_scroll = min(row_scroll, max_scroll)

            for vr in range(min(list_h, num_rows - row_scroll)):
                ar = vr + row_scroll
                for col in range(num_cols):
                    q_idx = col * num_rows + ar
                    if q_idx >= total:
                        continue
                    q = questions[q_idx]
                    color = curses.color_pair(1) if q.correct else curses.color_pair(3)
                    try:
                        stdscr.addstr(
                            list_y + vr, 2 + col * col_w, lines[q_idx][:max_lw], color
                        )
                    except curses.error:
                        pass

            if needs_scroll:
                bar_h = max(1, round(list_h / num_rows * list_h))
                bar_top = list_y + round(row_scroll / max_scroll * (list_h - bar_h))
                for dy in range(bar_h):
                    try:
                        stdscr.addstr(bar_top + dy, w - 2, "|")
                    except curses.error:
                        pass
        else:
            needs_scroll = False

        footer = "R again   M menu   V performance   Q quit"
        if needs_scroll:
            footer += "   j/k scroll"
        _center(stdscr, h - 2, footer, curses.A_DIM)
        _push(stdscr)

        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return "quit"
        elif key in (10, 13, curses.KEY_ENTER, ord("r"), ord("R")):
            return "again"
        elif key in (ord("m"), ord("M")):
            return "menu"
        elif key in (ord("v"), ord("V")):
            show_viz(stdscr, sessions)
        elif needs_scroll:
            if key in (curses.KEY_UP, ord("k")) and row_scroll > 0:
                row_scroll -= 1
            elif key in (curses.KEY_DOWN, ord("j")) and row_scroll < max_scroll:
                row_scroll += 1
