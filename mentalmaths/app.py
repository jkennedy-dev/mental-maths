"""Mental Maths Trainer — terminal arithmetic practice with countdown timer."""

import curses
from dataclasses import dataclass
from typing import List, Optional

from .constants import QuitGame, OPERATIONS, TIME_OPTIONS
from .models import OpConfig
from .storage import _dict_to_cfg, _cfg_to_dict, _load_data, _save_data, _make_session
from .ui.menus import (
    run_multiselect,
    run_op_config,
    run_single_select,
    show_quick_start,
)
from .ui.game import Game
from .ui.results import show_results
from .ui.viz import show_viz


@dataclass
class _SessionState:
    """Carries the configuration chosen in the most recent menu pass."""

    indices: Optional[List[int]] = None
    configs: Optional[List[OpConfig]] = None
    t_idx: int = 0
    guest_mode: bool = False
    voice_mode: bool = False


def main(stdscr) -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    curses.curs_set(0)
    stdscr.keypad(True)

    data = _load_data()
    state = _SessionState()
    skip_menu = False
    first_run = True  # show quick-start once on startup

    try:
        while True:
            if not skip_menu:
                # Quick-start prompt on first entry if previous config exists
                if first_run:
                    first_run = False
                    if data.get("last_config"):
                        lc = data["last_config"]
                        try:
                            saved_configs = [_dict_to_cfg(c) for c in lc["configs"]]
                            saved_t_idx = min(lc.get("t_idx", 0), len(TIME_OPTIONS) - 1)
                            choice = show_quick_start(
                                stdscr,
                                saved_configs,
                                saved_t_idx,
                                data.get("sessions", []),
                            )
                            if choice == "quick":
                                state.configs = saved_configs
                                state.t_idx = saved_t_idx
                                state.guest_mode = lc.get("guest_mode", False)
                                state.voice_mode = lc.get("voice_mode", False)
                                skip_menu = True
                                continue
                        except Exception:
                            pass  # corrupt save — fall through to normal menu

                # Normal menu flow
                result = run_multiselect(
                    stdscr,
                    "MENTAL MATHS TRAINER — Select Operations",
                    OPERATIONS,
                    preselected=state.indices,
                    guest=state.guest_mode,
                    voice=state.voice_mode,
                )
                if result is None:  # v pressed
                    show_viz(stdscr, data.get("sessions", []))
                    continue
                indices, guest_mode, voice_mode = result

                prev = {c.operation: c for c in (state.configs or [])}
                configs: List[OpConfig] = []
                cancelled = False
                for idx in indices:
                    cfg = run_op_config(
                        stdscr, prev.get(OPERATIONS[idx], OpConfig(OPERATIONS[idx]))
                    )
                    if cfg is None:
                        cancelled = True
                        break
                    configs.append(cfg)
                if cancelled:
                    continue

                t_idx = run_single_select(
                    stdscr,
                    "Select Time Limit",
                    [label for label, _ in TIME_OPTIONS] + ["Back"],
                    initial=state.t_idx,
                )
                if t_idx < 0 or t_idx == len(TIME_OPTIONS):
                    continue

                state.indices = indices
                state.configs = configs
                state.t_idx = t_idx
                state.guest_mode = guest_mode
                state.voice_mode = voice_mode

            # Play
            questions = Game(
                stdscr,
                state.configs,
                TIME_OPTIONS[state.t_idx][1],
                voice_mode=state.voice_mode,
                guest_mode=state.guest_mode,
            ).run()

            # Persist (skipped in guest mode)
            save_error = False
            if not state.guest_mode:
                session = _make_session(
                    questions, state.configs, TIME_OPTIONS[state.t_idx][1]
                )
                if session:
                    data.setdefault("sessions", []).append(session)
                    data["last_config"] = {
                        "t_idx": state.t_idx,
                        "configs": [_cfg_to_dict(c) for c in state.configs],
                        "guest_mode": state.guest_mode,
                        "voice_mode": state.voice_mode,
                    }
                    try:
                        _save_data(data)
                    except OSError:
                        save_error = True

            result = show_results(
                stdscr,
                questions,
                data.get("sessions", []),
                guest_mode=state.guest_mode,
                save_error=save_error,
            )
            if result == "quit":
                break
            skip_menu = result == "again"

    except QuitGame:
        pass
