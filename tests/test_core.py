"""Tests for mental-maths core logic (no curses required)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

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
