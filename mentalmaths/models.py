from dataclasses import dataclass
from typing import Optional


@dataclass
class OpConfig:
    operation: str
    digits: int = 2
    decimals: int = 0
    operand2_lo: int = 2
    operand2_hi: int = 12
    allow_negative: bool = False  # Subtraction only

    @property
    def label(self) -> str:
        if self.operation in ("Multiplication", "Division"):
            parts = [f"{self.operand2_lo}-{self.operand2_hi}"]
        else:
            parts = [f"{self.digits}-digit"]
        if self.decimals:
            parts.append(f"{self.decimals}dp")
        if self.operation == "Subtraction" and self.allow_negative:
            parts.append("neg")
        return f"{self.operation} ({', '.join(parts)})"


@dataclass
class Question:
    display: str
    answer: float
    answer_dec: int
    op_label: str = ""
    user_answer: str = ""
    correct: Optional[bool] = None

    @property
    def answer_str(self) -> str:
        if self.answer_dec == 0:
            return str(int(round(self.answer)))
        return f"{self.answer:.{self.answer_dec}f}"
