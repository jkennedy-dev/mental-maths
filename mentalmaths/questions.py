import random

from .models import OpConfig, Question


def _rnd(lo: int, hi: int, dec: int) -> float:
    if dec == 0:
        return float(random.randint(lo, hi))
    f = 10**dec
    return round(random.randint(lo * f, (hi + 1) * f - 1) / f, dec)


def _fmt(x: float, dec: int) -> str:
    return str(int(round(x))) if dec == 0 else f"{x:.{dec}f}"


def generate_question(cfg: OpConfig) -> Question:
    op, d, dec = cfg.operation, cfg.digits, cfg.decimals
    lo = 10 ** (d - 1) if d > 1 else 1
    hi = 10**d - 1

    if op == "Addition":
        a, b = _rnd(lo, hi, dec), _rnd(lo, hi, dec)
        return Question(
            f"{_fmt(a, dec)} + {_fmt(b, dec)}", round(a + b, dec), dec, cfg.label
        )

    if op == "Subtraction":
        a, b = _rnd(lo, hi, dec), _rnd(lo, hi, dec)
        if not cfg.allow_negative and b > a:
            a, b = b, a
        return Question(
            f"{_fmt(a, dec)} - {_fmt(b, dec)}", round(a - b, dec), dec, cfg.label
        )

    if op == "Multiplication":
        a = _rnd(cfg.operand2_lo, cfg.operand2_hi, dec)
        b = _rnd(cfg.operand2_lo, cfg.operand2_hi, dec)
        return Question(
            f"{_fmt(a, dec)} x {_fmt(b, dec)}", round(a * b, dec), dec, cfg.label
        )

    # Division
    divisor = random.randint(cfg.operand2_lo, cfg.operand2_hi)
    if dec == 0:
        quotient = random.randint(cfg.operand2_lo, cfg.operand2_hi)
        return Question(
            f"{divisor * quotient} / {divisor}", float(quotient), 0, cfg.label
        )
    a = _rnd(cfg.operand2_lo, cfg.operand2_hi, dec)
    return Question(
        f"{_fmt(a, dec)} / {divisor}", round(a / divisor, dec), dec, cfg.label
    )


def check_answer(user_str: str, q: Question) -> bool:
    try:
        if q.answer_dec == 0:
            return int(round(float(user_str))) == int(round(q.answer))
        return round(float(user_str), q.answer_dec) == round(q.answer, q.answer_dec)
    except (ValueError, TypeError):
        return False
