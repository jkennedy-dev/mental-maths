import curses
import random
import threading
import time
from typing import List, Optional

from ..constants import QuitGame
from ..models import Question
from ..questions import generate_question, check_answer
from ..voice import VoiceListener, _combine_spoken_nums
from .helpers import _center, _box, _confirm_quit


class Game:
    def __init__(
        self,
        stdscr,
        configs: list,
        time_limit: int,
        voice_mode: bool = False,
        guest_mode: bool = False,
    ):
        self.stdscr = stdscr
        self.configs = configs
        self.guest_mode = guest_mode
        self.time_limit = time_limit
        self.time_remaining = time_limit
        self.questions: List[Question] = []
        self.current = self._next_question()
        self.buf = ""
        self.voice_partial = ""
        self._running = False
        self._lock = threading.Lock()

        self.voice_listener: Optional[VoiceListener] = None
        self._voice_error: Optional[str] = None
        if voice_mode:
            listener = VoiceListener()
            if listener.start():
                self.voice_listener = listener
            else:
                self._voice_error = listener.error

    def _next_question(self) -> Question:
        return generate_question(random.choice(self.configs))

    def _timer_thread(self) -> None:
        while self._running:
            time.sleep(1)
            with self._lock:
                if self.time_remaining > 0:
                    self.time_remaining -= 1

    def _draw(self) -> None:
        s = self.stdscr
        s.erase()
        h, w = s.getmaxyx()
        _box(s)

        with self._lock:
            remaining = self.time_remaining

        correct = sum(1 for q in self.questions if q.correct)
        total = len(self.questions)

        score_str = f" Score: {correct}/{total} "
        timer_str = f" {remaining // 60:02d}:{remaining % 60:02d} "
        ops_str = " | ".join(c.label for c in self.configs)
        max_ops = w - len(score_str) - len(timer_str) - 4
        if len(ops_str) > max_ops:
            ops_str = ops_str[: max_ops - 1] + "\u2026"

        timer_attr = (
            curses.color_pair(3)
            if remaining <= 10
            else curses.color_pair(4)
            if remaining <= 30
            else curses.color_pair(1)
        ) | curses.A_BOLD
        mic_str = " [MIC] " if self.voice_listener else ""
        guest_str = " [G] " if self.guest_mode else ""
        try:
            s.addstr(1, 1, score_str, curses.A_BOLD)
            offset = 1 + len(score_str)
            if mic_str:
                s.addstr(1, offset, mic_str, curses.color_pair(2) | curses.A_BOLD)
                offset += len(mic_str)
            if guest_str:
                s.addstr(1, offset, guest_str, curses.color_pair(4) | curses.A_BOLD)
            _center(s, 1, ops_str)
            s.addstr(1, w - len(timer_str) - 1, timer_str, timer_attr)
        except curses.error:
            pass

        bar_w = max(4, w - 4)
        filled = round(remaining / self.time_limit * bar_w) if self.time_limit else 0
        bar_attr = (
            curses.color_pair(3)
            if remaining <= 10
            else curses.color_pair(4)
            if remaining <= 30
            else curses.color_pair(1)
        )
        try:
            s.addstr(2, 2, "#" * filled + "-" * (bar_w - filled), bar_attr)
        except curses.error:
            pass

        # Question line: draw question and buffer separately so partial voice
        # input can be shown in a different colour.
        q_prefix = f"{self.current.display}  =  "
        if self.buf and self.voice_partial:
            combined = _combine_spoken_nums(self.buf, self.voice_partial)
            if combined != self.voice_partial:
                # Partial extends the confirmed buffer (e.g. "40" + "2" → "42").
                # Show the combined preview in yellow to indicate it's in-progress.
                buf_disp = combined
                buf_attr = curses.color_pair(4)
            else:
                # Partial would replace the buffer (e.g. "45" + "5" → "5").
                # This is almost always spurious trailing audio — keep the
                # confirmed value visible so the display doesn't flicker down.
                buf_disp = self.buf
                buf_attr = curses.A_BOLD | curses.color_pair(2)
        elif self.buf:
            buf_disp = self.buf
            buf_attr = curses.A_BOLD | curses.color_pair(2)
        elif self.voice_partial:
            buf_disp = self.voice_partial
            buf_attr = curses.color_pair(4)  # yellow — tentative
        else:
            buf_disp = ""
            buf_attr = curses.A_BOLD | curses.color_pair(2)
        full_line = q_prefix + buf_disp + "_"
        q_x = max(0, (w - len(full_line)) // 2)
        try:
            s.addstr(h // 2 - 1, q_x, q_prefix, curses.A_BOLD | curses.color_pair(2))
            s.addstr(h // 2 - 1, q_x + len(q_prefix), buf_disp + "_", buf_attr)
        except curses.error:
            pass

        if self.current.answer_dec > 0:
            dp = self.current.answer_dec
            _center(
                s,
                h // 2 + 1,
                f"(answer to {dp} decimal place{'s' if dp > 1 else ''})",
                curses.A_DIM,
            )

        # Feedback line: voice error takes priority over last-answer feedback.
        if self._voice_error and not self.voice_listener:
            _center(
                s,
                h // 2 + 3,
                f"  Voice unavailable: {self._voice_error[:60]}  ",
                curses.color_pair(4),
            )
        elif self.questions:
            last = self.questions[-1]
            if last.correct:
                fb, attr = (
                    f"  Correct!   {last.display} = {last.answer_str}  ",
                    curses.color_pair(1),
                )
            else:
                fb, attr = (
                    (
                        f"  Wrong   {last.display} = {last.answer_str}"
                        f"   (you: {last.user_answer})  "
                    ),
                    curses.color_pair(3),
                )
            _center(s, h // 2 + 3, fb, attr)

        if self.voice_listener:
            help_text = "Speak answer + 'enter' to submit   'no' to clear   q to quit"
        else:
            help_text = "Type answer and ENTER   BACKSPACE to correct   q to quit"
        _center(s, h - 2, help_text, curses.A_DIM)
        s.noutrefresh()
        curses.doupdate()

    def _handle_backspace(self) -> None:
        """Clear input in response to a backspace keypress.

        In keyboard mode: remove the last character from buf (standard behaviour).
        In voice mode: clear both buf and voice_partial entirely, since buf is
        populated by whole-word recognition rather than keystroke-by-keystroke
        and character removal has no meaningful semantic in that context.
        """
        self.voice_partial = ""
        if self.voice_listener:
            self.buf = ""
        else:
            self.buf = self.buf[:-1]

    def _process_voice_events(self) -> bool:
        """Drain pending voice events and update buf / voice_partial accordingly.

        Returns True if at least one event was processed (used by the game loop
        to decide whether to sleep or poll again immediately).

        Also detects a crashed recognition thread: if listener.error is set the
        listener is retired and the error is surfaced via _voice_error so the UI
        can display it.
        """
        if not self.voice_listener:
            return False
        if self.voice_listener.error is not None:
            self._voice_error = self.voice_listener.error
            self.voice_listener = None
            return False
        had_events = False
        while True:
            event = self.voice_listener.get_nowait()
            if event is None:
                break
            had_events = True
            kind, value = event
            if kind == "clear":
                self.buf = ""
                self.voice_partial = ""
            elif kind == "enter":
                # Commit any still-pending partial before submitting so that
                # "forty [pause] two [pause] enter" works correctly.
                # Guard: only merge if the combine *extends* the buffer.  If it
                # would replace (combine returns the partial itself), the partial
                # is a spurious echo of trailing audio — keep the confirmed buf.
                if self.voice_partial:
                    if self.buf:
                        combined = _combine_spoken_nums(self.buf, self.voice_partial)
                        if combined != self.voice_partial:
                            self.buf = combined
                    else:
                        self.buf = self.voice_partial
                    self.voice_partial = ""
                self._submit()
            elif kind == "final":
                # Combine with existing buffer so slow speech ("forty" … "two")
                # accumulates correctly rather than overwriting.
                # If buf is empty but voice_partial has a value, vosk may have
                # dropped the first word of a phrase from its final result (e.g.
                # partial "forty five"=45, final "five"=5).  Use the partial as
                # the base so the full phrase can be recovered.
                if self.buf:
                    self.buf = _combine_spoken_nums(self.buf, value)
                elif self.voice_partial:
                    combined = _combine_spoken_nums(self.voice_partial, value)
                    if combined == value:
                        # Combine replaced (did not add to) the partial.  If the
                        # final is numerically smaller than the partial the final
                        # is almost certainly a truncation — prefer the partial.
                        try:
                            self.buf = (
                                self.voice_partial
                                if int(value) < int(self.voice_partial)
                                else value
                            )
                        except ValueError:
                            self.buf = value  # decimal/negative — trust the final
                    else:
                        self.buf = combined
                else:
                    self.buf = value
                self.voice_partial = ""
            elif kind == "partial":
                self.voice_partial = value
        return had_events

    def run(self) -> List[Question]:
        self.stdscr.nodelay(True)
        self.stdscr.keypad(True)
        curses.curs_set(0)
        self._running = True
        threading.Thread(target=self._timer_thread, daemon=True).start()
        try:
            while True:
                with self._lock:
                    remaining = self.time_remaining
                if remaining <= 0:
                    break
                had_voice = self._process_voice_events()
                self._draw()
                key = self.stdscr.getch()
                if key == -1:
                    # When voice is active use a short poll interval so a
                    # 'final' number and the following 'enter' event are picked
                    # up in rapid succession without visible flicker.
                    time.sleep(0.01 if (self.voice_listener or had_voice) else 0.05)
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    self._handle_backspace()
                elif key in (10, 13, curses.KEY_ENTER) and not self.voice_listener:
                    self.voice_partial = ""
                    self._submit()
                elif key in (27, ord("q"), ord("Q")):
                    self._draw()
                    if _confirm_quit(self.stdscr):
                        raise QuitGame
                    self.stdscr.nodelay(True)
                elif key < 256 and chr(key).isdigit():
                    self.voice_partial = ""
                    self.buf += chr(key)
                elif key < 256 and chr(key) == "." and "." not in self.buf:
                    self.voice_partial = ""
                    self.buf += "."
                elif key < 256 and chr(key) == "-" and not self.buf:
                    self.voice_partial = ""
                    self.buf = "-"
        finally:
            self._running = False
            if self.voice_listener:
                self.voice_listener.stop()
        return self.questions

    def _submit(self) -> None:
        if not self.buf or self.buf in ("-", ".", "-."):
            return
        self.current.user_answer = self.buf
        self.current.correct = check_answer(self.buf, self.current)
        self.questions.append(self.current)
        self.buf = ""
        self.current = self._next_question()
