import array
import contextlib
import json
import os
import queue
import threading
from pathlib import Path
from typing import Optional

from .constants import VOICE_MODEL_DIR

try:
    import vosk as _vosk
    import pyaudio as _pyaudio

    _VOICE_AVAILABLE = True
except ImportError:
    _vosk = None  # type: ignore[assignment]
    _pyaudio = None  # type: ignore[assignment]
    _VOICE_AVAILABLE = False

_WORD_TO_NUM: dict = {
    "zero": 0,
    "oh": 0,
    "nought": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "thousand": 1000,
}


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
        if word == "and":
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
    - Anything else (same magnitude, larger incoming, non-round existing)
      → incoming replaces existing entirely
        ('42', '3') → '3'    ('2', '5') → '5'
    - If either value is non-integer (decimal/negative) the incoming value
      replaces the existing one entirely.
    """
    try:
        a = int(existing)
        b = int(incoming)
    except ValueError:
        return incoming  # non-integer (decimal, empty, etc.) — treat as a fresh answer
    if a < 0 or b < 0:
        return incoming  # negative — treat as a fresh answer
    if a > b >= 0:
        # 'a' is a round multiple of the next power of 10 above 'b',
        # so 'b' fills in the lower digits (e.g. 40 + 2, 100 + 42).
        power = 10 ** len(str(b))
        if a % power == 0:
            return str(a + b)
    return incoming  # not a continuation — replace with the new number


def _amplify_audio(data: bytes, gain: int) -> bytes:
    """Scale 16-bit little-endian PCM samples by gain, clamping to ±32767."""
    samples = array.array("h", data)
    return array.array(
        "h", (max(-32768, min(32767, s * gain)) for s in samples)
    ).tobytes()


def _parse_spoken_number(text: str) -> Optional[str]:
    """Parse spoken text to a digit string suitable for the answer buffer.

    Returns 'ENTER' for submit commands, a numeric string for numbers, or None
    if the text cannot be interpreted as either.
    """
    text = text.strip().lower()
    words = text.split()
    if not words:
        return None

    # Submit commands
    if words[0] == "enter":
        return "ENTER"

    # Vosk may transcribe digits directly (e.g. "42", "-5", "3.5")
    stripped = text.lstrip("-")
    if stripped.replace(".", "", 1).isdigit() and stripped.count(".") <= 1:
        return text

    # Optional negative prefix
    negative = False
    if words[0] in ("minus", "negative"):
        negative = True
        words = words[1:]
    if not words:
        return None

    # Split on "point" for decimal portion
    try:
        pt_idx = words.index("point")
        int_words = words[:pt_idx]
        dec_words = words[pt_idx + 1 :]
    except ValueError:
        int_words = words
        dec_words = []

    if not int_words:
        return None

    int_val = _words_to_int(int_words)
    if int_val is None:
        return None

    result = ("-" if negative else "") + str(int_val)

    if dec_words:
        dec_str = ""
        for w in dec_words:
            val = _WORD_TO_NUM.get(w)
            if val is not None and val <= 9:
                dec_str += str(val)
            elif w.isdigit() and len(w) == 1:
                dec_str += w
            else:
                break  # ignore unrecognised trailing words
        if dec_str:
            result += "." + dec_str

    return result


@contextlib.contextmanager
def _silence_stderr():
    """Redirect the OS-level stderr (fd 2) to /dev/null for the duration.

    This suppresses C-library chatter (ALSA probing errors, JACK connection
    failures, vosk LOG lines) that would otherwise corrupt the curses display.
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved = os.dup(2)
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
        ('enter',   '')          — user said a submit command ('enter')
        ('clear',   '')          — user said a clear command ('no')
    """

    SAMPLE_RATE = 16000
    CHUNK_SIZE = 200  # 12.5 ms per processing cycle
    INPUT_GAIN = 4  # amplify PCM before recognition (helps with distance)

    # Restrict recognition to only the words the number parser uses.
    # This dramatically improves accuracy and speed compared to open vocabulary.
    # Derived from _WORD_TO_NUM so the two never drift out of sync.
    _VOCAB = json.dumps(
        list(_WORD_TO_NUM)
        + ["point", "minus", "negative", "and", "enter", "no", "[unk]"]
    )

    def __init__(self, model_dir: Path = VOICE_MODEL_DIR):
        self._model_dir = model_dir
        self._events: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.error: Optional[str] = None
        self._enter_pending = False  # enter already queued — suppress re-fire
        self._clear_pending = False  # clear already queued — suppress re-fire
        self._acted_on_partial = (
            False  # combined partial acted on — suppress real final
        )
        self._last_combined_num: Optional[str] = (
            None  # for combined-partial stability check
        )

    def start(self) -> bool:
        """Start the background recognition thread.  Returns True on success."""
        if not _VOICE_AVAILABLE:
            self.error = (
                "vosk and pyaudio must be installed for voice mode — "
                "run: pip install vosk pyaudio"
            )
            return False
        if not self._model_dir.exists():
            self.error = (
                f"Voice model not found: {self._model_dir}\n"
                f"Download a model from https://alphacephei.com/vosk/models "
                f"and unpack it to that path."
            )
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

        All enter events fire as early as possible — on the first partial that
        contains "enter" — rather than waiting for vosk to finalise the utterance
        (which requires a VAD silence timeout of ~300–500 ms).

        Two dedup flags prevent double-firing:
        - _enter_pending: enter already queued; ignore further enter signals until
          a new number resets it.
        - _acted_on_partial: a combined partial (number + enter) was already acted
          on; suppress the real final that vosk will emit for the same utterance.
        """
        words = text.split()
        has_sub = bool(words) and words[-1] == "enter"
        num_words = words[:-1] if has_sub else words
        num_text = " ".join(num_words)

        # Suppress all further events for this utterance once we acted on the
        # combined partial.  Vosk can re-emit the same partial multiple times as
        # it refines its hypothesis; without this, each re-emission would reset
        # _enter_pending and fire another enter event.
        if self._acted_on_partial:
            if final:
                self._acted_on_partial = False
                self._last_combined_num = None
                self._enter_pending = False  # re-arm so the next enter fires
            return

        # "no" is a clear command — wipe the current entry.  It may appear
        # anywhere in the phrase ("forty no fifty nine") so search for the first
        # occurrence.  Everything before "no" is discarded; everything after is
        # the new intended input and is processed recursively on the final.
        # On a partial, only the clear fires — the remainder waits for the final
        # to avoid acting on a still-refining hypothesis.
        no_idx = next((i for i, w in enumerate(words) if w == "no"), -1)
        if no_idx >= 0:
            if not self._clear_pending:
                self._clear_pending = True
                self._enter_pending = False
                self._last_combined_num = None
                self._events.put(("clear", ""))
            if final:
                remainder = words[no_idx + 1 :]
                if remainder:
                    self._emit_text(" ".join(remainder), final=True)
                self._clear_pending = False
            return

        if num_text:
            val = _parse_spoken_number(num_text)
            if val == "ENTER":
                # "enter" at start of utterance (e.g. vosk returned "enter forty")
                # — treat as enter only, final only to avoid duplicates.
                if final and not self._enter_pending:
                    self._enter_pending = True
                    self._events.put(("enter", ""))
                self._last_combined_num = None
                return
            if val is not None:
                self._enter_pending = False
                self._clear_pending = False
                if has_sub and not final:
                    # Combined partial: require the same number value in two
                    # consecutive partials before committing.  This prevents
                    # acting on an intermediate partial (e.g. "forty enter")
                    # before vosk settles on the correct "forty two enter".
                    if val != self._last_combined_num:
                        self._last_combined_num = val
                        self._events.put(("partial", val))
                        return  # not yet stable — don't fire enter
                    # Stable — commit as final, then fall through to fire enter.
                    self._last_combined_num = None
                    self._events.put(("final", val))
                else:
                    self._last_combined_num = None
                    kind = "final" if final else "partial"
                    self._events.put((kind, val))

        if final:
            self._last_combined_num = None

        if has_sub and not self._enter_pending:
            self._enter_pending = True
            # Remember we acted on a partial so the real final is suppressed.
            if not final and num_text:
                self._acted_on_partial = True
            self._events.put(("enter", ""))

    def _loop(self) -> None:
        try:
            # Suppress C-library noise (ALSA/JACK errors, vosk LOG lines, and
            # audio-device probing chatter) so they don't bleed into the curses
            # display.  pa.open() is included because device selection can also
            # produce ALSA stderr output.
            with _silence_stderr():
                _vosk.SetLogLevel(-1)
                model = _vosk.Model(str(self._model_dir))
                # Restricted vocab + no word-level timing = faster inference.
                rec = _vosk.KaldiRecognizer(model, self.SAMPLE_RATE, self._VOCAB)
                pa = _pyaudio.PyAudio()
                stream = pa.open(
                    format=_pyaudio.paInt16,
                    channels=1,
                    rate=self.SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=self.CHUNK_SIZE,
                )
                # Keep stderr suppressed for the streaming loop too: ALSA can
                # emit noise during reads and stream teardown, not just at init.
                try:
                    while not self._stop.is_set():
                        raw = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                        data = _amplify_audio(raw, self.INPUT_GAIN)
                        if rec.AcceptWaveform(data):
                            text = json.loads(rec.Result()).get("text", "").strip()
                            if text:
                                self._emit_text(text, final=True)
                        else:
                            partial = (
                                json.loads(rec.PartialResult())
                                .get("partial", "")
                                .strip()
                            )
                            if partial:
                                self._emit_text(partial, final=False)
                finally:
                    stream.stop_stream()
                    stream.close()
                    pa.terminate()
        except Exception as exc:
            self.error = str(exc)
