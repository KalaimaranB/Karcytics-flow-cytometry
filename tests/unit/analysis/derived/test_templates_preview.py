"""Formula templates and the editor's live-preview statistics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.derived import parse_formula
from karcytics_plugins.flow_cytometry.analysis.derived.preview import compute_preview
from karcytics_plugins.flow_cytometry.analysis.derived.templates import (
    TEMPLATES,
    get_template,
    short_label,
)


class TestTemplates:
    @pytest.mark.parametrize("tpl", TEMPLATES, ids=[t.key for t in TEMPLATES])
    def test_every_template_parses_and_uses_both_channels(self, tpl):
        expr = parse_formula(tpl.formula("FITC-A", "APC-A"))
        assert set(expr.channels) == {"FITC-A", "APC-A"}

    @pytest.mark.parametrize("tpl", TEMPLATES, ids=[t.key for t in TEMPLATES])
    def test_scales_are_linear_or_log(self, tpl):
        assert tpl.preferred_transform in ("linear", "log")

    def test_ratio_formula_and_name(self):
        tpl = get_template("ratio")
        assert tpl.formula("FITC-A", "APC-A") == "[FITC-A] / [APC-A]"
        assert tpl.suggested_name("B220 (FITC-A)", "CD45 (APC-A)") == "B220/CD45"

    def test_unknown_key(self):
        assert get_template("nope") is None

    @pytest.mark.parametrize(
        ("label", "short"),
        [
            ("B220 (FITC-A)", "B220"),
            ("FSC-A", "FSC-A"),
            ("PerCP-Cy5.5 (B) (PerCP-A)", "PerCP-Cy5.5 (B)"),
        ],
    )
    def test_short_label(self, label, short):
        assert short_label(label) == short

    def test_fraction_values(self):
        df = pd.DataFrame({"A": [1.0, 3.0], "B": [3.0, 1.0]})
        expr = parse_formula(get_template("fraction").formula("A", "B"))
        np.testing.assert_allclose(expr.evaluate(df), [0.25, 0.75])


class TestPreview:
    def test_median_and_invalid_share(self):
        df = pd.DataFrame({"A": [2.0, 4.0, 6.0, 1.0], "B": [1.0, 1.0, 1.0, 0.0]})
        s = compute_preview(
            parse_formula("[A] / [B]"), df, positive_denominators=True, log_scale=False
        )
        assert s.n_events == 4
        assert s.n_valid == 3
        assert s.pct_invalid == pytest.approx(25.0)
        assert s.median == pytest.approx(4.0)
        assert s.counts.sum() == 3
        assert len(s.edges) == len(s.counts) + 1

    def test_log_scale_drops_non_positive_from_histogram_only(self):
        df = pd.DataFrame({"A": [-1.0, 0.0, 10.0, 100.0]})
        s = compute_preview(parse_formula("[A]"), df, positive_denominators=True, log_scale=True)
        assert s.n_valid == 4
        assert s.n_plotted == 2
        assert s.counts.sum() == 2
        assert s.edges[0] > 0

    def test_subsamples_large_populations(self):
        df = pd.DataFrame({"A": np.arange(1, 50_001, dtype=float)})
        s = compute_preview(
            parse_formula("[A]"), df, positive_denominators=True, log_scale=False, max_events=5_000
        )
        assert 4_000 < s.n_events < 6_000

    def test_all_invalid(self):
        df = pd.DataFrame({"A": [1.0, 2.0], "B": [0.0, -1.0]})
        s = compute_preview(
            parse_formula("[A] / [B]"), df, positive_denominators=True, log_scale=False
        )
        assert s.median is None
        assert len(s.counts) == 0
        assert s.pct_invalid == 100.0

    def test_constant_values_still_bin(self):
        df = pd.DataFrame({"A": [5.0] * 10})
        s = compute_preview(parse_formula("[A]"), df, positive_denominators=True, log_scale=True)
        assert s.counts.sum() == 10

    def test_missing_channel_raises(self):
        with pytest.raises(KeyError):
            compute_preview(
                parse_formula("[Z]"),
                pd.DataFrame({"A": [1.0]}),
                positive_denominators=True,
                log_scale=False,
            )
