import curses
from typing import List, NamedTuple, Optional, Tuple

from ..constants import QuitGame, TIME_OPTIONS
from ..models import OpConfig
from ..voice import _VOICE_AVAILABLE
from .helpers import _push, _center, _box
from .viz import show_viz


# ─── Menu: single select ───────────────────────────────────────────────────────


def run_single_select(stdscr, title: str, options: List[str], initial: int = 0) -> int:
    """Returns selected index, -1 on ESC. Raises QuitGame on q."""
    cursor = initial
    stdscr.nodelay(False)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _box(stdscr)
        _center(stdscr, 2, title, curses.A_BOLD | curses.color_pair(2))
        for i, opt in enumerate(options):
            label = f"  {'>' if i == cursor else ' '}  {opt}  "
            _center(
                stdscr,
                4 + i,
                label,
                curses.A_REVERSE | curses.A_BOLD if i == cursor else 0,
            )
        _center(
            stdscr,
            h - 2,
            "j/k navigate   ENTER select   ESC back   q quit",
            curses.A_DIM,
        )
        _push(stdscr)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(options)
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(options)
        elif key in (10, 13, curses.KEY_ENTER):
            return cursor
        elif key == 27:
            return -1
        elif key in (ord("q"), ord("Q")):
            raise QuitGame


# ─── Menu: multi-select ────────────────────────────────────────────────────────


def run_multiselect(
    stdscr,
    title: str,
    options: List[str],
    preselected: Optional[List[int]] = None,
    guest: bool = False,
    voice: bool = False,
) -> Optional[Tuple[List[int], bool, bool]]:
    """SPACE toggles, ENTER confirms, g toggles guest mode, s toggles voice mode.
    Returns (sorted indices, guest_mode, voice_mode), None on v (viz). Raises QuitGame on q."""
    cursor = 0
    selected: set = set(preselected or [])
    stdscr.nodelay(False)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _box(stdscr)
        _center(stdscr, 1, title, curses.A_BOLD | curses.color_pair(2))
        _center(
            stdscr,
            2,
            "j/k navigate   SPACE toggle   ENTER confirm   g guest   s voice   v performance   q quit",
            curses.A_DIM,
        )
        max_opt = max(len(o) for o in options)
        for i, opt in enumerate(options):
            mark = "[X]" if i in selected else "[ ]"
            label = f"  {mark}  {opt:<{max_opt}}  "
            _center(
                stdscr,
                4 + i,
                label,
                curses.A_REVERSE | curses.A_BOLD if i == cursor else 0,
            )
        confirm_attr = (
            (curses.A_BOLD | curses.color_pair(1)) if selected else curses.A_DIM
        )
        _center(stdscr, 4 + len(options) + 1, "[ Confirm ]", confirm_attr)
        guest_label = "[ Guest Mode: ON  ]" if guest else "[ Guest Mode: OFF ]"
        guest_attr = curses.color_pair(4) | curses.A_BOLD if guest else curses.A_DIM
        _center(stdscr, 4 + len(options) + 2, guest_label, guest_attr)
        if _VOICE_AVAILABLE:
            voice_label = "[ Voice Mode: ON  ]" if voice else "[ Voice Mode: OFF ]"
            voice_attr = curses.color_pair(2) | curses.A_BOLD if voice else curses.A_DIM
        else:
            voice_label = "[ Voice Mode: N/A ]"
            voice_attr = curses.A_DIM
        _center(stdscr, 4 + len(options) + 3, voice_label, voice_attr)
        _push(stdscr)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(options)
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(options)
        elif key == ord(" "):
            selected ^= {cursor}
        elif key in (10, 13, curses.KEY_ENTER):
            if selected:
                return (sorted(selected), guest, voice)
        elif key in (ord("g"), ord("G")):
            guest = not guest
        elif key in (ord("s"), ord("S")):
            if _VOICE_AVAILABLE:
                voice = not voice
        elif key in (ord("v"), ord("V")):
            return None  # caller shows viz then comes back
        elif key in (ord("q"), ord("Q")):
            raise QuitGame


# ─── Menu: per-operation config ────────────────────────────────────────────────

class Row(NamedTuple):
    label: str
    value: int
    min_val: int
    max_val: int
    key: str


def _build_rows(
    op: str, digits: int, decimals: int, op2_lo: int, op2_hi: int, allow_neg: int = 0
) -> List[Row]:
    rows: List[Row] = []
    if op in ("Addition", "Subtraction"):
        rows.append(Row("Integer digits", digits, 1, 4, "digits"))
    if op == "Multiplication":
        rows += [
            Row("Multiplier min", op2_lo, 1, op2_hi, "op2_lo"),
            Row("Multiplier max", op2_hi, op2_lo, 99, "op2_hi"),
        ]
    elif op == "Division":
        rows += [
            Row("Divisor min", op2_lo, 2, op2_hi, "op2_lo"),
            Row("Divisor max", op2_hi, op2_lo, 99, "op2_hi"),
        ]
    rows.append(Row("Decimal places", decimals, 0, 3, "decimals"))
    if op == "Subtraction":
        rows.append(Row("Allow negatives", allow_neg, 0, 1, "allow_neg"))
    return rows


def run_op_config(stdscr, cfg: OpConfig) -> Optional[OpConfig]:
    """Returns configured OpConfig, None on ESC. Raises QuitGame on q."""
    op, digits, decimals, op2_lo, op2_hi, allow_neg = (
        cfg.operation,
        cfg.digits,
        cfg.decimals,
        cfg.operand2_lo,
        cfg.operand2_hi,
        int(cfg.allow_negative),
    )
    field_idx = 0
    stdscr.nodelay(False)
    while True:
        rows = _build_rows(op, digits, decimals, op2_lo, op2_hi, allow_neg)
        n = len(rows)
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _box(stdscr)
        _center(stdscr, 2, f"Configure: {op}", curses.A_BOLD | curses.color_pair(2))
        max_label = max(len(r[0]) for r in rows)
        for i, (label, val, mn, mx, _key) in enumerate(rows):
            left = "<" if val > mn else " "
            right = ">" if val < mx else " "
            val_str = (
                ("No" if val == 0 else "Yes") if _key == "allow_neg" else f"{val:>2}"
            )
            line = f"  {label:<{max_label}}   {left} {val_str} {right}  "
            _center(
                stdscr,
                5 + i * 2,
                line,
                curses.A_REVERSE | curses.A_BOLD if i == field_idx else 0,
            )
        _center(
            stdscr,
            h - 2,
            "j/k switch field   h/l change value   ENTER confirm   ESC cancel   q quit",
            curses.A_DIM,
        )
        _push(stdscr)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            field_idx = (field_idx - 1) % n
        elif key in (curses.KEY_DOWN, ord("j")):
            field_idx = (field_idx + 1) % n
        elif key in (curses.KEY_LEFT, ord("h"), curses.KEY_RIGHT, ord("l")):
            delta = -1 if key in (curses.KEY_LEFT, ord("h")) else 1
            _key = rows[field_idx].key
            if _key == "digits":
                digits = max(1, min(4, digits + delta))
            elif _key == "allow_neg":
                allow_neg = max(0, min(1, allow_neg + delta))
            elif _key == "op2_lo":
                op2_lo = max(rows[field_idx].min_val, min(op2_hi, op2_lo + delta))
            elif _key == "op2_hi":
                op2_hi = max(op2_lo, min(99, op2_hi + delta))
            elif _key == "decimals":
                decimals = max(0, min(3, decimals + delta))
        elif key in (10, 13, curses.KEY_ENTER):
            return OpConfig(op, digits, decimals, op2_lo, op2_hi, bool(allow_neg))
        elif key == 27:
            return None
        elif key in (ord("q"), ord("Q")):
            raise QuitGame


# ─── Quick start ───────────────────────────────────────────────────────────────


def show_quick_start(stdscr, configs: list, t_idx: int, sessions: list) -> str:
    """Returns 'quick' or 'new'. Raises QuitGame on q."""
    time_label = TIME_OPTIONS[t_idx][0]
    ops_label = " | ".join(c.label for c in configs)
    options = ["Quick Start", "New Game"]
    cursor = 0
    stdscr.nodelay(False)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _box(stdscr)
        _center(stdscr, 2, "MENTAL MATHS TRAINER", curses.A_BOLD | curses.color_pair(2))
        _center(stdscr, 4, "Last session:", curses.A_DIM)
        _center(stdscr, 5, ops_label, curses.A_BOLD)
        _center(stdscr, 6, time_label, curses.A_DIM)
        for i, opt in enumerate(options):
            label = f"  {'>' if i == cursor else ' '}  {opt}  "
            _center(
                stdscr,
                9 + i,
                label,
                curses.A_REVERSE | curses.A_BOLD if i == cursor else 0,
            )
        _center(
            stdscr,
            h - 2,
            "j/k navigate   ENTER select   v performance   q quit",
            curses.A_DIM,
        )
        _push(stdscr)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(options)
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(options)
        elif key in (10, 13, curses.KEY_ENTER):
            return "quick" if cursor == 0 else "new"
        elif key in (ord("v"), ord("V")):
            show_viz(stdscr, sessions)
        elif key in (ord("q"), ord("Q")):
            raise QuitGame
