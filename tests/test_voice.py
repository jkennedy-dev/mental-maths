"""Tests for voice recognition logic and voice-related game behaviour."""

from unittest.mock import MagicMock

from mentalmaths.models import OpConfig
import mentalmaths.voice as _voice_mod
from mentalmaths.voice import (
    _words_to_int,
    _parse_spoken_number,
    _amplify_audio,
    _combine_spoken_nums,
    VoiceListener,
)
from mentalmaths.ui.game import Game


# ===========================================================================
# _words_to_int
# ===========================================================================


class TestWordsToInt:
    def test_single_digit(self):
        assert _words_to_int(["five"]) == 5

    def test_zero(self):
        assert _words_to_int(["zero"]) == 0

    def test_teen(self):
        assert _words_to_int(["thirteen"]) == 13

    def test_tens(self):
        assert _words_to_int(["forty"]) == 40

    def test_tens_and_ones(self):
        assert _words_to_int(["forty", "two"]) == 42

    def test_hundred(self):
        assert _words_to_int(["one", "hundred"]) == 100

    def test_hundred_and_ones(self):
        assert _words_to_int(["one", "hundred", "and", "five"]) == 105

    def test_hundred_tens_ones(self):
        assert _words_to_int(["one", "hundred", "and", "forty", "two"]) == 142

    def test_numeric_string(self):
        assert _words_to_int(["42"]) == 42

    def test_empty_returns_none(self):
        assert _words_to_int([]) is None

    def test_unknown_word_returns_none(self):
        assert _words_to_int(["hello"]) is None


# ===========================================================================
# _parse_spoken_number
# ===========================================================================


class TestParseSpokenNumber:
    def test_single_digit_word(self):
        assert _parse_spoken_number("five") == "5"

    def test_zero(self):
        assert _parse_spoken_number("zero") == "0"

    def test_teen(self):
        assert _parse_spoken_number("thirteen") == "13"

    def test_tens(self):
        assert _parse_spoken_number("forty") == "40"

    def test_compound(self):
        assert _parse_spoken_number("forty two") == "42"

    def test_hundred(self):
        assert _parse_spoken_number("one hundred") == "100"

    def test_hundred_compound(self):
        assert _parse_spoken_number("one hundred and forty two") == "142"

    def test_negative_minus(self):
        assert _parse_spoken_number("minus five") == "-5"

    def test_negative_word(self):
        assert _parse_spoken_number("negative three") == "-3"

    def test_decimal(self):
        assert _parse_spoken_number("three point five") == "3.5"

    def test_decimal_two_places(self):
        assert _parse_spoken_number("one point two five") == "1.25"

    def test_negative_decimal(self):
        assert _parse_spoken_number("minus three point five") == "-3.5"

    def test_enter_command(self):
        assert _parse_spoken_number("enter") == "ENTER"

    def test_numeric_string(self):
        assert _parse_spoken_number("42") == "42"

    def test_numeric_string_negative(self):
        assert _parse_spoken_number("-5") == "-5"

    def test_numeric_string_decimal(self):
        assert _parse_spoken_number("3.5") == "3.5"

    def test_empty_returns_none(self):
        assert _parse_spoken_number("") is None

    def test_whitespace_returns_none(self):
        assert _parse_spoken_number("   ") is None

    def test_unrecognized_returns_none(self):
        assert _parse_spoken_number("hello world") is None

    def test_case_insensitive(self):
        assert _parse_spoken_number("FORTY TWO") == "42"

    def test_nineteen(self):
        assert _parse_spoken_number("nineteen") == "19"


# ===========================================================================
# _combine_spoken_nums
# ===========================================================================


class TestCombineSpokenNums:
    # ---- round-number arithmetic combination --------------------------------
    def test_tens_plus_units(self):
        assert _combine_spoken_nums("40", "2") == "42"

    def test_twenty_plus_units(self):
        assert _combine_spoken_nums("20", "5") == "25"

    def test_hundred_plus_tens_units(self):
        assert _combine_spoken_nums("100", "42") == "142"

    def test_partial_hundred_plus_units(self):
        assert _combine_spoken_nums("140", "2") == "142"

    def test_thousand_plus_hundreds(self):
        assert _combine_spoken_nums("1000", "200") == "1200"

    def test_ten_plus_units(self):
        assert _combine_spoken_nums("10", "5") == "15"

    # ---- non-continuation replaces ------------------------------------------
    def test_same_magnitude_replaces(self):
        # '42' followed by '43' — user is correcting their answer
        assert _combine_spoken_nums("42", "43") == "43"

    def test_single_digit_after_multi_replaces(self):
        # '42' is not a round multiple, so '3' replaces it
        assert _combine_spoken_nums("42", "3") == "3"

    def test_larger_incoming_replaces(self):
        assert _combine_spoken_nums("2", "5") == "5"

    def test_non_round_tens_replaces(self):
        # 43 % 10 = 3 ≠ 0 so incoming replaces
        assert _combine_spoken_nums("43", "2") == "2"

    # ---- non-integer restart ------------------------------------------------
    def test_decimal_existing_restarts(self):
        assert _combine_spoken_nums("3.5", "2") == "2"

    def test_negative_existing_restarts(self):
        assert _combine_spoken_nums("-5", "3") == "3"

    def test_decimal_incoming_restarts(self):
        assert _combine_spoken_nums("40", "2.5") == "2.5"

    # ---- zero continuation --------------------------------------------------
    def test_round_plus_zero(self):
        # "one hundred" followed by "zero" should combine to "100", not "0"
        assert _combine_spoken_nums("100", "0") == "100"

    def test_ten_plus_zero(self):
        assert _combine_spoken_nums("10", "0") == "10"

    def test_non_round_plus_zero_replaces(self):
        # 5 % 10 != 0, so "zero" replaces
        assert _combine_spoken_nums("5", "0") == "0"

    # ---- empty existing -----------------------------------------------------
    def test_empty_existing_returns_incoming(self):
        # Not called with empty existing in practice, but defensive check.
        assert _combine_spoken_nums("", "42") == "42"


# ===========================================================================
# _amplify_audio
# ===========================================================================


class TestAmplifyAudio:
    def _pack(self, samples):
        import array

        return array.array("h", samples).tobytes()

    def _unpack(self, data):
        import array

        return list(array.array("h", data))

    def test_amplifies_by_gain(self):
        data = self._pack([100, 200, -100])
        result = self._unpack(_amplify_audio(data, 3))
        assert result == [300, 600, -300]

    def test_clamps_positive_overflow(self):
        data = self._pack([20000])
        result = self._unpack(_amplify_audio(data, 4))
        assert result == [32767]

    def test_clamps_negative_overflow(self):
        data = self._pack([-20000])
        result = self._unpack(_amplify_audio(data, 4))
        assert result == [-32768]

    def test_gain_one_is_unchanged(self):
        samples = [1000, -500, 0, 32767, -32768]
        data = self._pack(samples)
        assert self._unpack(_amplify_audio(data, 1)) == samples

    def test_zero_samples_unchanged(self):
        data = self._pack([0, 0, 0])
        assert self._unpack(_amplify_audio(data, 10)) == [0, 0, 0]


# ===========================================================================
# VoiceListener
# ===========================================================================


class TestVoiceListener:
    def test_get_nowait_empty_returns_none(self):
        listener = VoiceListener()
        assert listener.get_nowait() is None

    def test_events_queue_fifo(self):
        listener = VoiceListener()
        listener._events.put(("final", "42"))
        listener._events.put(("enter", ""))
        assert listener.get_nowait() == ("final", "42")
        assert listener.get_nowait() == ("enter", "")
        assert listener.get_nowait() is None

    def test_stop_sets_flag(self):
        listener = VoiceListener()
        assert not listener._stop.is_set()
        listener.stop()
        assert listener._stop.is_set()

    def test_start_fails_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(_voice_mod, "_VOICE_AVAILABLE", False)
        listener = VoiceListener()
        assert listener.start() is False
        assert listener.error is not None

    def test_start_fails_without_model(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_voice_mod, "_VOICE_AVAILABLE", True)
        listener = VoiceListener(model_dir=tmp_path / "no-model")
        assert listener.start() is False
        assert listener.error is not None

    def test_start_ok_with_model_dir(self, tmp_path, monkeypatch):
        """start() returns True when model dir exists and dependencies available."""
        monkeypatch.setattr(_voice_mod, "_VOICE_AVAILABLE", True)
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        listener = VoiceListener(model_dir=model_dir)
        # Patch _loop so no real audio hardware is accessed.
        listener._loop = lambda: None
        assert listener.start() is True
        listener.stop()


# ===========================================================================
# VoiceListener._emit_text
# ===========================================================================


class TestEmitText:
    def _listener(self):
        return VoiceListener()

    def test_number_final(self):
        listener = self._listener()
        listener._emit_text("forty two", final=True)
        assert listener.get_nowait() == ("final", "42")
        assert listener.get_nowait() is None

    def test_number_partial(self):
        listener = self._listener()
        listener._emit_text("forty", final=False)
        assert listener.get_nowait() == ("partial", "40")

    def test_enter_only(self):
        listener = self._listener()
        listener._emit_text("enter", final=True)
        assert listener.get_nowait() == ("enter", "")
        assert listener.get_nowait() is None

    def test_number_then_enter_combined(self):
        """'forty two enter' in one utterance emits number then enter."""
        listener = self._listener()
        listener._emit_text("forty two enter", final=True)
        assert listener.get_nowait() == ("final", "42")
        assert listener.get_nowait() == ("enter", "")
        assert listener.get_nowait() is None

    def test_number_then_submit_not_recognised(self):
        listener = self._listener()
        listener._emit_text("eight submit", final=True)
        assert listener.get_nowait() is None

    def test_combined_partial_fires_after_stable(self):
        # First combined partial shows the number as a partial only.
        # Only the second consecutive partial with the same number commits.
        listener = self._listener()
        listener._emit_text("forty enter", final=False)
        assert listener.get_nowait() == ("partial", "40")
        assert listener.get_nowait() is None
        listener._emit_text("forty enter", final=False)
        assert listener.get_nowait() == ("final", "40")
        assert listener.get_nowait() == ("enter", "")
        assert listener.get_nowait() is None

    def test_combined_partial_refines_before_firing(self):
        # If vosk refines "forty enter" → "forty two enter", stability resets
        # so only the settled value fires.
        listener = self._listener()
        listener._emit_text("forty enter", final=False)
        assert listener.get_nowait() == ("partial", "40")
        listener._emit_text("forty two enter", final=False)
        assert listener.get_nowait() == ("partial", "42")  # changed — reset stability
        listener._emit_text("forty two enter", final=False)
        assert listener.get_nowait() == ("final", "42")  # stable now
        assert listener.get_nowait() == ("enter", "")
        assert listener.get_nowait() is None

    def test_combined_partial_suppresses_real_final(self):
        # The real vosk final for an already-acted-on combined partial is dropped.
        listener = self._listener()
        listener._emit_text("forty two enter", final=False)  # first — not yet stable
        listener.get_nowait()  # ('partial', '42')
        listener._emit_text("forty two enter", final=False)  # second — stable, fires
        listener.get_nowait()  # ('final', '42')
        listener.get_nowait()  # ('enter', '')
        listener._emit_text("forty two enter", final=True)  # real final — suppressed
        assert listener.get_nowait() is None

    def test_standalone_enter_fires_on_partial(self):
        # Standalone "enter" (no preceding number) fires immediately on a partial
        # result, bypassing the VAD silence wait for lower latency.
        listener = self._listener()
        listener._emit_text("enter", final=False)
        assert listener.get_nowait() == ("enter", "")

    def test_standalone_enter_not_duplicated_by_final(self):
        # Once enter fires from a partial, the subsequent final must be suppressed.
        listener = self._listener()
        listener._emit_text("enter", final=False)
        assert listener.get_nowait() == ("enter", "")
        listener._emit_text("enter", final=True)
        assert listener.get_nowait() is None

    def test_new_number_resets_enter_dedup(self):
        # After a number event, enter should fire again (dedup flag reset).
        listener = self._listener()
        listener._emit_text("enter", final=False)
        listener.get_nowait()  # consume the enter
        listener._emit_text("forty two", final=True)
        listener.get_nowait()  # consume the number
        listener._emit_text("enter", final=False)
        assert listener.get_nowait() == ("enter", "")

    def test_unrecognised_text_emits_nothing(self):
        listener = self._listener()
        listener._emit_text("hello world", final=True)
        assert listener.get_nowait() is None

    def test_empty_text_emits_nothing(self):
        listener = self._listener()
        listener._emit_text("", final=True)
        assert listener.get_nowait() is None

    def test_enter_at_start_emits_enter_not_buf(self):
        """'enter forty' should produce an enter event, not put 'ENTER' in the buf."""
        listener = self._listener()
        listener._emit_text("enter forty", final=True)
        assert listener.get_nowait() == ("enter", "")
        assert listener.get_nowait() is None  # no spurious number event

    def test_enter_at_start_partial_no_submit(self):
        # "enter five" partial — enter at start treated as ENTER-only path,
        # which requires final=True, so nothing is emitted here.
        listener = self._listener()
        listener._emit_text("enter five", final=False)
        assert listener.get_nowait() is None

    def test_no_emits_clear_on_partial(self):
        # "no" fires immediately without waiting for the VAD silence final.
        listener = self._listener()
        listener._emit_text("no", final=False)
        assert listener.get_nowait() == ("clear", "")
        assert listener.get_nowait() is None

    def test_no_emits_clear_on_final(self):
        listener = self._listener()
        listener._emit_text("no", final=True)
        assert listener.get_nowait() == ("clear", "")
        assert listener.get_nowait() is None

    def test_no_not_duplicated_by_final(self):
        # Partial fires the clear; the subsequent vosk final must be suppressed.
        listener = self._listener()
        listener._emit_text("no", final=False)
        assert listener.get_nowait() == ("clear", "")
        listener._emit_text("no", final=True)
        assert listener.get_nowait() is None

    def test_no_resets_after_new_number(self):
        # After a clear, saying a new number re-arms 'no' for future use.
        listener = self._listener()
        listener._emit_text("no", final=False)
        listener.get_nowait()  # consume the clear
        listener._emit_text("forty two", final=True)
        listener.get_nowait()  # consume the number
        listener._emit_text("no", final=False)
        assert listener.get_nowait() == ("clear", "")

    def test_no_followed_by_number_clears_then_enters_number(self):
        # "no forty" said quickly as one breath: clear fires AND the number
        # is processed so the player does not need a second utterance.
        listener = self._listener()
        listener._emit_text("no forty", final=True)
        assert listener.get_nowait() == ("clear", "")
        assert listener.get_nowait() == ("final", "40")
        assert listener.get_nowait() is None

    def test_no_followed_by_number_and_enter(self):
        # "no forty two enter" in one breath: clear + final 42 + enter.
        listener = self._listener()
        listener._emit_text("no forty two enter", final=True)
        assert listener.get_nowait() == ("clear", "")
        assert listener.get_nowait() == ("final", "42")
        assert listener.get_nowait() == ("enter", "")
        assert listener.get_nowait() is None

    def test_trailing_no_clears(self):
        # "forty no" — "no" anywhere in the phrase acts as clear; the number
        # before it is discarded (the player is cancelling it).
        listener = self._listener()
        listener._emit_text("forty no", final=True)
        assert listener.get_nowait() == ("clear", "")
        assert listener.get_nowait() is None

    def test_no_mid_utterance_clears_then_enters_number(self):
        # "forty no fifty nine" — clear fires and the new number is processed.
        listener = self._listener()
        listener._emit_text("forty no fifty nine", final=True)
        assert listener.get_nowait() == ("clear", "")
        assert listener.get_nowait() == ("final", "59")
        assert listener.get_nowait() is None

    def test_no_mid_utterance_with_enter(self):
        # "forty no fifty nine enter" — clear + final 59 + enter, all in one breath.
        listener = self._listener()
        listener._emit_text("forty no fifty nine enter", final=True)
        assert listener.get_nowait() == ("clear", "")
        assert listener.get_nowait() == ("final", "59")
        assert listener.get_nowait() == ("enter", "")
        assert listener.get_nowait() is None

    def test_no_mid_utterance_partial_only_clears(self):
        # On a partial, only the clear fires — the number after "no" waits for
        # the final to avoid acting on a still-refining hypothesis.
        listener = self._listener()
        listener._emit_text("forty no fifty nine", final=False)
        assert listener.get_nowait() == ("clear", "")
        assert listener.get_nowait() is None

    def test_double_no_fires_only_one_clear(self):
        # "no no" (or any phrase with two "no" words) should produce exactly
        # one clear event, not two.
        listener = self._listener()
        listener._emit_text("no no", final=True)
        assert listener.get_nowait() == ("clear", "")
        assert listener.get_nowait() is None

    def test_enter_rearms_after_acted_on_partial_final(self):
        """Bug: after a combined partial fires via stability check, the real vosk
        final is suppressed but _enter_pending is left True.  A subsequent
        standalone 'enter' (e.g. the user submits the next question without
        first saying a number) must NOT be swallowed."""
        listener = self._listener()
        # Step 1: drive the combined-partial stability check to fire.
        listener._emit_text("forty two enter", final=False)  # first — not yet stable
        listener.get_nowait()  # ("partial", "42")
        listener._emit_text("forty two enter", final=False)  # second — stable, fires
        listener.get_nowait()  # ("final", "42")
        listener.get_nowait()  # ("enter", "")
        # Step 2: real vosk final arrives — correctly suppressed.
        listener._emit_text("forty two enter", final=True)
        assert listener.get_nowait() is None
        # Step 3: subsequent standalone "enter" must now fire (flag re-armed).
        listener._emit_text("enter", final=True)
        assert listener.get_nowait() == ("enter", "")


# ===========================================================================
# Game._process_voice_events
# ===========================================================================


def _make_game():
    stdscr = MagicMock()
    stdscr.getmaxyx.return_value = (24, 80)
    cfg = OpConfig("Addition", digits=1, decimals=0)
    return Game(stdscr, [cfg], 60)


def _mock_listener(**attrs):
    listener = MagicMock()
    listener.error = None
    for k, v in attrs.items():
        setattr(listener, k, v)
    return listener


class TestGameVoiceEvents:
    def test_no_listener_returns_false(self):
        g = _make_game()
        g.voice_listener = None
        assert g._process_voice_events() is False

    def test_returns_true_when_events_processed(self):
        g = _make_game()
        listener = _mock_listener()
        listener.get_nowait.side_effect = [("partial", "4"), None]
        g.voice_listener = listener
        assert g._process_voice_events() is True

    def test_returns_false_when_queue_empty(self):
        g = _make_game()
        listener = _mock_listener()
        listener.get_nowait.return_value = None
        g.voice_listener = listener
        assert g._process_voice_events() is False

    def test_no_listener_is_noop(self):
        g = _make_game()
        g.voice_listener = None
        g._process_voice_events()  # must not raise

    def test_final_number_sets_buf(self):
        g = _make_game()
        listener = _mock_listener()
        listener.get_nowait.side_effect = [("final", "42"), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == "42"
        assert g.voice_partial == ""

    def test_partial_sets_voice_partial(self):
        g = _make_game()
        listener = _mock_listener()
        listener.get_nowait.side_effect = [("partial", "40"), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.voice_partial == "40"
        assert g.buf == ""

    def test_enter_submits_buffer(self):
        g = _make_game()
        g.buf = "8"
        listener = _mock_listener()
        listener.get_nowait.side_effect = [("enter", ""), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == ""
        assert len(g.questions) == 1

    def test_enter_ignored_when_buf_empty(self):
        g = _make_game()
        g.buf = ""
        g.voice_partial = ""
        listener = _mock_listener()
        listener.get_nowait.side_effect = [("enter", ""), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert len(g.questions) == 0

    def test_enter_clears_voice_partial(self):
        g = _make_game()
        g.buf = "5"
        g.voice_partial = "5"
        listener = _mock_listener()
        listener.get_nowait.side_effect = [("enter", ""), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.voice_partial == ""

    def test_slow_speech_combines_finals(self):
        """Two separate finals ('forty' then 'two') should combine to '42'."""
        g = _make_game()
        listener = _mock_listener()
        listener.get_nowait.side_effect = [("final", "40"), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == "40"

        listener.get_nowait.side_effect = [("final", "2"), None]
        g._process_voice_events()
        assert g.buf == "42"

    def test_enter_commits_pending_partial(self):
        """Enter should commit voice_partial into buf before submitting."""
        g = _make_game()
        g.buf = "40"
        g.voice_partial = "2"
        listener = _mock_listener()
        listener.get_nowait.side_effect = [("enter", ""), None]
        g.voice_listener = listener
        g._process_voice_events()
        # Submitted answer should be '42', not '40'
        assert len(g.questions) == 1
        assert g.questions[0].user_answer == "42"
        assert g.voice_partial == ""

    def test_multiple_events_in_order(self):
        g = _make_game()
        listener = _mock_listener()
        listener.get_nowait.side_effect = [
            ("partial", "4"),
            ("final", "42"),
            None,
        ]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == "42"
        assert g.voice_partial == ""

    def test_partial_rescued_when_vosk_drops_word_from_final(self):
        """Bug: vosk drops the first word of a phrase from the final result.
        e.g. user says 'forty five'; partial shows '40' but vosk finalises
        as just 'five'.  The partial should be used to reconstruct '45'."""
        g = _make_game()
        listener = _mock_listener()
        listener.get_nowait.side_effect = [
            ("partial", "40"),  # "forty" heard during speech
            ("final", "5"),  # vosk dropped "forty", only finalised "five"
            None,
        ]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == "45"
        assert g.voice_partial == ""

    def test_partial_preferred_when_full_phrase_partial_then_truncated_final(self):
        """Remaining gap after the earlier partial-rescue fix: vosk correctly
        builds partial 'forty five'=45, but its final drops 'forty' and
        only returns 'five'=5.  _combine_spoken_nums('45','5') replaces rather
        than adds, so we must fall back to the partial instead."""
        g = _make_game()
        listener = _mock_listener()
        listener.get_nowait.side_effect = [
            ("partial", "45"),  # "forty five" heard during speech
            ("final", "5"),  # vosk only finalised "five"
            None,
        ]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == "45"
        assert g.voice_partial == ""

    def test_larger_final_beats_partial(self):
        """A final that is numerically larger than the partial is a legitimate
        refinement (more words recognised), not a truncation — use the final."""
        g = _make_game()
        listener = _mock_listener()
        listener.get_nowait.side_effect = [
            ("partial", "40"),
            ("final", "42"),  # vosk correctly identified "forty two"
            None,
        ]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == "42"
        assert g.voice_partial == ""

    def test_spurious_partial_not_committed_on_enter(self):
        """Bug: after a correct final ('45'), trailing audio from the last
        word leaks into the next recognition window as a partial ('5').
        On enter the combine would replace '45' with '5'.  The partial must
        be discarded instead."""
        g = _make_game()
        g.buf = "45"
        g.voice_partial = "5"
        listener = _mock_listener()
        listener.get_nowait.side_effect = [("enter", ""), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert len(g.questions) == 1
        assert g.questions[0].user_answer == "45"

    def test_thread_error_clears_listener_and_stores_message(self):
        """If the voice thread crashes, _process_voice_events detects it and
        moves the error message into _voice_error so the UI can display it."""
        g = _make_game()
        listener = _mock_listener(error="Microphone disconnected")
        listener.get_nowait.return_value = None
        g.voice_listener = listener
        result = g._process_voice_events()
        assert g.voice_listener is None
        assert g._voice_error == "Microphone disconnected"
        assert result is False

    def test_thread_error_not_triggered_when_no_error(self):
        """A healthy listener (error=None) must not be cleared."""
        g = _make_game()
        listener = _mock_listener()  # error=None by default
        listener.get_nowait.return_value = None
        g.voice_listener = listener
        g._process_voice_events()
        assert g.voice_listener is listener

    def test_clear_event_resets_buf_and_partial(self):
        """A 'clear' event wipes buf and voice_partial so the player starts over."""
        g = _make_game()
        g.buf = "42"
        g.voice_partial = "5"
        listener = _mock_listener()
        listener.get_nowait.side_effect = [("clear", ""), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == ""
        assert g.voice_partial == ""
        assert len(g.questions) == 0  # nothing submitted

    def test_clear_then_new_answer_works(self):
        """After a clear the player can say a fresh number normally."""
        g = _make_game()
        g.buf = "99"
        listener = _mock_listener()
        listener.get_nowait.side_effect = [
            ("clear", ""),
            ("final", "42"),
            None,
        ]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == "42"


# ===========================================================================
# Game._handle_backspace
# ===========================================================================


class TestGameHandleBackspace:
    def test_keyboard_mode_removes_last_char(self):
        g = _make_game()
        g.buf = "42"
        g.voice_listener = None
        g._handle_backspace()
        assert g.buf == "4"
        assert g.voice_partial == ""

    def test_keyboard_mode_on_empty_buf_is_noop(self):
        g = _make_game()
        g.buf = ""
        g.voice_listener = None
        g._handle_backspace()
        assert g.buf == ""

    def test_voice_mode_clears_buf_and_partial(self):
        """In voice mode the whole buffer is cleared, not just the last char."""
        g = _make_game()
        g.buf = "42"
        g.voice_partial = "5"
        g.voice_listener = _mock_listener()
        g._handle_backspace()
        assert g.buf == ""
        assert g.voice_partial == ""

    def test_voice_mode_clears_partial_only_when_buf_empty(self):
        g = _make_game()
        g.buf = ""
        g.voice_partial = "40"
        g.voice_listener = _mock_listener()
        g._handle_backspace()
        assert g.buf == ""
        assert g.voice_partial == ""
