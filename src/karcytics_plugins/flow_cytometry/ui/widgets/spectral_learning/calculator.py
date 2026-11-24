"""The deck's 🧮 calculator: type arithmetic, see the result.

Only numbers, + − × ÷, brackets and a trailing % ("20%" is 0.2) are allowed.
The expression is parsed into a syntax tree and only those nodes are
evaluated, so nothing typed here can run code.
"""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable

from karcytics_sdk.plugin.components import BioLineEdit
from karcytics_sdk.plugin.theme_fallback import theme_manager
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

MAX_LENGTH = 80  # characters: room for any sum the deck asks for
_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_SPELLINGS = (("×", "*"), ("x", "*"), ("X", "*"), ("÷", "/"), ("−", "-"), (",", ""))


def evaluate(expression: str) -> float | None:
    """The value of an arithmetic expression; None if it isn't one (or divides by zero)."""
    text = expression.strip()
    if not text or len(text) > MAX_LENGTH:
        return None
    for typed, python in _SPELLINGS:
        text = text.replace(typed, python)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", text)
    try:
        tree = ast.parse(text, mode="eval")
        return _value(tree.body)
    except (SyntaxError, ValueError, ZeroDivisionError):
        return None


def _value(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        if isinstance(node.value, bool):
            raise ValueError("not a number")
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        sign = -1.0 if isinstance(node.op, ast.USub) else 1.0
        return sign * _value(node.operand)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_value(node.left), _value(node.right))
    raise ValueError(f"not arithmetic: {ast.dump(node)}")


def format_result(value: float) -> str:
    """A result as people write it: no trailing zeros, at most 3 decimals."""
    rounded = round(value, 3)
    return f"{rounded:,.3f}".rstrip("0").rstrip(".")


class Calculator(QWidget):
    """🧮 a one-line calculator: the result updates as you type."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LearningCalculator")
        self.input = BioLineEdit()
        self.input.setPlaceholderText("🧮 Calculator: e.g. 750 × 20%  or  190 ÷ 950")
        self.input.setMaxLength(MAX_LENGTH)
        self.input.textChanged.connect(self._update)
        self.result = QLabel("")
        self.result.setMinimumWidth(90)
        theme_manager.apply_style(
            self.result, "color: {ACCENT_WARNING}; font-family: monospace; font-weight: bold;"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.input, stretch=1)
        row.addWidget(self.result)

    def _update(self, text: str) -> None:
        value = evaluate(text)
        if value is not None:
            self.result.setText(f"= {format_result(value)}")
        else:
            self.result.setText("" if not text.strip() else "= ?")
