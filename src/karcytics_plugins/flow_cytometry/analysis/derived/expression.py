"""Safe per-event formula language for derived parameters.

A formula is ordinary arithmetic over channel references written in square
brackets, e.g. ``[FITC-A] / [APC-A]`` or ``log10([PE-A] + 1)``. It is parsed
with :mod:`ast` and checked against a strict whitelist — numbers, channel
references, ``+ - * / ^ **``, unary minus, parentheses and a handful of
numpy functions — then compiled to a closure tree. User text never reaches
``eval``/``pd.eval``, so a formula cannot import, call arbitrary functions
or touch attributes.

Evaluation is fully vectorized, runs in float64 and never raises on bad
arithmetic: division by zero, log of non-positive values and overflow all
produce NaN for that event (±inf is folded to NaN too). NaN fails every gate
comparison and is dropped by the statistics layer, so an invalid event simply
falls outside anything drawn on the derived axis.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

MAX_FORMULA_LENGTH = 500
MAX_CHANNEL_REFS = 50
MAX_NESTING_DEPTH = 32

_REF_PATTERN = re.compile(r"\[([^\[\]]*)\]")

Evaluator = Callable[[pd.DataFrame], np.ndarray]

# Function whitelist: name -> (numpy callable, arity)
_FUNCTIONS: dict[str, tuple[Callable[..., np.ndarray], int]] = {
    "log10": (np.log10, 1),
    "ln": (np.log, 1),
    "log2": (np.log2, 1),
    "exp": (np.exp, 1),
    "sqrt": (np.sqrt, 1),
    "abs": (np.abs, 1),
    "asinh": (np.arcsinh, 1),
    "min": (np.minimum, 2),
    "max": (np.maximum, 2),
}

_FUNCTION_HINTS = {
    "log": "Ambiguous function 'log' — use log10(...) or ln(...)",
    "arcsinh": "Use asinh(...) for the inverse hyperbolic sine",
}


class FormulaError(ValueError):
    """A formula failed to parse or validate.

    Attributes:
        message:  Human-readable reason, suitable for inline UI display.
        position: 0-based character offset of the problem in the formula
                  text, or None when it applies to the whole formula.
    """

    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.position = position


@dataclass(frozen=True)
class ChannelRef:
    """One ``[channel]`` reference and its span in the formula text."""

    name: str
    start: int
    end: int


@dataclass(frozen=True)
class DerivedExpression:
    """A parsed, validated formula ready for evaluation.

    Build with :func:`parse_formula`; never construct directly.
    """

    text: str
    refs: tuple[ChannelRef, ...]
    has_division: bool
    _evaluator: Callable[[pd.DataFrame, bool], np.ndarray]

    @property
    def channels(self) -> tuple[str, ...]:
        """Distinct referenced channel names in first-use order."""
        return tuple(dict.fromkeys(r.name for r in self.refs))

    def missing_channels(self, columns) -> list[str]:
        """Return referenced channels absent from ``columns``."""
        present = set(columns)
        return [ch for ch in self.channels if ch not in present]

    def evaluate(self, events: pd.DataFrame, *, positive_denominators: bool = True) -> np.ndarray:
        """Compute the formula for every event.

        Args:
            events: Event table containing every referenced channel.
            positive_denominators: When True, any division whose
                denominator is zero or negative yields NaN for that event
                instead of a sign-flipped or exploding ratio.

        Returns:
            float64 array of length ``len(events)``; invalid events are NaN.

        Raises:
            KeyError: If a referenced channel is missing from ``events``.
        """
        missing = self.missing_channels(events.columns)
        if missing:
            raise KeyError(missing[0])
        with np.errstate(all="ignore"):
            out = np.asarray(self._evaluator(events, positive_denominators), dtype=np.float64)
            if out.ndim == 0:
                out = np.full(len(events), float(out), dtype=np.float64)
            else:
                out = out.copy()
        out[~np.isfinite(out)] = np.nan
        return out

    def with_renamed_channels(self, mapping: dict[str, str]) -> str:
        """Return the formula text with channel references renamed."""
        parts: list[str] = []
        cursor = 0
        for ref in self.refs:
            parts.append(self.text[cursor : ref.start])
            parts.append(f"[{mapping.get(ref.name, ref.name)}]")
            cursor = ref.end
        parts.append(self.text[cursor:])
        return "".join(parts)


def extract_channel_refs(text: str) -> list[ChannelRef]:
    """Return every ``[channel]`` reference in ``text`` (no validation)."""
    return [ChannelRef(m.group(1).strip(), m.start(), m.end()) for m in _REF_PATTERN.finditer(text)]


def parse_formula(text: str) -> DerivedExpression:
    """Parse and validate a derived-parameter formula.

    Raises:
        FormulaError: With a user-facing message and, where possible, the
            character position of the problem.
    """
    if not text or not text.strip():
        raise FormulaError("Formula is empty")
    if len(text) > MAX_FORMULA_LENGTH:
        raise FormulaError(f"Formula is too long (max {MAX_FORMULA_LENGTH} characters)")

    refs = extract_channel_refs(text)
    if not refs:
        raise FormulaError("Formula must reference at least one channel, e.g. [FITC-A]")
    if len(refs) > MAX_CHANNEL_REFS:
        raise FormulaError(f"Too many channel references (max {MAX_CHANNEL_REFS})")
    for ref in refs:
        if not ref.name:
            raise FormulaError("Empty channel reference []", ref.start)

    # Swap each [ref] for a same-length identifier so AST column offsets
    # still point at the right character of the user's text.
    placeholders: dict[str, str] = {}
    chars = list(text)
    for i, ref in enumerate(refs):
        width = ref.end - ref.start
        ident = f"_{i}".ljust(width, "_")
        placeholders[ident] = ref.name
        chars[ref.start : ref.end] = list(ident)
    source = "".join(chars)

    stray = re.search(r"[\[\]#\n\r]", source)
    if stray:
        what = "Unbalanced '[' or ']'" if stray.group() in "[]" else "Unexpected character"
        raise FormulaError(what, stray.start())

    # Parenthesize so leading whitespace is legal; every AST offset is then
    # one past the user's character, which _pos() corrects for.
    try:
        tree = ast.parse(f"({source})", mode="eval")
    except SyntaxError as exc:
        pos = max(0, min(exc.offset - 2, len(text) - 1)) if exc.offset else None
        raise FormulaError("Syntax error", pos) from None

    compiler = _Compiler(placeholders)
    evaluator = compiler.compile(tree.body, depth=0)
    return DerivedExpression(
        text=text,
        refs=tuple(refs),
        has_division=compiler.has_division,
        _evaluator=evaluator,
    )


_Node = Callable[[pd.DataFrame, bool], np.ndarray]


class _Compiler:
    """Whitelisting AST -> closure compiler."""

    def __init__(self, placeholders: dict[str, str]) -> None:
        self._placeholders = placeholders
        self.has_division = False

    def compile(self, node: ast.AST, depth: int) -> _Node:  # noqa: PLR0911
        if depth > MAX_NESTING_DEPTH:
            raise FormulaError("Formula is nested too deeply", _pos(node))

        if isinstance(node, ast.Constant):
            return self._constant(node)
        if isinstance(node, ast.Name):
            return self._name(node)
        if isinstance(node, ast.UnaryOp):
            return self._unary(node, depth)
        if isinstance(node, ast.BinOp):
            return self._binary(node, depth)
        if isinstance(node, ast.Call):
            return self._call(node, depth)
        raise FormulaError(f"'{_describe(node)}' is not allowed in a formula", _pos(node))

    @staticmethod
    def _constant(node: ast.Constant) -> _Node:
        value = node.value
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise FormulaError("Only numbers are allowed as constants", _pos(node))
        const = float(value)
        return lambda _df, _pd: np.asarray(const, dtype=np.float64)

    def _name(self, node: ast.Name) -> _Node:
        channel = self._placeholders.get(node.id)
        if channel is None:
            if node.id in _FUNCTIONS:
                raise FormulaError(f"'{node.id}' is a function — use {node.id}(...)", _pos(node))
            if re.fullmatch(r"_\d+_*_\d+_*", node.id):
                raise FormulaError("Missing operator between two channels", _pos(node))
            raise FormulaError(
                f"Unknown name '{node.id}' — wrap channels in brackets, e.g. [{node.id}]",
                _pos(node),
            )
        return lambda df, _pd: df[channel].to_numpy(dtype=np.float64, copy=False)

    def _unary(self, node: ast.UnaryOp, depth: int) -> _Node:
        operand = self.compile(node.operand, depth + 1)
        if isinstance(node.op, ast.USub):
            return lambda df, pd_: np.negative(operand(df, pd_))
        if isinstance(node.op, ast.UAdd):
            return operand
        raise FormulaError("Only unary + and - are allowed", _pos(node))

    def _binary(self, node: ast.BinOp, depth: int) -> _Node:
        left = self.compile(node.left, depth + 1)
        right = self.compile(node.right, depth + 1)
        op = node.op
        if isinstance(op, ast.Add):
            return lambda df, pd_: np.add(left(df, pd_), right(df, pd_))
        if isinstance(op, ast.Sub):
            return lambda df, pd_: np.subtract(left(df, pd_), right(df, pd_))
        if isinstance(op, ast.Mult):
            return lambda df, pd_: np.multiply(left(df, pd_), right(df, pd_))
        if isinstance(op, ast.Div):
            self.has_division = True
            return _divide(left, right)
        if isinstance(op, ast.Pow | ast.BitXor):  # '^' reads as power to scientists
            return lambda df, pd_: np.power(left(df, pd_), right(df, pd_))
        raise FormulaError(f"Operator '{_describe(op)}' is not allowed", _pos(node))

    def _call(self, node: ast.Call, depth: int) -> _Node:
        if not isinstance(node.func, ast.Name):
            raise FormulaError("Only plain function calls like sqrt(...) are allowed", _pos(node))
        name = node.func.id
        if name not in _FUNCTIONS:
            hint = _FUNCTION_HINTS.get(name)
            allowed = ", ".join(sorted(_FUNCTIONS))
            raise FormulaError(
                hint or f"Unknown function '{name}' (allowed: {allowed})", _pos(node)
            )
        if node.keywords:
            raise FormulaError(f"{name}() does not take keyword arguments", _pos(node))
        fn, arity = _FUNCTIONS[name]
        if len(node.args) != arity:
            plural = "s" if arity != 1 else ""
            raise FormulaError(f"{name}() takes {arity} argument{plural}", _pos(node))
        args = [self.compile(a, depth + 1) for a in node.args]
        if arity == 1:
            (a0,) = args
            return lambda df, pd_: fn(a0(df, pd_))
        a0, a1 = args
        return lambda df, pd_: fn(a0(df, pd_), a1(df, pd_))


def _divide(left: _Node, right: _Node) -> _Node:
    def _div(df: pd.DataFrame, positive_denominators: bool) -> np.ndarray:
        num = left(df, positive_denominators)
        den = right(df, positive_denominators)
        result = np.divide(num, den)
        if positive_denominators:
            result = np.where(np.asarray(den) > 0, result, np.nan)
        return result

    return _div


def _pos(node: ast.AST) -> int | None:
    offset = getattr(node, "col_offset", None)
    return None if offset is None else max(0, offset - 1)


def _describe(node: ast.AST) -> str:
    return {
        "Attribute": "attribute access",
        "Subscript": "indexing",
        "Compare": "comparison",
        "BoolOp": "and/or",
        "Lambda": "lambda",
        "IfExp": "if/else",
        "List": "list",
        "Tuple": "tuple",
        "Dict": "dict",
        "Set": "set",
        "ListComp": "comprehension",
        "GeneratorExp": "generator",
        "Mod": "%",
        "FloorDiv": "//",
        "MatMult": "@",
        "BitAnd": "&",
        "BitOr": "|",
        "LShift": "<<",
        "RShift": ">>",
    }.get(type(node).__name__, type(node).__name__)
