"""Tests for the derived-parameter formula language (parse + evaluate)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.derived.expression import (
    MAX_FORMULA_LENGTH,
    MAX_NESTING_DEPTH,
    FormulaError,
    parse_formula,
)


@pytest.fixture
def events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "FITC-A": [10.0, 0.0, -5.0, 4.0, 8.0],
            "APC-A": [2.0, 0.0, 5.0, -4.0, 4.0],
            "PE-A": [1.0, 10.0, 100.0, 1000.0, 0.0],
        }
    )


class TestEvaluate:
    def test_ratio_with_positive_denominators(self, events):
        out = parse_formula("[FITC-A] / [APC-A]").evaluate(events)
        np.testing.assert_array_equal(out, [5.0, np.nan, -1.0, np.nan, 2.0])

    def test_ratio_permissive_keeps_negative_denominators(self, events):
        out = parse_formula("[FITC-A] / [APC-A]").evaluate(events, positive_denominators=False)
        # 0/0 -> NaN; 4/-4 -> -1 is kept when the policy is off
        np.testing.assert_array_equal(out, [5.0, np.nan, -1.0, -1.0, 2.0])

    def test_log_of_non_positive_is_nan_not_inf(self, events):
        out = parse_formula("log10([PE-A])").evaluate(events)
        np.testing.assert_allclose(out[:4], [0.0, 1.0, 2.0, 3.0])
        assert np.isnan(out[4])
        assert not np.isinf(out).any()

    def test_caret_is_power(self, events):
        out = parse_formula("[APC-A]^2").evaluate(events)
        np.testing.assert_array_equal(out, [4.0, 0.0, 25.0, 16.0, 16.0])

    def test_operator_precedence_and_constants(self, events):
        out = parse_formula("-[FITC-A] + 2 * [APC-A] - 1.5").evaluate(events)
        expected = -events["FITC-A"] + 2 * events["APC-A"] - 1.5
        np.testing.assert_allclose(out, expected)

    @pytest.mark.parametrize(
        ("formula", "fn"),
        [
            ("ln([PE-A] + 1)", lambda e: np.log(e["PE-A"] + 1)),
            ("sqrt(abs([FITC-A]))", lambda e: np.sqrt(np.abs(e["FITC-A"]))),
            ("asinh([FITC-A] / 5)", lambda e: np.arcsinh(e["FITC-A"] / 5)),
            ("max([FITC-A], [APC-A])", lambda e: np.maximum(e["FITC-A"], e["APC-A"])),
            ("min([FITC-A], 0)", lambda e: np.minimum(e["FITC-A"], 0)),
        ],
    )
    def test_whitelisted_functions(self, events, formula, fn):
        np.testing.assert_allclose(parse_formula(formula).evaluate(events), fn(events))

    def test_constant_denominator_broadcasts(self, events):
        out = parse_formula("[PE-A] / 10").evaluate(events)
        np.testing.assert_allclose(out, events["PE-A"] / 10)

    def test_overflow_becomes_nan(self):
        df = pd.DataFrame({"X": [1000.0]})
        assert np.isnan(parse_formula("exp([X])").evaluate(df)[0])

    def test_result_is_float64_and_detached(self, events):
        out = parse_formula("[FITC-A]").evaluate(events)
        assert out.dtype == np.float64
        out[0] = 999.0
        assert events["FITC-A"].iloc[0] == 10.0

    def test_missing_channel_raises_keyerror(self, events):
        with pytest.raises(KeyError):
            parse_formula("[NOPE-A] / [FITC-A]").evaluate(events)

    def test_empty_frame(self):
        out = parse_formula("[A] / [B]").evaluate(pd.DataFrame({"A": [], "B": []}))
        assert len(out) == 0


class TestParse:
    def test_channels_deduplicated_in_order(self):
        expr = parse_formula("([APC-A] - [FITC-A]) / ([APC-A] + [FITC-A])")
        assert expr.channels == ("APC-A", "FITC-A")
        assert expr.has_division

    def test_channel_names_with_spaces_and_dots(self):
        df = pd.DataFrame({"PerCP-Cy5.5 A": [4.0], "Pacific Blue-A": [2.0]})
        out = parse_formula("[PerCP-Cy5.5 A] / [Pacific Blue-A]").evaluate(df)
        assert out[0] == 2.0

    def test_leading_whitespace_allowed(self):
        assert parse_formula("   [A] + 1").channels == ("A",)

    def test_rename_channels(self):
        expr = parse_formula("[B220] / [CD45]")
        assert expr.with_renamed_channels({"B220": "FITC-A"}) == "[FITC-A] / [CD45]"


class TestRejects:
    @pytest.mark.parametrize(
        "formula",
        [
            '__import__("os").system("x") + [A]',
            "[A].real",
            "[A][0]",
            "(lambda: 1)() + [A]",
            "[A] if [A] else 1",
            "[A] > 1",
            "[A] and [B]",
            "[x for x in [A]]",
            "open('f') + [A]",
            "np.log([A])",
            "[A] % 2",
            "[A] // 2",
            "[A] @ [B]",
            "'text' + [A]",
            "True + [A]",
            "1j + [A]",
            "sqrt([A], [B])",
            "max([A])",
            "sqrt(x=[A])",
            "[A] # comment",
        ],
    )
    def test_disallowed_syntax(self, formula):
        with pytest.raises(FormulaError):
            parse_formula(formula)

    def test_no_channel_reference(self):
        with pytest.raises(FormulaError, match="at least one channel"):
            parse_formula("1 / 2")

    def test_empty(self):
        with pytest.raises(FormulaError, match="empty"):
            parse_formula("   ")

    def test_too_long(self):
        with pytest.raises(FormulaError, match="too long"):
            parse_formula("[A]" + " + 1" * MAX_FORMULA_LENGTH)

    def test_too_deep(self):
        formula = "abs(" * (MAX_NESTING_DEPTH + 2) + "[A]" + ")" * (MAX_NESTING_DEPTH + 2)
        with pytest.raises(FormulaError, match="nested too deeply"):
            parse_formula(formula)

    def test_ambiguous_log_has_hint(self):
        with pytest.raises(FormulaError, match="log10"):
            parse_formula("log([A])")

    def test_bare_name_suggests_brackets(self):
        with pytest.raises(FormulaError, match=r"\[CD4\]") as info:
            parse_formula("[A] / CD4")
        assert info.value.position == 6

    def test_missing_operator_between_channels(self):
        with pytest.raises(FormulaError, match="Missing operator"):
            parse_formula("[A][B]")

    def test_empty_reference_position(self):
        with pytest.raises(FormulaError) as info:
            parse_formula("[A] + []")
        assert info.value.position == 6

    def test_unbalanced_bracket(self):
        with pytest.raises(FormulaError, match="Unbalanced"):
            parse_formula("[A] + [B")

    def test_syntax_error_position_in_range(self):
        with pytest.raises(FormulaError) as info:
            parse_formula("[A] +")
        assert info.value.position is not None
        assert 0 <= info.value.position < len("[A] +")
