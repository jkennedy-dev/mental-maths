"""Tests for mental-maths core logic (no curses required)."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add project root to sys.path so the mentalmaths package is importable.
sys.path.insert(0, str(Path(__file__).parent.parent))

from mentalmaths.constants import TIME_OPTIONS
from mentalmaths.models import OpConfig, Question
from mentalmaths.questions import generate_question, check_answer, _rnd, _fmt
import mentalmaths.storage as _storage_mod
from mentalmaths.storage import (
    _cfg_to_dict,
    _dict_to_cfg,
    _load_data,
    _save_data,
    _make_session,
)
import mentalmaths.voice as _voice_mod
from mentalmaths.voice import (
    _words_to_int,
    _parse_spoken_number,
    _amplify_audio,
    _combine_spoken_nums,
    VoiceListener,
)
from mentalmaths.ui.game import Game
from mentalmaths.ui.results import _q_line
from mentalmaths.ui.menus import _build_rows


# ===========================================================================
# OpConfig.label
# ===========================================================================


class TestOpConfigLabel:
    def test_addition_basic(self):
        cfg = OpConfig("Addition", digits=2)
        assert cfg.label == "Addition (2-digit)"

    def test_addition_with_decimals(self):
        cfg = OpConfig("Addition", digits=3, decimals=2)
        assert cfg.label == "Addition (3-digit, 2dp)"

    def test_subtraction_no_negative(self):
        cfg = OpConfig("Subtraction", digits=1)
        assert cfg.label == "Subtraction (1-digit)"

    def test_subtraction_with_negative(self):
        cfg = OpConfig("Subtraction", digits=2, allow_negative=True)
        assert cfg.label == "Subtraction (2-digit, neg)"

    def test_subtraction_decimals_and_negative(self):
        cfg = OpConfig("Subtraction", digits=2, decimals=1, allow_negative=True)
        assert cfg.label == "Subtraction (2-digit, 1dp, neg)"

    def test_multiplication_shows_range(self):
        cfg = OpConfig("Multiplication", operand2_lo=3, operand2_hi=9)
        assert cfg.label == "Multiplication (3-9)"

    def test_multiplication_with_decimals(self):
        cfg = OpConfig("Multiplication", operand2_lo=2, operand2_hi=12, decimals=1)
        assert cfg.label == "Multiplication (2-12, 1dp)"

    def test_division_shows_range(self):
        cfg = OpConfig("Division", operand2_lo=2, operand2_hi=12)
        assert cfg.label == "Division (2-12)"

    def test_division_with_decimals(self):
        cfg = OpConfig("Division", operand2_lo=4, operand2_hi=8, decimals=2)
        assert cfg.label == "Division (4-8, 2dp)"


# ===========================================================================
# Question.answer_str
# ===========================================================================


class TestQuestionAnswerStr:
    def test_integer_answer(self):
        q = Question("1 + 1", 2.0, 0)
        assert q.answer_str == "2"

    def test_integer_answer_rounds(self):
        q = Question("x", 2.9999999, 0)
        assert q.answer_str == "3"

    def test_decimal_1dp(self):
        q = Question("x", 1.5, 1)
        assert q.answer_str == "1.5"

    def test_decimal_2dp(self):
        q = Question("x", 3.14, 2)
        assert q.answer_str == "3.14"

    def test_negative_integer(self):
        q = Question("x", -5.0, 0)
        assert q.answer_str == "-5"

    def test_negative_decimal(self):
        q = Question("x", -1.25, 2)
        assert q.answer_str == "-1.25"


# ===========================================================================
# _fmt helper
# ===========================================================================


class TestFmt:
    def test_integer_zero_dec(self):
        assert _fmt(7.0, 0) == "7"

    def test_rounds_to_int(self):
        assert _fmt(6.9, 0) == "7"

    def test_one_decimal(self):
        assert _fmt(3.5, 1) == "3.5"

    def test_two_decimals(self):
        assert _fmt(1.23, 2) == "1.23"

    def test_negative(self):
        assert _fmt(-4.0, 0) == "-4"


# ===========================================================================
# _rnd helper
# ===========================================================================


class TestRnd:
    def test_integer_range(self):
        for _ in range(200):
            v = _rnd(10, 99, 0)
            assert 10 <= v <= 99
            assert v == int(v)  # whole number

    def test_decimal_range(self):
        for _ in range(200):
            v = _rnd(1, 9, 2)
            assert 1.0 <= v < 10.0
            # two decimal places — multiply and check integer
            assert round(v * 100) == int(round(v * 100))

    def test_single_value_range(self):
        for _ in range(50):
            v = _rnd(5, 5, 0)
            assert v == 5.0


# ===========================================================================
# generate_question
# ===========================================================================


class TestGenerateQuestion:
    # ---- Addition ----------------------------------------------------------
    def test_addition_integer_format(self):
        cfg = OpConfig("Addition", digits=2, decimals=0)
        for _ in range(50):
            q = generate_question(cfg)
            assert "+" in q.display
            assert q.answer_dec == 0
            # answer should be an integer value
            assert q.answer == int(round(q.answer))

    def test_addition_operand_range(self):
        cfg = OpConfig("Addition", digits=2, decimals=0)
        for _ in range(100):
            q = generate_question(cfg)
            a_str, b_str = q.display.split(" + ")
            a, b = int(a_str), int(b_str)
            assert 10 <= a <= 99
            assert 10 <= b <= 99
            assert q.answer == a + b

    def test_addition_decimal(self):
        cfg = OpConfig("Addition", digits=1, decimals=1)
        for _ in range(50):
            q = generate_question(cfg)
            assert "+" in q.display
            assert q.answer_dec == 1

    def test_addition_1digit(self):
        cfg = OpConfig("Addition", digits=1, decimals=0)
        for _ in range(100):
            q = generate_question(cfg)
            a_str, b_str = q.display.split(" + ")
            assert 1 <= int(a_str) <= 9
            assert 1 <= int(b_str) <= 9

    # ---- Subtraction -------------------------------------------------------
    def test_subtraction_no_negative_result(self):
        cfg = OpConfig("Subtraction", digits=2, decimals=0, allow_negative=False)
        for _ in range(200):
            q = generate_question(cfg)
            assert q.answer >= 0

    def test_subtraction_allows_negative(self):
        # Force a case where b > a to guarantee a negative result.
        import random

        cfg = OpConfig("Subtraction", digits=1, decimals=0, allow_negative=True)
        with patch.object(
            random, "randint", side_effect=[3, 7]
        ):  # a=3, b=7 → answer=-4
            q = generate_question(cfg)
        assert q.answer < 0

    def test_subtraction_format(self):
        cfg = OpConfig("Subtraction", digits=2, decimals=0)
        for _ in range(20):
            q = generate_question(cfg)
            assert " - " in q.display

    def test_subtraction_answer_correct(self):
        cfg = OpConfig("Subtraction", digits=2, decimals=0, allow_negative=False)
        for _ in range(50):
            q = generate_question(cfg)
            a_str, b_str = q.display.split(" - ")
            assert float(a_str) - float(b_str) == pytest.approx(q.answer)

    # ---- Multiplication ----------------------------------------------------
    def test_multiplication_format(self):
        cfg = OpConfig("Multiplication", operand2_lo=2, operand2_hi=12)
        for _ in range(20):
            q = generate_question(cfg)
            assert " x " in q.display

    def test_multiplication_operand_range(self):
        cfg = OpConfig("Multiplication", operand2_lo=3, operand2_hi=9)
        for _ in range(100):
            q = generate_question(cfg)
            a_str, b_str = q.display.split(" x ")
            a, b = int(a_str), int(b_str)
            assert 3 <= a <= 9
            assert 3 <= b <= 9
            assert q.answer == a * b

    def test_multiplication_answer_correct(self):
        cfg = OpConfig("Multiplication", operand2_lo=2, operand2_hi=12, decimals=0)
        for _ in range(50):
            q = generate_question(cfg)
            a_str, b_str = q.display.split(" x ")
            assert float(a_str) * float(b_str) == pytest.approx(q.answer)

    # ---- Division ----------------------------------------------------------
    def test_division_format(self):
        cfg = OpConfig("Division", operand2_lo=2, operand2_hi=12)
        for _ in range(20):
            q = generate_question(cfg)
            assert " / " in q.display

    def test_division_integer_exact(self):
        """Integer division always produces a whole-number quotient."""
        cfg = OpConfig("Division", operand2_lo=2, operand2_hi=12, decimals=0)
        for _ in range(100):
            q = generate_question(cfg)
            assert q.answer == int(round(q.answer))

    def test_division_answer_correct_integer(self):
        cfg = OpConfig("Division", operand2_lo=2, operand2_hi=12, decimals=0)
        for _ in range(50):
            q = generate_question(cfg)
            dividend_str, divisor_str = q.display.split(" / ")
            assert float(dividend_str) / float(divisor_str) == pytest.approx(q.answer)

    def test_division_answer_correct_decimal(self):
        cfg = OpConfig("Division", operand2_lo=2, operand2_hi=9, decimals=2)
        for _ in range(50):
            q = generate_question(cfg)
            dividend_str, divisor_str = q.display.split(" / ")
            # Answer is rounded to answer_dec places by design
            expected = round(float(dividend_str) / float(divisor_str), q.answer_dec)
            assert q.answer == pytest.approx(expected, rel=1e-9)

    # ---- op_label propagation ----------------------------------------------
    def test_op_label_set(self):
        cfg = OpConfig("Addition", digits=2)
        q = generate_question(cfg)
        assert q.op_label == cfg.label


# ===========================================================================
# check_answer
# ===========================================================================


class TestCheckAnswer:
    def _q(self, answer, dec):
        return Question("x", answer, dec)

    # ---- Integer answers ---------------------------------------------------
    def test_correct_integer(self):
        assert check_answer("42", self._q(42.0, 0)) is True

    def test_wrong_integer(self):
        assert check_answer("43", self._q(42.0, 0)) is False

    def test_negative_correct(self):
        assert check_answer("-5", self._q(-5.0, 0)) is True

    def test_integer_with_decimal_notation_accepted(self):
        # A user can type '42.0' in the game; it should be treated as correct for answer 42.
        assert check_answer("42.0", self._q(42.0, 0)) is True

    # ---- Decimal answers ---------------------------------------------------
    def test_correct_1dp(self):
        assert check_answer("3.5", self._q(3.5, 1)) is True

    def test_wrong_1dp(self):
        assert check_answer("3.6", self._q(3.5, 1)) is False

    def test_correct_2dp(self):
        assert check_answer("1.23", self._q(1.23, 2)) is True

    def test_decimal_rounding_tolerance(self):
        # User enters more decimal places — should be rounded to match
        assert check_answer("1.235", self._q(1.24, 2)) is True

    # ---- Bad input ---------------------------------------------------------
    def test_empty_string(self):
        assert check_answer("", self._q(5.0, 0)) is False

    def test_non_numeric(self):
        assert check_answer("abc", self._q(5.0, 0)) is False

    def test_none_value(self):
        assert check_answer(None, self._q(5.0, 0)) is False

    def test_just_minus(self):
        # _submit() already blocks '-' before calling check_answer, so this is
        # a defence-in-depth check rather than a real user path.
        assert check_answer("-", self._q(-1.0, 0)) is False

    def test_just_dot(self):
        # _submit() already blocks '.' before calling check_answer, so this is
        # a defence-in-depth check rather than a real user path.
        assert check_answer(".", self._q(0.0, 1)) is False

    # ---- Zero answer -------------------------------------------------------
    def test_zero_correct(self):
        assert check_answer("0", self._q(0.0, 0)) is True

    def test_zero_wrong(self):
        assert check_answer("1", self._q(0.0, 0)) is False


# ===========================================================================
# _cfg_to_dict / _dict_to_cfg  (round-trip)
# ===========================================================================


class TestCfgSerialization:
    def _roundtrip(self, cfg):
        return _dict_to_cfg(_cfg_to_dict(cfg))

    def test_addition_defaults(self):
        cfg = OpConfig("Addition")
        rt = self._roundtrip(cfg)
        assert rt.operation == cfg.operation
        assert rt.digits == cfg.digits
        assert rt.decimals == cfg.decimals
        assert rt.operand2_lo == cfg.operand2_lo
        assert rt.operand2_hi == cfg.operand2_hi
        assert rt.allow_negative == cfg.allow_negative

    def test_subtraction_allow_negative(self):
        cfg = OpConfig("Subtraction", digits=3, decimals=1, allow_negative=True)
        rt = self._roundtrip(cfg)
        assert rt.digits == 3
        assert rt.decimals == 1
        assert rt.allow_negative is True

    def test_multiplication_range(self):
        cfg = OpConfig("Multiplication", operand2_lo=5, operand2_hi=20)
        rt = self._roundtrip(cfg)
        assert rt.operand2_lo == 5
        assert rt.operand2_hi == 20

    def test_division_full(self):
        cfg = OpConfig("Division", operand2_lo=3, operand2_hi=15, decimals=2)
        rt = self._roundtrip(cfg)
        assert rt.operation == "Division"
        assert rt.operand2_lo == 3
        assert rt.operand2_hi == 15
        assert rt.decimals == 2

    def test_dict_to_cfg_uses_defaults_for_missing_keys(self):
        d = {"operation": "Addition"}
        cfg = _dict_to_cfg(d)
        assert cfg.digits == 2
        assert cfg.decimals == 0
        assert cfg.operand2_lo == 2
        assert cfg.operand2_hi == 12
        assert cfg.allow_negative is False


# ===========================================================================
# _load_data / _save_data
# ===========================================================================


class TestDataPersistence:
    def test_load_returns_empty_on_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_storage_mod, "DATA_FILE", tmp_path / "nonexistent.json")
        assert _load_data() == {}

    def test_load_returns_empty_on_corrupt_json(self, tmp_path, monkeypatch):
        f = tmp_path / "data.json"
        f.write_text("NOT JSON")
        monkeypatch.setattr(_storage_mod, "DATA_FILE", f)
        assert _load_data() == {}

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        f = tmp_path / "data.json"
        monkeypatch.setattr(_storage_mod, "DATA_FILE", f)
        data = {"sessions": [{"ts": "2024-01-01 12:00", "total": 10, "correct": 8}]}
        _save_data(data)
        assert _load_data() == data

    def test_save_silently_ignores_os_error(self, tmp_path, monkeypatch):
        f = tmp_path / "data.json"
        monkeypatch.setattr(_storage_mod, "DATA_FILE", f)
        with patch.object(Path, "write_text", side_effect=OSError("no disk")):
            _save_data({"x": 1})  # must not raise

    def test_load_full_structure(self, tmp_path, monkeypatch):
        f = tmp_path / "data.json"
        payload = {"sessions": [], "last_config": {"t_idx": 2, "configs": []}}
        f.write_text(json.dumps(payload))
        monkeypatch.setattr(_storage_mod, "DATA_FILE", f)
        assert _load_data() == payload


# ===========================================================================
# _make_session
# ===========================================================================


class TestMakeSession:
    def _q(self, op_label, correct):
        q = Question("x", 1.0, 0, op_label=op_label)
        q.correct = correct
        return q

    def test_returns_none_for_empty_questions(self):
        cfg = OpConfig("Addition")
        assert _make_session([], [cfg], 30) is None

    def test_basic_session_structure(self):
        cfg = OpConfig("Addition")
        qs = [self._q(cfg.label, True), self._q(cfg.label, False)]
        sess = _make_session(qs, [cfg], 30)
        assert sess is not None
        assert sess["total"] == 2
        assert sess["correct"] == 1
        assert sess["time_limit"] == 30

    def test_per_op_aggregation(self):
        add_cfg = OpConfig("Addition")
        sub_cfg = OpConfig("Subtraction")
        qs = [
            self._q(add_cfg.label, True),
            self._q(add_cfg.label, True),
            self._q(sub_cfg.label, False),
        ]
        sess = _make_session(qs, [add_cfg, sub_cfg], 60)
        assert sess["per_op"][add_cfg.label] == {"total": 2, "correct": 2}
        assert sess["per_op"][sub_cfg.label] == {"total": 1, "correct": 0}

    def test_configs_serialized(self):
        cfg = OpConfig("Multiplication", operand2_lo=3, operand2_hi=9)
        qs = [self._q(cfg.label, True)]
        sess = _make_session(qs, [cfg], 30)
        assert sess["configs"] == [_cfg_to_dict(cfg)]

    def test_time_limit_stored(self):
        cfg = OpConfig("Addition")
        qs = [self._q(cfg.label, True)]
        for _, secs in TIME_OPTIONS:
            sess = _make_session(qs, [cfg], secs)
            assert sess["time_limit"] == secs

    def test_timestamp_format(self):
        import re

        cfg = OpConfig("Addition")
        qs = [self._q(cfg.label, True)]
        sess = _make_session(qs, [cfg], 30)
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", sess["ts"])

    def test_all_correct(self):
        cfg = OpConfig("Addition")
        qs = [self._q(cfg.label, True) for _ in range(5)]
        sess = _make_session(qs, [cfg], 30)
        assert sess["correct"] == 5
        assert sess["total"] == 5

    def test_all_wrong(self):
        cfg = OpConfig("Addition")
        qs = [self._q(cfg.label, False) for _ in range(3)]
        sess = _make_session(qs, [cfg], 30)
        assert sess["correct"] == 0


# ===========================================================================
# _build_rows
# ===========================================================================


class TestBuildRows:
    def _keys(self, rows):
        return [r[4] for r in rows]

    def test_addition_rows(self):
        rows = _build_rows("Addition", 2, 0, 2, 12)
        keys = self._keys(rows)
        assert "digits" in keys
        assert "decimals" in keys
        assert "op2_lo" not in keys
        assert "op2_hi" not in keys
        assert "allow_neg" not in keys

    def test_subtraction_rows_includes_allow_neg(self):
        rows = _build_rows("Subtraction", 2, 0, 2, 12, allow_neg=0)
        keys = self._keys(rows)
        assert "digits" in keys
        assert "decimals" in keys
        assert "allow_neg" in keys

    def test_multiplication_rows(self):
        rows = _build_rows("Multiplication", 2, 0, 3, 9)
        keys = self._keys(rows)
        assert "op2_lo" in keys
        assert "op2_hi" in keys
        assert "decimals" in keys
        assert "digits" not in keys
        assert "allow_neg" not in keys

    def test_division_rows(self):
        rows = _build_rows("Division", 2, 0, 2, 12)
        keys = self._keys(rows)
        assert "op2_lo" in keys
        assert "op2_hi" in keys
        assert "decimals" in keys
        assert "digits" not in keys

    def test_row_values(self):
        rows = _build_rows("Addition", digits=3, decimals=1, op2_lo=2, op2_hi=12)
        row_dict = {r[4]: r for r in rows}
        label, val, mn, mx, key = row_dict["digits"]
        assert val == 3
        assert mn == 1
        assert mx == 4

    def test_decimals_row_bounds(self):
        rows = _build_rows("Addition", 2, 0, 2, 12)
        row_dict = {r[4]: r for r in rows}
        _, val, mn, mx, _ = row_dict["decimals"]
        assert mn == 0
        assert mx == 3

    def test_multiplication_range_bounds(self):
        rows = _build_rows("Multiplication", 2, 0, op2_lo=5, op2_hi=15)
        row_dict = {r[4]: r for r in rows}
        _, lo_val, lo_min, lo_max, _ = row_dict["op2_lo"]
        assert lo_val == 5
        assert lo_min == 1
        assert lo_max == 15  # capped by op2_hi

    def test_division_divisor_min_is_2(self):
        rows = _build_rows("Division", 2, 0, op2_lo=3, op2_hi=9)
        row_dict = {r[4]: r for r in rows}
        _, _, mn, _, _ = row_dict["op2_lo"]
        assert mn == 2


# ===========================================================================
# _q_line
# ===========================================================================


class TestQLine:
    def test_correct_question_no_user_answer(self):
        q = Question("5 + 3", 8.0, 0, user_answer="8")
        q.correct = True
        line = _q_line(q)
        assert line.startswith("[+]")
        assert "5 + 3" in line
        assert "8" in line
        assert "you:" not in line

    def test_wrong_question_shows_user_answer(self):
        q = Question("5 + 3", 8.0, 0, user_answer="9")
        q.correct = False
        line = _q_line(q)
        assert line.startswith("[-]")
        assert "5 + 3" in line
        assert "8" in line
        assert "you: 9" in line

    def test_decimal_answer_str(self):
        q = Question("1.5 + 1.5", 3.0, 1, user_answer="3.0")
        q.correct = True
        line = _q_line(q)
        assert "3.0" in line

    def test_negative_answer(self):
        q = Question("3 - 7", -4.0, 0, user_answer="-4")
        q.correct = True
        line = _q_line(q)
        assert "[+]" in line
        assert "-4" in line


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
# Game._process_voice_events
# ===========================================================================


class TestGameVoiceEvents:
    def _make_game(self):
        from unittest.mock import MagicMock

        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        cfg = OpConfig("Addition", digits=1, decimals=0)
        return Game(stdscr, [cfg], 60)

    def test_no_listener_returns_false(self):
        g = self._make_game()
        g.voice_listener = None
        assert g._process_voice_events() is False

    def test_returns_true_when_events_processed(self):
        from unittest.mock import MagicMock

        g = self._make_game()
        listener = MagicMock()
        listener.error = None
        listener.get_nowait.side_effect = [("partial", "4"), None]
        g.voice_listener = listener
        assert g._process_voice_events() is True

    def test_returns_false_when_queue_empty(self):
        from unittest.mock import MagicMock

        g = self._make_game()
        listener = MagicMock()
        listener.error = None
        listener.get_nowait.return_value = None
        g.voice_listener = listener
        assert g._process_voice_events() is False

    def test_no_listener_is_noop(self):
        g = self._make_game()
        g.voice_listener = None
        g._process_voice_events()  # must not raise

    def test_final_number_sets_buf(self):
        from unittest.mock import MagicMock

        g = self._make_game()
        listener = MagicMock()
        listener.error = None
        listener.get_nowait.side_effect = [("final", "42"), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == "42"
        assert g.voice_partial == ""

    def test_partial_sets_voice_partial(self):
        from unittest.mock import MagicMock

        g = self._make_game()
        listener = MagicMock()
        listener.error = None
        listener.get_nowait.side_effect = [("partial", "40"), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.voice_partial == "40"
        assert g.buf == ""

    def test_enter_submits_buffer(self):
        from unittest.mock import MagicMock

        g = self._make_game()
        g.buf = "8"
        listener = MagicMock()
        listener.error = None
        listener.get_nowait.side_effect = [("enter", ""), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == ""
        assert len(g.questions) == 1

    def test_enter_ignored_when_buf_empty(self):
        from unittest.mock import MagicMock

        g = self._make_game()
        g.buf = ""
        g.voice_partial = ""
        listener = MagicMock()
        listener.error = None
        listener.get_nowait.side_effect = [("enter", ""), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert len(g.questions) == 0

    def test_enter_clears_voice_partial(self):
        from unittest.mock import MagicMock

        g = self._make_game()
        g.buf = "5"
        g.voice_partial = "5"
        listener = MagicMock()
        listener.error = None
        listener.get_nowait.side_effect = [("enter", ""), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.voice_partial == ""

    def test_slow_speech_combines_finals(self):
        """Two separate finals ('forty' then 'two') should combine to '42'."""
        from unittest.mock import MagicMock

        g = self._make_game()
        listener = MagicMock()
        listener.error = None
        listener.get_nowait.side_effect = [("final", "40"), None]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == "40"

        listener.get_nowait.side_effect = [("final", "2"), None]
        g._process_voice_events()
        assert g.buf == "42"

    def test_enter_commits_pending_partial(self):
        """Enter should commit voice_partial into buf before submitting."""
        from unittest.mock import MagicMock

        g = self._make_game()
        g.buf = "40"
        g.voice_partial = "2"
        listener = MagicMock()
        listener.error = None
        listener.get_nowait.side_effect = [("enter", ""), None]
        g.voice_listener = listener
        g._process_voice_events()
        # Submitted answer should be '42', not '40'
        assert len(g.questions) == 1
        assert g.questions[0].user_answer == "42"
        assert g.voice_partial == ""

    def test_multiple_events_in_order(self):
        from unittest.mock import MagicMock

        g = self._make_game()
        listener = MagicMock()
        listener.error = None
        listener.get_nowait.side_effect = [
            ("partial", "4"),
            ("final", "42"),
            None,
        ]
        g.voice_listener = listener
        g._process_voice_events()
        assert g.buf == "42"
        assert g.voice_partial == ""

    def test_thread_error_clears_listener_and_stores_message(self):
        """If the voice thread crashes, _process_voice_events detects it and
        moves the error message into _voice_error so the UI can display it."""
        from unittest.mock import MagicMock

        g = self._make_game()
        listener = MagicMock()
        listener.error = "Microphone disconnected"
        listener.get_nowait.return_value = None
        g.voice_listener = listener
        result = g._process_voice_events()
        assert g.voice_listener is None
        assert g._voice_error == "Microphone disconnected"
        assert result is False

    def test_thread_error_not_triggered_when_no_error(self):
        """A healthy listener (error=None) must not be cleared."""
        from unittest.mock import MagicMock

        g = self._make_game()
        listener = MagicMock()
        listener.error = None  # explicitly None — MagicMock auto-attrs are truthy
        listener.get_nowait.return_value = None
        g.voice_listener = listener
        g._process_voice_events()
        assert g.voice_listener is listener


# ===========================================================================
# Game._handle_backspace
# ===========================================================================


class TestGameHandleBackspace:
    def _make_game(self):
        from unittest.mock import MagicMock

        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        cfg = OpConfig("Addition", digits=1, decimals=0)
        return Game(stdscr, [cfg], 60)

    def test_keyboard_mode_removes_last_char(self):
        g = self._make_game()
        g.buf = "42"
        g.voice_listener = None
        g._handle_backspace()
        assert g.buf == "4"
        assert g.voice_partial == ""

    def test_keyboard_mode_on_empty_buf_is_noop(self):
        g = self._make_game()
        g.buf = ""
        g.voice_listener = None
        g._handle_backspace()
        assert g.buf == ""

    def test_voice_mode_clears_buf_and_partial(self):
        """In voice mode the whole buffer is cleared, not just the last char."""
        from unittest.mock import MagicMock

        g = self._make_game()
        g.buf = "42"
        g.voice_partial = "5"
        listener = MagicMock()
        listener.error = None
        g.voice_listener = listener
        g._handle_backspace()
        assert g.buf == ""
        assert g.voice_partial == ""

    def test_voice_mode_clears_partial_only_when_buf_empty(self):
        from unittest.mock import MagicMock

        g = self._make_game()
        g.buf = ""
        g.voice_partial = "40"
        listener = MagicMock()
        listener.error = None
        g.voice_listener = listener
        g._handle_backspace()
        assert g.buf == ""
        assert g.voice_partial == ""


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
        # First combined partial just shows the number as a partial.
        # Only the second consecutive partial with the same number fires.
        listener = self._listener()
        listener._emit_text("forty enter", final=False)
        assert listener.get_nowait() == ("partial", "40")
        assert listener.get_nowait() is None
        listener._emit_text("forty enter", final=False)
        assert listener.get_nowait() == ("final", "40")
        assert listener.get_nowait() == ("enter", "")
        assert listener.get_nowait() is None

    def test_combined_partial_refines_before_firing(self):
        # If vosk refines "forty enter" → "forty two enter", the first value
        # ("forty") is discarded and only the stable "forty two" fires.
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
