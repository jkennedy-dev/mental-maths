import curses
from typing import List

from ..constants import TIME_OPTIONS
from .helpers import _push, _center, _box


def _draw_history_view(
    stdscr,
    sessions: list,
    y0: int,
    x0: int,
    max_h: int,
    max_w: int,
    metric: int = 0,
    sel: int = -1,
) -> None:
    """Bar chart.
    metric=0: accuracy % per session (colour-coded green/yellow/red), y-axis 0–100%.
    metric=1: stacked bars per session — green=correct, red=wrong, y-axis 0–max_total.
    sel: absolute index into sessions of the selected bar (-1 = none).
    """
    y_lbl_w = 5
    chart_h = max(4, max_h - 4)
    chart_w = max(3, max_w - y_lbl_w - 1)
    n_show = min(len(sessions), chart_w)
    data = sessions[-n_show:]
    ax_x = x0 + y_lbl_w - 1

    # Convert absolute sel to relative index within data
    offset = len(sessions) - n_show
    sel_rel = (sel - offset) if (0 <= sel - offset < n_show) else -1

    # Metric label centred above the chart
    labels = ["< Accuracy % >", "< Correct count >"]
    lbl = labels[metric]
    lbl_x = ax_x + 1 + max(0, (n_show - len(lbl)) // 2)
    try:
        stdscr.addstr(y0, lbl_x, lbl, curses.A_BOLD)
    except curses.error:
        pass
    chart_y = y0 + 1

    # Build x-axis string with cursor marker embedded
    xaxis = [("v" if i == sel_rel else "-") for i in range(n_show)]

    if metric == 0:
        # Accuracy % bars — single colour per session
        for tick in range(5):
            tick_val = tick * 25
            row = chart_y + round((1 - tick / 4) * (chart_h - 1))
            try:
                stdscr.addstr(row, x0, f"{tick_val:>3}%", curses.A_DIM)
                stdscr.addstr(row, ax_x, "|")
            except curses.error:
                pass
        try:
            stdscr.addstr(chart_y + chart_h, ax_x, "+" + "".join(xaxis))
        except curses.error:
            pass
        for i, s in enumerate(data):
            pct = s["correct"] / s["total"] * 100 if s["total"] else 0
            bar_h = round(pct / 100 * chart_h)
            base_clr = (
                curses.color_pair(1)
                if pct >= 70
                else curses.color_pair(4)
                if pct >= 50
                else curses.color_pair(3)
            )
            bold = curses.A_BOLD if i == sel_rel else 0
            for row in range(chart_h):
                from_bottom = chart_h - 1 - row
                if from_bottom < bar_h:
                    char, attr = "#", base_clr | bold
                elif i == sel_rel:
                    char, attr = "|", curses.A_DIM
                else:
                    char, attr = " ", 0
                try:
                    stdscr.addstr(chart_y + row, ax_x + 1 + i, char, attr)
                except curses.error:
                    pass
        # Legend
        legend_y = chart_y + chart_h + 1
        try:
            stdscr.addstr(legend_y, x0, "#", curses.color_pair(1))
            stdscr.addstr(legend_y, x0 + 2, ">=70%", curses.A_DIM)
            stdscr.addstr(legend_y, x0 + 9, "#", curses.color_pair(4))
            stdscr.addstr(legend_y, x0 + 11, ">=50%", curses.A_DIM)
            stdscr.addstr(legend_y, x0 + 18, "#", curses.color_pair(3))
            stdscr.addstr(legend_y, x0 + 20, "<50%", curses.A_DIM)
        except curses.error:
            pass

    else:
        # Stacked bars: green = correct, red = wrong; y-axis 0–max_total
        max_total = max((s["total"] for s in data), default=1) or 1
        for tick in range(5):
            tick_val = round(tick / 4 * max_total)
            row = chart_y + round((1 - tick / 4) * (chart_h - 1))
            try:
                stdscr.addstr(row, x0, f"{tick_val:>3}q", curses.A_DIM)
                stdscr.addstr(row, ax_x, "|")
            except curses.error:
                pass
        try:
            stdscr.addstr(chart_y + chart_h, ax_x, "+" + "".join(xaxis))
        except curses.error:
            pass
        for i, s in enumerate(data):
            total = s["total"]
            correct = s["correct"]
            bar_h = round(total / max_total * chart_h)
            correct_h = round(correct / max_total * chart_h)
            bold = curses.A_BOLD if i == sel_rel else 0
            for row in range(chart_h):
                from_bottom = chart_h - 1 - row
                if from_bottom < correct_h:
                    char, attr = "#", curses.color_pair(1) | bold
                elif from_bottom < bar_h:
                    char, attr = "#", curses.color_pair(3) | bold
                elif i == sel_rel:
                    char, attr = "|", curses.A_DIM
                else:
                    char, attr = " ", 0
                try:
                    stdscr.addstr(chart_y + row, ax_x + 1 + i, char, attr)
                except curses.error:
                    pass
        # Legend
        legend_y = chart_y + chart_h + 1
        try:
            stdscr.addstr(legend_y, x0, "#", curses.color_pair(1))
            stdscr.addstr(legend_y, x0 + 2, "correct", curses.A_DIM)
            stdscr.addstr(legend_y, x0 + 11, "#", curses.color_pair(3))
            stdscr.addstr(legend_y, x0 + 13, "wrong", curses.A_DIM)
        except curses.error:
            pass

    # Bottom info line: selected session summary, or aggregate stats
    info_y = chart_y + chart_h + 2
    if sel_rel >= 0 and 0 <= sel < len(sessions):
        s = sessions[sel]
        pct = s["correct"] / s["total"] * 100 if s["total"] else 0
        info = f"{s['ts']}  {s['correct']}/{s['total']} ({pct:.0f}%)  ENTER for details"
        try:
            stdscr.addstr(info_y, x0, info[:max_w], curses.A_BOLD)
        except curses.error:
            pass
    else:
        all_correct = sum(s["correct"] for s in sessions)
        all_total = sum(s["total"] for s in sessions)
        all_pcts = [s["correct"] / s["total"] * 100 for s in sessions if s["total"]]
        if all_pcts:
            n = len(sessions)
            avg = sum(all_pcts) / len(all_pcts)
            best = max(all_pcts)
            stats = (
                f"{n} session{'s' if n != 1 else ''}  |  "
                f"{all_correct} correct / {all_total} total  |  "
                f"avg {avg:.0f}%  |  best {best:.0f}%"
            )
            try:
                stdscr.addstr(info_y, x0, stats[:max_w], curses.A_DIM)
            except curses.error:
                pass


def _show_session_detail(stdscr, session: dict) -> None:
    """Overlay showing full config and score for one session. Any key dismisses."""
    h, w = stdscr.getmaxyx()

    def _fmt_time(secs: int) -> str:
        return next((lbl for lbl, s in TIME_OPTIONS if s == secs), f"{secs}s")

    lines: List[str] = []
    lines.append(f" Session: {session.get('ts', '?')} ")
    lines.append(f" Time:    {_fmt_time(session.get('time_limit', 0))} ")
    total = session.get("total", 0)
    correct = session.get("correct", 0)
    pct = correct / total * 100 if total else 0
    lines.append(f" Score:   {correct} / {total}  ({pct:.0f}%) ")
    lines.append("")

    configs = session.get("configs", [])
    if configs:
        lines.append(" Operations: ")
        for cfg_d in configs:
            op = cfg_d["operation"]
            lines.append(f"   {op}")
            if op in ("Addition", "Subtraction"):
                lines.append(f"     Digits: {cfg_d.get('digits', 2)}")
            if op == "Multiplication":
                lines.append(
                    f"     Multiplier range: {cfg_d.get('operand2_lo', 2)}"
                    f"–{cfg_d.get('operand2_hi', 12)}"
                )
            elif op == "Division":
                lines.append(
                    f"     Divisor range: {cfg_d.get('operand2_lo', 2)}"
                    f"–{cfg_d.get('operand2_hi', 12)}"
                )
            if cfg_d.get("decimals", 0):
                lines.append(f"     Decimal places: {cfg_d['decimals']}")
            if op == "Subtraction" and cfg_d.get("allow_negative"):
                lines.append("     Allow negatives: yes")
    else:
        per_op = session.get("per_op", {})
        if per_op:
            lines.append(" Operations: ")
            for lbl in per_op:
                lines.append(f"   {lbl}")

    lines.append("")
    lines.append(" Press any key to close ")

    box_w = min(w - 4, max(len(line) for line in lines) + 4)
    box_h = min(h - 4, len(lines) + 2)
    by = max(1, (h - box_h) // 2)
    bx = max(1, (w - box_w) // 2)

    for row in range(box_h):
        try:
            stdscr.addstr(by + row, bx, " " * box_w, curses.A_REVERSE)
        except curses.error:
            pass
    try:
        stdscr.addstr(by, bx, ("┌" + "─" * (box_w - 2) + "┐"), curses.A_REVERSE)
        stdscr.addstr(
            by + box_h - 1, bx, ("└" + "─" * (box_w - 2) + "┘"), curses.A_REVERSE
        )
    except curses.error:
        pass
    for row in range(1, box_h - 1):
        try:
            stdscr.addstr(by + row, bx, "│", curses.A_REVERSE)
            stdscr.addstr(by + row, bx + box_w - 1, "│", curses.A_REVERSE)
        except curses.error:
            pass
    for i, line in enumerate(lines[: box_h - 2]):
        padded = line[: box_w - 2].ljust(box_w - 2)
        try:
            stdscr.addstr(by + 1 + i, bx + 1, padded, curses.A_REVERSE)
        except curses.error:
            pass

    _push(stdscr)
    stdscr.getch()


def _draw_perop_view(stdscr, sessions: list, y0: int, x0: int, max_h: int) -> None:
    op_stats: dict = {}
    for s in sessions:
        for label, counts in s.get("per_op", {}).items():
            st = op_stats.setdefault(
                label, {"total": 0, "correct": 0, "sessions": 0, "pcts": []}
            )
            st["total"] += counts["total"]
            st["correct"] += counts["correct"]
            st["sessions"] += 1
            if counts["total"]:
                st["pcts"].append(counts["correct"] / counts["total"] * 100)

    if not op_stats:
        try:
            stdscr.addstr(y0, x0, "No per-operation data yet.", curses.A_DIM)
        except curses.error:
            pass
        return

    cols = ["Operation", "Sessions", "Total Q", "Correct", "Avg %", "Best %"]
    widths = [26, 9, 8, 8, 7, 7]
    header = "  ".join(f"{c:<{w}}" for c, w in zip(cols, widths))
    try:
        stdscr.addstr(y0, x0, header, curses.A_BOLD)
        stdscr.addstr(y0 + 1, x0, "-" * len(header), curses.A_DIM)
    except curses.error:
        pass

    for i, (label, st) in enumerate(sorted(op_stats.items())):
        if i >= max_h - 3:
            break
        pct = st["correct"] / st["total"] * 100 if st["total"] else 0
        best = max(st["pcts"]) if st["pcts"] else 0
        color = (
            curses.color_pair(1)
            if pct >= 70
            else curses.color_pair(4)
            if pct >= 50
            else curses.color_pair(3)
        )
        row_data = [
            label[:26],
            str(st["sessions"]),
            str(st["total"]),
            str(st["correct"]),
            f"{pct:.0f}%",
            f"{best:.0f}%",
        ]
        line = "  ".join(f"{d:<{w}}" for d, w in zip(row_data, widths))
        try:
            stdscr.addstr(y0 + 2 + i, x0, line, color)
        except curses.error:
            pass


def show_viz(stdscr, sessions: list) -> None:
    """Performance charts. TAB switches between History and By Operation views.
    History tab: j/k switch metric; h/l move bar selection; ENTER shows session detail."""
    view = 0
    history_metric = 0
    # sel: absolute index into sessions (-1 = no selection; start at most recent)
    sel = len(sessions) - 1 if sessions else -1
    stdscr.nodelay(False)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _box(stdscr)
        _center(stdscr, 1, " PERFORMANCE ", curses.A_BOLD | curses.color_pair(2))

        # Tab bar
        tabs = ["[ History ]", "[ By Operation ]"]
        tab_str = "   ".join(tabs)
        tab_x0 = max(0, (w - len(tab_str)) // 2)
        x_cur = tab_x0
        for i, t in enumerate(tabs):
            try:
                stdscr.addstr(
                    2,
                    x_cur,
                    t,
                    curses.A_REVERSE | curses.A_BOLD if i == view else curses.A_DIM,
                )
            except curses.error:
                pass
            x_cur += len(t) + 3

        content_y = 4
        content_h = h - content_y - 3

        if not sessions:
            _center(stdscr, h // 2, "No sessions recorded yet.", curses.A_DIM)
        elif view == 0:
            # Compute visible window size to keep sel in bounds
            y_lbl_w = 5
            chart_w = max(3, (w - 4) - y_lbl_w - 1)
            n_show = min(len(sessions), chart_w)
            sel_min = len(sessions) - n_show
            sel = max(sel_min, min(len(sessions) - 1, sel))
            _draw_history_view(
                stdscr,
                sessions,
                y0=content_y,
                x0=2,
                max_h=content_h,
                max_w=w - 4,
                metric=history_metric,
                sel=sel,
            )
        else:
            _draw_perop_view(stdscr, sessions, y0=content_y, x0=2, max_h=content_h)

        if view == 0:
            footer = "h/l select   j/k metric   ENTER details   TAB view   ESC/q back"
        else:
            footer = "TAB switch view   ESC / q back"
        _center(stdscr, h - 2, footer, curses.A_DIM)
        _push(stdscr)

        key = stdscr.getch()
        if key in (27, ord("q"), ord("Q"), ord("v"), ord("V")):
            return
        elif key == ord("\t"):
            view = 1 - view
        elif view == 0 and key in (
            ord("j"),
            ord("J"),
            curses.KEY_DOWN,
            ord("k"),
            ord("K"),
            curses.KEY_UP,
        ):
            history_metric = 1 - history_metric
        elif view == 0 and key in (ord("h"), ord("H"), curses.KEY_LEFT):
            sel = max(0, sel - 1)
        elif view == 0 and key in (ord("l"), ord("L"), curses.KEY_RIGHT):
            sel = min(len(sessions) - 1, sel + 1)
        elif view == 0 and key in (ord("\n"), ord("\r"), curses.KEY_ENTER):
            if 0 <= sel < len(sessions):
                _show_session_detail(stdscr, sessions[sel])
