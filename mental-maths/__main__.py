#!/usr/bin/env python3
"""Mental Maths Trainer — terminal arithmetic practice with countdown timer."""

import array
import contextlib
import curses
import json
import math
import os
import queue
import random
import time
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

try:
    import vosk as _vosk
    import pyaudio as _pyaudio
    _VOICE_AVAILABLE = True
except ImportError:
    _vosk = None          # type: ignore[assignment]
    _pyaudio = None       # type: ignore[assignment]
    _VOICE_AVAILABLE = False

DATA_FILE       = Path.home() / '.mental-maths.json'
VOICE_MODEL_DIR = Path.home() / '.local' / 'share' / 'mental-maths' / 'vosk-model'
OPERATIONS      = ['Addition', 'Subtraction', 'Multiplication', 'Division']
TIME_OPTIONS    = [('30 seconds', 30), ('1 minute', 60), ('2 minutes', 120),
                   ('5 minutes', 300), ('10 minutes', 600)]


class QuitGame(Exception):
    """Raised from any screen to exit the program."""


# ─── Data model ────────────────────────────────────────────────────────────────

@dataclass
class OpConfig:
    operation: str
    digits: int = 2
    decimals: int = 0
    operand2_lo: int = 2
    operand2_hi: int = 12
    allow_negative: bool = False   # Subtraction only

    @property
    def label(self) -> str:
        if self.operation in ('Multiplication', 'Division'):
            parts = [f"{self.operand2_lo}-{self.operand2_hi}"]
        else:
            parts = [f"{self.digits}-digit"]
        if self.decimals:
            parts.append(f"{self.decimals}dp")
        if self.operation == 'Subtraction' and self.allow_negative:
            parts.append('neg')
        return f"{self.operation} ({', '.join(parts)})"


@dataclass
class Question:
    display: str
    answer: float
    answer_dec: int
    op_label: str = ''
    user_answer: str = ''
    correct: Optional[bool] = None

    @property
    def answer_str(self) -> str:
        if self.answer_dec == 0:
            return str(int(round(self.answer)))
        return f"{self.answer:.{self.answer_dec}f}"


# ─── Question generation ───────────────────────────────────────────────────────

def _rnd(lo: int, hi: int, dec: int) -> float:
    if dec == 0:
        return float(random.randint(lo, hi))
    f = 10 ** dec
    return round(random.randint(lo * f, (hi + 1) * f - 1) / f, dec)


def _fmt(x: float, dec: int) -> str:
    return str(int(round(x))) if dec == 0 else f"{x:.{dec}f}"


def generate_question(cfg: OpConfig) -> Question:
    op, d, dec = cfg.operation, cfg.digits, cfg.decimals
    lo = 10 ** (d - 1) if d > 1 else 1
    hi = 10 ** d - 1

    if op == 'Addition':
        a, b = _rnd(lo, hi, dec), _rnd(lo, hi, dec)
        return Question(f"{_fmt(a,dec)} + {_fmt(b,dec)}", round(a + b, dec), dec, cfg.label)

    if op == 'Subtraction':
        a, b = _rnd(lo, hi, dec), _rnd(lo, hi, dec)
        if not cfg.allow_negative and b > a:
            a, b = b, a
        return Question(f"{_fmt(a,dec)} - {_fmt(b,dec)}", round(a - b, dec), dec, cfg.label)

    if op == 'Multiplication':
        a = _rnd(cfg.operand2_lo, cfg.operand2_hi, dec)
        b = _rnd(cfg.operand2_lo, cfg.operand2_hi, dec)
        return Question(f"{_fmt(a,dec)} x {_fmt(b,dec)}", round(a * b, dec), dec, cfg.label)

    # Division
    divisor = random.randint(cfg.operand2_lo, cfg.operand2_hi)
    if dec == 0:
        quotient = random.randint(cfg.operand2_lo, cfg.operand2_hi)
        return Question(f"{divisor * quotient} / {divisor}", float(quotient), 0, cfg.label)
    a = _rnd(cfg.operand2_lo, cfg.operand2_hi, dec)
    return Question(f"{_fmt(a,dec)} / {divisor}", round(a / divisor, dec), dec, cfg.label)


def check_answer(user_str: str, q: Question) -> bool:
    try:
        if q.answer_dec == 0:
            return int(round(float(user_str))) == int(round(q.answer))
        return round(float(user_str), q.answer_dec) == round(q.answer, q.answer_dec)
    except (ValueError, TypeError):
        return False


# ─── Voice recognition ─────────────────────────────────────────────────────────

_WORD_TO_NUM: dict = {
    'zero': 0, 'oh': 0, 'nought': 0,
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
    'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14,
    'fifteen': 15, 'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19,
    'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
    'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90,
    'hundred': 100, 'thousand': 1000,
}

_SINGLE_DIGIT_WORDS: dict = {
    'zero': '0', 'oh': '0', 'nought': '0',
    'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
    'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
}

_SUBMIT_WORDS: frozenset = frozenset({'enter', 'submit', 'confirm', 'done'})


def _words_to_int(words: list) -> Optional[int]:
    """Convert a list of number words to a non-negative integer, or None if unrecognised."""
    if not words:
        return None
    if len(words) == 1:
        if words[0].isdigit():
            return int(words[0])
        return _WORD_TO_NUM.get(words[0])

    total = 0
    chunk = 0
    for word in words:
        if word == 'and':
            continue
        if word not in _WORD_TO_NUM:
            return None
        val = _WORD_TO_NUM[word]
        if val == 1000:
            total += (chunk if chunk else 1) * 1000
            chunk = 0
        elif val == 100:
            chunk = (chunk if chunk else 1) * 100
        else:
            chunk += val
    return total + chunk


def _combine_spoken_nums(existing: str, incoming: str) -> str:
    """Merge two sequentially voiced number strings.

    When a speaker pauses mid-number vosk produces separate final results
    (e.g. "forty" then "two").  This function recombines them:

    - Round multiple + smaller value → arithmetic sum
        ('40', '2') → '42'   ('100', '42') → '142'   ('140', '2') → '142'
    - Anything else → digit-by-digit concatenation
        ('4', '2') → '42'    ('1', '3') → '13'
    - If either value is non-integer (decimal/negative) the incoming value
      replaces the existing one entirely.
    """
    try:
        a = int(existing)
        b = int(incoming)
    except ValueError:
        return incoming   # decimal — treat as a fresh answer
    if a < 0 or b < 0:
        return incoming   # negative — treat as a fresh answer
    if a > b > 0:
        # 'a' is a round multiple of the next power of 10 above 'b',
        # so 'b' fills in the lower digits (e.g. 40 + 2, 100 + 42).
        power = 10 ** len(str(b))
        if a % power == 0:
            return str(a + b)
    return incoming   # not a continuation — replace with the new number


def _amplify_audio(data: bytes, gain: int) -> bytes:
    """Scale 16-bit little-endian PCM samples by gain, clamping to ±32767."""
    buf = array.array('h', data)
    for i in range(len(buf)):
        v = buf[i] * gain
        buf[i] = 32767 if v > 32767 else (-32768 if v < -32768 else v)
    return buf.tobytes()


def _parse_spoken_number(text: str) -> Optional[str]:
    """Parse spoken text to a digit string suitable for the answer buffer.

    Returns 'ENTER' for submit commands, a numeric string for numbers, or None
    if the text cannot be interpreted as either.
    """
    text  = text.strip().lower()
    words = text.split()
    if not words:
        return None

    # Submit commands
    if words[0] in ('enter', 'submit', 'confirm', 'done'):
        return 'ENTER'

    # Vosk may transcribe digits directly (e.g. "42", "-5", "3.5")
    stripped = text.lstrip('-')
    if stripped.replace('.', '', 1).isdigit() and stripped.count('.') <= 1:
        return text

    # Optional negative prefix
    negative = False
    if words[0] in ('minus', 'negative'):
        negative = True
        words = words[1:]
    if not words:
        return None

    # Split on "point" for decimal portion
    try:
        pt_idx    = words.index('point')
        int_words = words[:pt_idx]
        dec_words = words[pt_idx + 1:]
    except ValueError:
        int_words = words
        dec_words = []

    if not int_words:
        return None

    int_val = _words_to_int(int_words)
    if int_val is None:
        return None

    result = ('-' if negative else '') + str(int_val)

    if dec_words:
        dec_str = ''
        for w in dec_words:
            if w in _SINGLE_DIGIT_WORDS:
                dec_str += _SINGLE_DIGIT_WORDS[w]
            elif w.isdigit() and len(w) == 1:
                dec_str += w
            else:
                break   # ignore unrecognised trailing words
        if dec_str:
            result += '.' + dec_str

    return result


@contextlib.contextmanager
def _silence_stderr():
    """Redirect the OS-level stderr (fd 2) to /dev/null for the duration.

    This suppresses C-library chatter (ALSA probing errors, JACK connection
    failures, vosk LOG lines) that would otherwise corrupt the curses display.
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved   = os.dup(2)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)


class VoiceListener:
    """Local speech recognition using vosk (runs entirely offline).

    Events placed on the queue are 2-tuples:
        ('partial', '<digits>')  — in-progress recognition, may change
        ('final',   '<digits>')  — committed recognition result
        ('enter',   '')          — user said a submit command
    """

    SAMPLE_RATE = 16000
    CHUNK_SIZE  = 800    # 50 ms per processing cycle
    INPUT_GAIN  = 4      # amplify PCM before recognition (helps with distance)

    # Restrict recognition to only the words the number parser uses.
    # This dramatically improves accuracy and speed compared to open vocabulary.
    _VOCAB = json.dumps([
        'zero', 'oh', 'nought', 'one', 'two', 'three', 'four', 'five',
        'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
        'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen',
        'eighteen', 'nineteen', 'twenty', 'thirty', 'forty', 'fifty',
        'sixty', 'seventy', 'eighty', 'ninety', 'hundred', 'thousand',
        'point', 'minus', 'negative', 'and',
        'enter', 'submit', 'confirm', 'done',
        '[unk]',
    ])

    def __init__(self, model_dir: Path = VOICE_MODEL_DIR):
        self._model_dir = model_dir
        self._events: queue.Queue = queue.Queue()
        self._stop    = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.error: Optional[str] = None

    def start(self) -> bool:
        """Start the background recognition thread.  Returns True on success."""
        if not _VOICE_AVAILABLE:
            self.error = ('vosk and pyaudio must be installed for voice mode — '
                          'run: pip install vosk pyaudio')
            return False
        if not self._model_dir.exists():
            self.error = (f'Voice model not found: {self._model_dir}\n'
                          f'Download a model from https://alphacephei.com/vosk/models '
                          f'and unpack it to that path.')
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def get_nowait(self) -> Optional[tuple]:
        """Return the next pending (kind, value) event, or None if the queue is empty."""
        try:
            return self._events.get_nowait()
        except queue.Empty:
            return None

    def _emit_text(self, text: str, final: bool) -> None:
        """Parse a vosk transcript and place the appropriate events on the queue.

        Handles combined utterances such as "forty two enter" by stripping a
        trailing submit word and emitting both a number event and an enter event.
        This lets the player say the number and "enter" in one breath without
        the second word being lost.
        """
        words     = text.split()
        has_sub   = bool(words) and words[-1] in _SUBMIT_WORDS
        num_words = words[:-1] if has_sub else words
        num_text  = ' '.join(num_words)

        if num_text:
            val = _parse_spoken_number(num_text)
            if val == 'ENTER':
                # A submit word appeared somewhere other than the end
                # (e.g. vosk returned "enter forty") — treat as enter only,
                # and only on a final result to avoid duplicates.
                if final:
                    self._events.put(('enter', ''))
                return
            if val is not None:
                kind = 'final' if final else 'partial'
                self._events.put((kind, val))

        # Only emit enter on a final result.  Partials are unstable mid-stream
        # guesses; acting on them causes the same utterance to fire multiple
        # enter events as vosk refines its hypothesis.
        if has_sub and final:
            self._events.put(('enter', ''))

    def _loop(self) -> None:
        try:
            # Suppress C-library noise (ALSA/JACK errors, vosk LOG lines) so
            # they don't bleed into the curses display.
            with _silence_stderr():
                _vosk.SetLogLevel(-1)
                model = _vosk.Model(str(self._model_dir))
                # Restricted vocab + no word-level timing = faster inference.
                rec   = _vosk.KaldiRecognizer(model, self.SAMPLE_RATE, self._VOCAB)
                pa    = _pyaudio.PyAudio()
            stream = pa.open(
                format=_pyaudio.paInt16, channels=1,
                rate=self.SAMPLE_RATE, input=True,
                frames_per_buffer=self.CHUNK_SIZE)
            try:
                while not self._stop.is_set():
                    raw  = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                    data = _amplify_audio(raw, self.INPUT_GAIN)
                    if rec.AcceptWaveform(data):
                        text = json.loads(rec.Result()).get('text', '').strip()
                        if text:
                            self._emit_text(text, final=True)
                    else:
                        partial = json.loads(rec.PartialResult()).get('partial', '').strip()
                        if partial:
                            self._emit_text(partial, final=False)
            finally:
                stream.stop_stream()
                stream.close()
                pa.terminate()
        except Exception as exc:
            self.error = str(exc)


# ─── Data persistence ──────────────────────────────────────────────────────────

def _cfg_to_dict(cfg: OpConfig) -> dict:
    return {'operation': cfg.operation, 'digits': cfg.digits, 'decimals': cfg.decimals,
            'operand2_lo': cfg.operand2_lo, 'operand2_hi': cfg.operand2_hi,
            'allow_negative': cfg.allow_negative}


def _dict_to_cfg(d: dict) -> OpConfig:
    return OpConfig(operation=d['operation'], digits=d.get('digits', 2),
                    decimals=d.get('decimals', 0), operand2_lo=d.get('operand2_lo', 2),
                    operand2_hi=d.get('operand2_hi', 12),
                    allow_negative=d.get('allow_negative', False))


def _load_data() -> dict:
    try:
        return json.loads(DATA_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_data(data: dict) -> None:
    try:
        DATA_FILE.write_text(json.dumps(data, indent=2))
    except OSError:
        pass


def _make_session(questions: list, configs: list, t_idx: int) -> Optional[dict]:
    if not questions:
        return None
    per_op: dict = {}
    for q in questions:
        st = per_op.setdefault(q.op_label, {'total': 0, 'correct': 0})
        st['total'] += 1
        if q.correct:
            st['correct'] += 1
    return {
        'ts': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'time_limit': TIME_OPTIONS[t_idx][1],
        'total': len(questions),
        'correct': sum(1 for q in questions if q.correct),
        'per_op': per_op,
        'configs': [_cfg_to_dict(c) for c in configs],
    }


# ─── Drawing helpers ───────────────────────────────────────────────────────────

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
    bw  = len(msg) + 4
    bx  = max(0, (w - bw) // 2)
    by  = h // 2 - 1
    for dy in range(3):
        try:
            stdscr.addstr(by + dy, bx, ' ' * bw, curses.A_REVERSE)
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
        if key in (ord('y'), ord('Y')):
            return True
        if key in (ord('n'), ord('N'), 27):
            return False


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
            _center(stdscr, 4 + i, label,
                    curses.A_REVERSE | curses.A_BOLD if i == cursor else 0)
        _center(stdscr, h - 2, "j/k navigate   ENTER select   ESC back   q quit",
                curses.A_DIM)
        _push(stdscr)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord('k')):
            cursor = (cursor - 1) % len(options)
        elif key in (curses.KEY_DOWN, ord('j')):
            cursor = (cursor + 1) % len(options)
        elif key in (10, 13, curses.KEY_ENTER):
            return cursor
        elif key == 27:
            return -1
        elif key in (ord('q'), ord('Q')):
            raise QuitGame


# ─── Menu: multi-select ────────────────────────────────────────────────────────

def run_multiselect(stdscr, title: str, options: List[str],
                    preselected: Optional[List[int]] = None,
                    guest: bool = False,
                    voice: bool = False) -> Optional[Tuple[List[int], bool, bool]]:
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
        _center(stdscr, 2,
                "j/k navigate   SPACE toggle   ENTER confirm   g guest   s voice   v performance   q quit",
                curses.A_DIM)
        max_opt = max(len(o) for o in options)
        for i, opt in enumerate(options):
            mark = '[X]' if i in selected else '[ ]'
            label = f"  {mark}  {opt:<{max_opt}}  "
            _center(stdscr, 4 + i, label,
                    curses.A_REVERSE | curses.A_BOLD if i == cursor else 0)
        confirm_attr = (curses.A_BOLD | curses.color_pair(1)) if selected else curses.A_DIM
        _center(stdscr, 4 + len(options) + 1, "[ Confirm ]", confirm_attr)
        guest_label = "[ Guest Mode: ON  ]" if guest else "[ Guest Mode: OFF ]"
        guest_attr  = curses.color_pair(4) | curses.A_BOLD if guest else curses.A_DIM
        _center(stdscr, 4 + len(options) + 2, guest_label, guest_attr)
        if _VOICE_AVAILABLE:
            voice_label = "[ Voice Mode: ON  ]" if voice else "[ Voice Mode: OFF ]"
            voice_attr  = curses.color_pair(2) | curses.A_BOLD if voice else curses.A_DIM
        else:
            voice_label = "[ Voice Mode: N/A ]"
            voice_attr  = curses.A_DIM
        _center(stdscr, 4 + len(options) + 3, voice_label, voice_attr)
        _push(stdscr)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord('k')):
            cursor = (cursor - 1) % len(options)
        elif key in (curses.KEY_DOWN, ord('j')):
            cursor = (cursor + 1) % len(options)
        elif key == ord(' '):
            selected ^= {cursor}
        elif key in (10, 13, curses.KEY_ENTER):
            if selected:
                return (sorted(selected), guest, voice)
        elif key in (ord('g'), ord('G')):
            guest = not guest
        elif key in (ord('s'), ord('S')):
            if _VOICE_AVAILABLE:
                voice = not voice
        elif key in (ord('v'), ord('V')):
            return None   # caller shows viz then comes back
        elif key in (ord('q'), ord('Q')):
            raise QuitGame


# ─── Menu: per-operation config ────────────────────────────────────────────────

Row = Tuple[str, int, int, int, str]


def _build_rows(op: str, digits: int, decimals: int, op2_lo: int, op2_hi: int,
                allow_neg: int = 0) -> List[Row]:
    rows: List[Row] = []
    if op in ('Addition', 'Subtraction'):
        rows.append(('Integer digits', digits, 1, 4, 'digits'))
    if op == 'Multiplication':
        rows += [('Multiplier min', op2_lo, 1,      op2_hi, 'op2_lo'),
                 ('Multiplier max', op2_hi, op2_lo, 99,     'op2_hi')]
    elif op == 'Division':
        rows += [('Divisor min', op2_lo, 2,      op2_hi, 'op2_lo'),
                 ('Divisor max', op2_hi, op2_lo, 99,     'op2_hi')]
    rows.append(('Decimal places', decimals, 0, 3, 'decimals'))
    if op == 'Subtraction':
        rows.append(('Allow negatives', allow_neg, 0, 1, 'allow_neg'))
    return rows


def run_op_config(stdscr, cfg: OpConfig) -> Optional[OpConfig]:
    """Returns configured OpConfig, None on ESC. Raises QuitGame on q."""
    op, digits, decimals, op2_lo, op2_hi, allow_neg = (
        cfg.operation, cfg.digits, cfg.decimals,
        cfg.operand2_lo, cfg.operand2_hi, int(cfg.allow_negative))
    field_idx = 0
    stdscr.nodelay(False)
    while True:
        rows = _build_rows(op, digits, decimals, op2_lo, op2_hi, allow_neg)
        n    = len(rows)
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _box(stdscr)
        _center(stdscr, 2, f"Configure: {op}", curses.A_BOLD | curses.color_pair(2))
        max_label = max(len(r[0]) for r in rows)
        for i, (label, val, mn, mx, _key) in enumerate(rows):
            left    = '<' if val > mn else ' '
            right   = '>' if val < mx else ' '
            val_str = ('No' if val == 0 else 'Yes') if _key == 'allow_neg' else f"{val:>2}"
            line    = f"  {label:<{max_label}}   {left} {val_str} {right}  "
            _center(stdscr, 5 + i * 2, line,
                    curses.A_REVERSE | curses.A_BOLD if i == field_idx else 0)
        _center(stdscr, h - 2,
                "j/k switch field   h/l change value   ENTER confirm   ESC cancel   q quit",
                curses.A_DIM)
        _push(stdscr)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord('k')):
            field_idx = (field_idx - 1) % n
        elif key in (curses.KEY_DOWN, ord('j')):
            field_idx = (field_idx + 1) % n
        elif key in (curses.KEY_LEFT, ord('h'), curses.KEY_RIGHT, ord('l')):
            delta = -1 if key in (curses.KEY_LEFT, ord('h')) else 1
            _key  = rows[field_idx][4]
            if   _key == 'digits':    digits    = max(1,      min(4,      digits    + delta))
            elif _key == 'allow_neg': allow_neg = max(0,      min(1,      allow_neg + delta))
            elif _key == 'op2_lo':    op2_lo    = max(rows[field_idx][2], min(op2_hi, op2_lo + delta))
            elif _key == 'op2_hi':    op2_hi    = max(op2_lo, min(99,     op2_hi    + delta))
            elif _key == 'decimals':  decimals  = max(0,      min(3,      decimals  + delta))
        elif key in (10, 13, curses.KEY_ENTER):
            return OpConfig(op, digits, decimals, op2_lo, op2_hi, bool(allow_neg))
        elif key == 27:
            return None
        elif key in (ord('q'), ord('Q')):
            raise QuitGame


# ─── Quick start ───────────────────────────────────────────────────────────────

def show_quick_start(stdscr, configs: list, t_idx: int, sessions: list) -> str:
    """Returns 'quick' or 'new'. Raises QuitGame on q."""
    time_label = TIME_OPTIONS[t_idx][0]
    ops_label  = ' | '.join(c.label for c in configs)
    options    = ['Quick Start', 'New Game']
    cursor     = 0
    stdscr.nodelay(False)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _box(stdscr)
        _center(stdscr, 2, 'MENTAL MATHS TRAINER', curses.A_BOLD | curses.color_pair(2))
        _center(stdscr, 4, 'Last session:', curses.A_DIM)
        _center(stdscr, 5, ops_label, curses.A_BOLD)
        _center(stdscr, 6, time_label, curses.A_DIM)
        for i, opt in enumerate(options):
            label = f"  {'>' if i == cursor else ' '}  {opt}  "
            _center(stdscr, 9 + i, label,
                    curses.A_REVERSE | curses.A_BOLD if i == cursor else 0)
        _center(stdscr, h - 2, "j/k navigate   ENTER select   v performance   q quit",
                curses.A_DIM)
        _push(stdscr)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord('k')):
            cursor = (cursor - 1) % len(options)
        elif key in (curses.KEY_DOWN, ord('j')):
            cursor = (cursor + 1) % len(options)
        elif key in (10, 13, curses.KEY_ENTER):
            return 'quick' if cursor == 0 else 'new'
        elif key in (ord('v'), ord('V')):
            show_viz(stdscr, sessions)
        elif key in (ord('q'), ord('Q')):
            raise QuitGame


# ─── Visualisations ────────────────────────────────────────────────────────────

def _draw_history_view(stdscr, sessions: list, y0: int, x0: int,
                       max_h: int, max_w: int, metric: int = 0,
                       sel: int = -1) -> None:
    """Bar chart.
    metric=0: accuracy % per session (colour-coded green/yellow/red), y-axis 0–100%.
    metric=1: stacked bars per session — green=correct, red=wrong, y-axis 0–max_total.
    sel: absolute index into sessions of the selected bar (-1 = none).
    """
    y_lbl_w = 5
    chart_h = max(4, max_h - 4)
    chart_w = max(3, max_w - y_lbl_w - 1)
    n_show  = min(len(sessions), chart_w)
    data    = sessions[-n_show:]
    ax_x    = x0 + y_lbl_w - 1

    # Convert absolute sel to relative index within data
    offset  = len(sessions) - n_show
    sel_rel = (sel - offset) if (0 <= sel - offset < n_show) else -1

    # Metric label centred above the chart
    labels = ['< Accuracy % >', '< Correct count >']
    lbl    = labels[metric]
    lbl_x  = ax_x + 1 + max(0, (n_show - len(lbl)) // 2)
    try:
        stdscr.addstr(y0, lbl_x, lbl, curses.A_BOLD)
    except curses.error:
        pass
    chart_y = y0 + 1

    # Build x-axis string with cursor marker embedded
    xaxis = [('v' if i == sel_rel else '-') for i in range(n_show)]

    if metric == 0:
        # Accuracy % bars — single colour per session
        for tick in range(5):
            tick_val = tick * 25
            row      = chart_y + round((1 - tick / 4) * (chart_h - 1))
            try:
                stdscr.addstr(row, x0, f"{tick_val:>3}%", curses.A_DIM)
                stdscr.addstr(row, ax_x, '|')
            except curses.error:
                pass
        try:
            stdscr.addstr(chart_y + chart_h, ax_x, '+' + ''.join(xaxis))
        except curses.error:
            pass
        for i, s in enumerate(data):
            pct       = s['correct'] / s['total'] * 100 if s['total'] else 0
            bar_h     = round(pct / 100 * chart_h)
            base_clr  = (curses.color_pair(1) if pct >= 70 else
                         curses.color_pair(4) if pct >= 50 else
                         curses.color_pair(3))
            bold      = curses.A_BOLD if i == sel_rel else 0
            for row in range(chart_h):
                from_bottom = chart_h - 1 - row
                if from_bottom < bar_h:
                    char, attr = '#', base_clr | bold
                elif i == sel_rel:
                    char, attr = '|', curses.A_DIM
                else:
                    char, attr = ' ', 0
                try:
                    stdscr.addstr(chart_y + row, ax_x + 1 + i, char, attr)
                except curses.error:
                    pass
        # Legend
        legend_y = chart_y + chart_h + 1
        try:
            stdscr.addstr(legend_y, x0,      '#', curses.color_pair(1))
            stdscr.addstr(legend_y, x0 + 2,  '>=70%', curses.A_DIM)
            stdscr.addstr(legend_y, x0 + 9,  '#', curses.color_pair(4))
            stdscr.addstr(legend_y, x0 + 11, '>=50%', curses.A_DIM)
            stdscr.addstr(legend_y, x0 + 18, '#', curses.color_pair(3))
            stdscr.addstr(legend_y, x0 + 20, '<50%', curses.A_DIM)
        except curses.error:
            pass

    else:
        # Stacked bars: green = correct, red = wrong; y-axis 0–max_total
        max_total = max((s['total'] for s in data), default=1) or 1
        for tick in range(5):
            tick_val = round(tick / 4 * max_total)
            row      = chart_y + round((1 - tick / 4) * (chart_h - 1))
            try:
                stdscr.addstr(row, x0, f"{tick_val:>3}q", curses.A_DIM)
                stdscr.addstr(row, ax_x, '|')
            except curses.error:
                pass
        try:
            stdscr.addstr(chart_y + chart_h, ax_x, '+' + ''.join(xaxis))
        except curses.error:
            pass
        for i, s in enumerate(data):
            total     = s['total']
            correct   = s['correct']
            bar_h     = round(total   / max_total * chart_h)
            correct_h = round(correct / max_total * chart_h)
            bold      = curses.A_BOLD if i == sel_rel else 0
            for row in range(chart_h):
                from_bottom = chart_h - 1 - row
                if from_bottom < correct_h:
                    char, attr = '#', curses.color_pair(1) | bold
                elif from_bottom < bar_h:
                    char, attr = '#', curses.color_pair(3) | bold
                elif i == sel_rel:
                    char, attr = '|', curses.A_DIM
                else:
                    char, attr = ' ', 0
                try:
                    stdscr.addstr(chart_y + row, ax_x + 1 + i, char, attr)
                except curses.error:
                    pass
        # Legend
        legend_y = chart_y + chart_h + 1
        try:
            stdscr.addstr(legend_y, x0,      '#', curses.color_pair(1))
            stdscr.addstr(legend_y, x0 + 2,  'correct', curses.A_DIM)
            stdscr.addstr(legend_y, x0 + 11, '#', curses.color_pair(3))
            stdscr.addstr(legend_y, x0 + 13, 'wrong', curses.A_DIM)
        except curses.error:
            pass

    # Bottom info line: selected session summary, or aggregate stats
    info_y = chart_y + chart_h + 2
    if sel_rel >= 0 and 0 <= sel < len(sessions):
        s   = sessions[sel]
        pct = s['correct'] / s['total'] * 100 if s['total'] else 0
        info = (f"{s['ts']}  {s['correct']}/{s['total']} ({pct:.0f}%)"
                f"  ENTER for details")
        try:
            stdscr.addstr(info_y, x0, info[:max_w], curses.A_BOLD)
        except curses.error:
            pass
    else:
        all_correct = sum(s['correct'] for s in sessions)
        all_total   = sum(s['total']   for s in sessions)
        all_pcts    = [s['correct'] / s['total'] * 100 for s in sessions if s['total']]
        if all_pcts:
            n    = len(sessions)
            avg  = sum(all_pcts) / len(all_pcts)
            best = max(all_pcts)
            stats = (f"{n} session{'s' if n != 1 else ''}  |  "
                     f"{all_correct} correct / {all_total} total  |  "
                     f"avg {avg:.0f}%  |  best {best:.0f}%")
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
    total   = session.get('total', 0)
    correct = session.get('correct', 0)
    pct     = correct / total * 100 if total else 0
    lines.append(f" Score:   {correct} / {total}  ({pct:.0f}%) ")
    lines.append('')

    configs = session.get('configs', [])
    if configs:
        lines.append(' Operations: ')
        for cfg_d in configs:
            op = cfg_d['operation']
            lines.append(f'   {op}')
            if op in ('Addition', 'Subtraction'):
                lines.append(f"     Digits: {cfg_d.get('digits', 2)}")
            if op == 'Multiplication':
                lines.append(f"     Multiplier range: {cfg_d.get('operand2_lo', 2)}"
                              f"–{cfg_d.get('operand2_hi', 12)}")
            elif op == 'Division':
                lines.append(f"     Divisor range: {cfg_d.get('operand2_lo', 2)}"
                              f"–{cfg_d.get('operand2_hi', 12)}")
            if cfg_d.get('decimals', 0):
                lines.append(f"     Decimal places: {cfg_d['decimals']}")
            if op == 'Subtraction' and cfg_d.get('allow_negative'):
                lines.append('     Allow negatives: yes')
    else:
        per_op = session.get('per_op', {})
        if per_op:
            lines.append(' Operations: ')
            for lbl in per_op:
                lines.append(f'   {lbl}')

    lines.append('')
    lines.append(' Press any key to close ')

    box_w = min(w - 4, max(len(l) for l in lines) + 4)
    box_h = min(h - 4, len(lines) + 2)
    by    = max(1, (h - box_h) // 2)
    bx    = max(1, (w - box_w) // 2)

    for row in range(box_h):
        try:
            stdscr.addstr(by + row, bx, ' ' * box_w, curses.A_REVERSE)
        except curses.error:
            pass
    try:
        stdscr.addstr(by,            bx, ('┌' + '─' * (box_w - 2) + '┐'), curses.A_REVERSE)
        stdscr.addstr(by + box_h - 1, bx, ('└' + '─' * (box_w - 2) + '┘'), curses.A_REVERSE)
    except curses.error:
        pass
    for row in range(1, box_h - 1):
        try:
            stdscr.addstr(by + row, bx,             '│', curses.A_REVERSE)
            stdscr.addstr(by + row, bx + box_w - 1, '│', curses.A_REVERSE)
        except curses.error:
            pass
    for i, line in enumerate(lines[:box_h - 2]):
        padded = line[:box_w - 2].ljust(box_w - 2)
        try:
            stdscr.addstr(by + 1 + i, bx + 1, padded, curses.A_REVERSE)
        except curses.error:
            pass

    _push(stdscr)
    stdscr.getch()


def _draw_perop_view(stdscr, sessions: list, y0: int, x0: int, max_h: int) -> None:
    op_stats: dict = {}
    for s in sessions:
        for label, counts in s.get('per_op', {}).items():
            st = op_stats.setdefault(label, {'total': 0, 'correct': 0, 'sessions': 0, 'pcts': []})
            st['total']    += counts['total']
            st['correct']  += counts['correct']
            st['sessions'] += 1
            if counts['total']:
                st['pcts'].append(counts['correct'] / counts['total'] * 100)

    if not op_stats:
        try:
            stdscr.addstr(y0, x0, "No per-operation data yet.", curses.A_DIM)
        except curses.error:
            pass
        return

    cols   = ['Operation', 'Sessions', 'Total Q', 'Correct', 'Avg %', 'Best %']
    widths = [26,           9,          8,          8,         7,       7]
    header = '  '.join(f"{c:<{w}}" for c, w in zip(cols, widths))
    try:
        stdscr.addstr(y0,     x0, header,           curses.A_BOLD)
        stdscr.addstr(y0 + 1, x0, '-' * len(header), curses.A_DIM)
    except curses.error:
        pass

    for i, (label, st) in enumerate(sorted(op_stats.items())):
        if i >= max_h - 3:
            break
        pct  = st['correct'] / st['total'] * 100 if st['total'] else 0
        best = max(st['pcts']) if st['pcts'] else 0
        color = (curses.color_pair(1) if pct >= 70 else
                 curses.color_pair(4) if pct >= 50 else
                 curses.color_pair(3))
        row_data = [label[:26], str(st['sessions']), str(st['total']),
                    str(st['correct']), f"{pct:.0f}%", f"{best:.0f}%"]
        line = '  '.join(f"{d:<{w}}" for d, w in zip(row_data, widths))
        try:
            stdscr.addstr(y0 + 2 + i, x0, line, color)
        except curses.error:
            pass


def show_viz(stdscr, sessions: list) -> None:
    """Performance charts. TAB switches between History and By Operation views.
    History tab: j/k switch metric; h/l move bar selection; ENTER shows session detail."""
    view           = 0
    history_metric = 0
    # sel: absolute index into sessions (-1 = no selection; start at most recent)
    sel = len(sessions) - 1 if sessions else -1
    stdscr.nodelay(False)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _box(stdscr)
        _center(stdscr, 1, ' PERFORMANCE ', curses.A_BOLD | curses.color_pair(2))

        # Tab bar
        tabs    = ['[ History ]', '[ By Operation ]']
        tab_str = '   '.join(tabs)
        tab_x0  = max(0, (w - len(tab_str)) // 2)
        x_cur   = tab_x0
        for i, t in enumerate(tabs):
            try:
                stdscr.addstr(2, x_cur, t,
                              curses.A_REVERSE | curses.A_BOLD if i == view else curses.A_DIM)
            except curses.error:
                pass
            x_cur += len(t) + 3

        content_y = 4
        content_h = h - content_y - 3

        if not sessions:
            _center(stdscr, h // 2, 'No sessions recorded yet.', curses.A_DIM)
        elif view == 0:
            # Compute visible window size to keep sel in bounds
            y_lbl_w = 5
            chart_w = max(3, (w - 4) - y_lbl_w - 1)
            n_show  = min(len(sessions), chart_w)
            sel_min = len(sessions) - n_show
            sel     = max(sel_min, min(len(sessions) - 1, sel))
            _draw_history_view(stdscr, sessions,
                               y0=content_y, x0=2, max_h=content_h, max_w=w - 4,
                               metric=history_metric, sel=sel)
        else:
            _draw_perop_view(stdscr, sessions,
                             y0=content_y, x0=2, max_h=content_h)

        if view == 0:
            footer = 'h/l select   j/k metric   ENTER details   TAB view   ESC/q back'
        else:
            footer = 'TAB switch view   ESC / q back'
        _center(stdscr, h - 2, footer, curses.A_DIM)
        _push(stdscr)

        key = stdscr.getch()
        if key in (27, ord('q'), ord('Q'), ord('v'), ord('V')):
            return
        elif key == ord('\t'):
            view = 1 - view
        elif view == 0 and key in (ord('j'), ord('J'), curses.KEY_DOWN,
                                   ord('k'), ord('K'), curses.KEY_UP):
            history_metric = 1 - history_metric
        elif view == 0 and key in (ord('h'), ord('H'), curses.KEY_LEFT):
            sel = max(0, sel - 1)
        elif view == 0 and key in (ord('l'), ord('L'), curses.KEY_RIGHT):
            sel = min(len(sessions) - 1, sel + 1)
        elif view == 0 and key in (ord('\n'), ord('\r'), curses.KEY_ENTER):
            if 0 <= sel < len(sessions):
                _show_session_detail(stdscr, sessions[sel])


# ─── Game ──────────────────────────────────────────────────────────────────────

class Game:
    def __init__(self, stdscr, configs: List[OpConfig], time_limit: int,
                 voice_mode: bool = False, guest_mode: bool = False):
        self.stdscr         = stdscr
        self.configs        = configs
        self.guest_mode     = guest_mode
        self.time_limit     = time_limit
        self.time_remaining = time_limit
        self.questions: List[Question] = []
        self.current        = self._next_question()
        self.buf            = ''
        self.voice_partial  = ''
        self._running       = False
        self._lock          = threading.Lock()

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
        total   = len(self.questions)

        score_str = f" Score: {correct}/{total} "
        timer_str = f" {remaining // 60:02d}:{remaining % 60:02d} "
        ops_str   = ' | '.join(c.label for c in self.configs)
        max_ops   = w - len(score_str) - len(timer_str) - 4
        if len(ops_str) > max_ops:
            ops_str = ops_str[:max_ops - 1] + '\u2026'

        timer_attr = (curses.color_pair(3) if remaining <= 10 else
                      curses.color_pair(4) if remaining <= 30 else
                      curses.color_pair(1)) | curses.A_BOLD
        mic_str   = ' [MIC] ' if self.voice_listener else ''
        guest_str = ' [G] ' if self.guest_mode else ''
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

        bar_w    = max(4, w - 4)
        filled   = round(remaining / self.time_limit * bar_w) if self.time_limit else 0
        bar_attr = (curses.color_pair(3) if remaining <= 10 else
                    curses.color_pair(4) if remaining <= 30 else
                    curses.color_pair(1))
        try:
            s.addstr(2, 2, '#' * filled + '-' * (bar_w - filled), bar_attr)
        except curses.error:
            pass

        # Question line: draw question and buffer separately so partial voice
        # input can be shown in a different colour.
        q_prefix = f"{self.current.display}  =  "
        if self.buf and self.voice_partial:
            # Show what the combined answer will be once the partial finalises,
            # so the player can see the live result of slow digit-by-digit speech.
            buf_disp = _combine_spoken_nums(self.buf, self.voice_partial)
            buf_attr = curses.color_pair(4)   # yellow — still in progress
        elif self.buf:
            buf_disp = self.buf
            buf_attr = curses.A_BOLD | curses.color_pair(2)
        elif self.voice_partial:
            buf_disp = self.voice_partial
            buf_attr = curses.color_pair(4)   # yellow — tentative
        else:
            buf_disp = ''
            buf_attr = curses.A_BOLD | curses.color_pair(2)
        full_line = q_prefix + buf_disp + '_'
        q_x = max(0, (w - len(full_line)) // 2)
        try:
            s.addstr(h // 2 - 1, q_x, q_prefix,
                     curses.A_BOLD | curses.color_pair(2))
            s.addstr(h // 2 - 1, q_x + len(q_prefix), buf_disp + '_', buf_attr)
        except curses.error:
            pass

        if self.current.answer_dec > 0:
            dp = self.current.answer_dec
            _center(s, h // 2 + 1,
                    f"(answer to {dp} decimal place{'s' if dp > 1 else ''})",
                    curses.A_DIM)

        # Feedback line: voice error takes priority over last-answer feedback.
        if self._voice_error and not self.voice_listener:
            _center(s, h // 2 + 3,
                    f"  Voice unavailable: {self._voice_error[:60]}  ",
                    curses.color_pair(4))
        elif self.questions:
            last = self.questions[-1]
            if last.correct:
                fb, attr = f"  Correct!   {last.display} = {last.answer_str}  ", curses.color_pair(1)
            else:
                fb, attr = (f"  Wrong   {last.display} = {last.answer_str}"
                            f"   (you: {last.user_answer})  "), curses.color_pair(3)
            _center(s, h // 2 + 3, fb, attr)

        if self.voice_listener:
            help_text = "Speak or type answer   ENTER / say 'enter'   BACKSPACE   q to quit"
        else:
            help_text = "Type answer and ENTER   BACKSPACE to correct   q to quit"
        _center(s, h - 2, help_text, curses.A_DIM)
        s.noutrefresh()
        curses.doupdate()

    def _process_voice_events(self) -> bool:
        """Drain pending voice events and update buf / voice_partial accordingly.

        Returns True if at least one event was processed (used by the game loop
        to decide whether to sleep or poll again immediately).
        """
        if not self.voice_listener:
            return False
        had_events = False
        while True:
            event = self.voice_listener.get_nowait()
            if event is None:
                break
            had_events = True
            kind, value = event
            if kind == 'enter':
                # Commit any still-pending partial before submitting so that
                # "forty [pause] two [pause] enter" works correctly.
                if self.voice_partial:
                    self.buf = (_combine_spoken_nums(self.buf, self.voice_partial)
                                if self.buf else self.voice_partial)
                    self.voice_partial = ''
                self._submit()
            elif kind == 'final':
                # Combine with existing buffer so slow speech ("forty" … "two")
                # accumulates correctly rather than overwriting.
                self.buf = (_combine_spoken_nums(self.buf, value)
                            if self.buf else value)
                self.voice_partial = ''
            elif kind == 'partial':
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
                    self.voice_partial = ''
                    self.buf = self.buf[:-1]
                elif key in (10, 13, curses.KEY_ENTER):
                    self.voice_partial = ''
                    self._submit()
                elif key in (27, ord('q'), ord('Q')):
                    self._draw()
                    if _confirm_quit(self.stdscr):
                        raise QuitGame
                    self.stdscr.nodelay(True)
                elif key < 256 and chr(key).isdigit():
                    self.voice_partial = ''
                    self.buf += chr(key)
                elif key < 256 and chr(key) == '.' and '.' not in self.buf:
                    self.voice_partial = ''
                    self.buf += '.'
                elif key < 256 and chr(key) == '-' and not self.buf:
                    self.voice_partial = ''
                    self.buf = '-'
        finally:
            self._running = False
            if self.voice_listener:
                self.voice_listener.stop()
        return self.questions

    def _submit(self) -> None:
        if not self.buf or self.buf in ('-', '.', '-.'):
            return
        self.current.user_answer = self.buf
        self.current.correct     = check_answer(self.buf, self.current)
        self.questions.append(self.current)
        self.buf     = ''
        self.current = self._next_question()


# ─── Results ───────────────────────────────────────────────────────────────────

def _q_line(q: Question) -> str:
    line = f"[{'+'if q.correct else'-'}]  {q.display} = {q.answer_str}"
    if not q.correct:
        line += f"  (you: {q.user_answer})"
    return line


def show_results(stdscr, questions: List[Question], sessions: list,
                 guest_mode: bool = False) -> str:
    """Returns 'again', 'menu', or 'quit'."""
    curses.curs_set(0)
    stdscr.nodelay(False)
    total      = len(questions)
    row_scroll = 0

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _box(stdscr)

        correct = sum(1 for q in questions if q.correct)
        pct     = correct / total * 100 if total else 0
        _center(stdscr, 1, ' RESULTS ', curses.A_BOLD | curses.color_pair(2))
        _center(stdscr, 3, f"{correct} / {total} correct  ({pct:.0f}%)", curses.A_BOLD)
        if guest_mode:
            _center(stdscr, 4, '(guest mode — results not saved)', curses.color_pair(4))

        list_y = 5
        list_h = h - 8

        if total:
            lines        = [_q_line(q) for q in questions]
            max_lw       = max(len(l) for l in lines)
            col_gap      = 4
            col_w        = max_lw + col_gap
            usable_w     = w - 4
            num_cols     = max(1, usable_w // col_w)
            num_rows     = math.ceil(total / num_cols)
            needs_scroll = num_rows > list_h
            max_scroll   = max(0, num_rows - list_h) if needs_scroll else 0
            row_scroll   = min(row_scroll, max_scroll)

            for vr in range(min(list_h, num_rows - row_scroll)):
                ar = vr + row_scroll
                for col in range(num_cols):
                    q_idx = col * num_rows + ar
                    if q_idx >= total:
                        continue
                    q     = questions[q_idx]
                    color = curses.color_pair(1) if q.correct else curses.color_pair(3)
                    try:
                        stdscr.addstr(list_y + vr, 2 + col * col_w,
                                      lines[q_idx][:max_lw], color)
                    except curses.error:
                        pass

            if needs_scroll and max_scroll > 0:
                bar_h   = max(1, round(list_h / num_rows * list_h))
                bar_top = list_y + round(row_scroll / max_scroll * (list_h - bar_h))
                for dy in range(bar_h):
                    try:
                        stdscr.addstr(bar_top + dy, w - 2, '|')
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
        if key in (ord('q'), ord('Q'), 27):
            return 'quit'
        elif key in (10, 13, curses.KEY_ENTER, ord('r'), ord('R')):
            return 'again'
        elif key in (ord('m'), ord('M')):
            return 'menu'
        elif key in (ord('v'), ord('V')):
            show_viz(stdscr, sessions)
        elif needs_scroll:
            if key in (curses.KEY_UP, ord('k')) and row_scroll > 0:
                row_scroll -= 1
            elif key in (curses.KEY_DOWN, ord('j')) and row_scroll < max_scroll:
                row_scroll += 1


# ─── Main ──────────────────────────────────────────────────────────────────────

def main(stdscr):
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN,  -1)
    curses.init_pair(2, curses.COLOR_CYAN,   -1)
    curses.init_pair(3, curses.COLOR_RED,    -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    curses.curs_set(0)
    stdscr.keypad(True)

    data             = _load_data()
    last_indices     = None
    last_configs     = None
    last_t_idx       = 0
    last_guest_mode  = False
    last_voice_mode  = False
    action           = 'menu'
    first_run        = True   # show quick-start once on startup

    try:
        while True:
            if action == 'menu':
                # Quick-start prompt on first entry if previous config exists
                if first_run and data.get('last_config'):
                    first_run = False
                    lc = data['last_config']
                    try:
                        saved_configs = [_dict_to_cfg(c) for c in lc['configs']]
                        saved_t_idx   = min(lc.get('t_idx', 0), len(TIME_OPTIONS) - 1)
                        choice = show_quick_start(stdscr, saved_configs, saved_t_idx,
                                                  data.get('sessions', []))
                        if choice == 'quick':
                            last_configs    = saved_configs
                            last_t_idx      = saved_t_idx
                            last_guest_mode = False
                            action = 'again'   # skip menus, go straight to game
                            continue
                    except (KeyError, Exception):
                        pass   # corrupt save — fall through to normal menu
                first_run = False

                # Normal menu flow
                result = run_multiselect(
                    stdscr, 'MENTAL MATHS TRAINER — Select Operations',
                    OPERATIONS, preselected=last_indices, guest=last_guest_mode,
                    voice=last_voice_mode)
                if result is None:           # v pressed
                    show_viz(stdscr, data.get('sessions', []))
                    continue
                indices, guest_mode, voice_mode = result

                prev = {c.operation: c for c in (last_configs or [])}
                configs: List[OpConfig] = []
                cancelled = False
                for idx in indices:
                    cfg = run_op_config(
                        stdscr, prev.get(OPERATIONS[idx], OpConfig(OPERATIONS[idx])))
                    if cfg is None:
                        cancelled = True
                        break
                    configs.append(cfg)
                if cancelled:
                    continue

                t_idx = run_single_select(
                    stdscr, 'Select Time Limit',
                    [label for label, _ in TIME_OPTIONS] + ['Back'],
                    initial=last_t_idx)
                if t_idx < 0 or t_idx == len(TIME_OPTIONS):
                    continue

                last_indices    = indices
                last_configs    = configs
                last_t_idx      = t_idx
                last_guest_mode = guest_mode
                last_voice_mode = voice_mode

            # Play
            questions = Game(stdscr, last_configs, TIME_OPTIONS[last_t_idx][1],
                             voice_mode=last_voice_mode,
                             guest_mode=last_guest_mode).run()

            # Persist (skipped in guest mode)
            if not last_guest_mode:
                session = _make_session(questions, last_configs, last_t_idx)
                if session:
                    data.setdefault('sessions', []).append(session)
                    data['last_config'] = {
                        't_idx':   last_t_idx,
                        'configs': [_cfg_to_dict(c) for c in last_configs],
                    }
                    _save_data(data)

            action = show_results(stdscr, questions, data.get('sessions', []),
                                  guest_mode=last_guest_mode)
            if action == 'quit':
                break

    except QuitGame:
        pass


if __name__ == '__main__':
    curses.wrapper(main)
