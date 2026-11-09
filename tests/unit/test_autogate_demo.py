"""The demo engine returns what the Auto Gating tab draws, in the real engine's shape."""

import pytest

from karcytics_plugins.flow_cytometry.analysis.autogate import METHODS, DemoEngine, StepRequest
from karcytics_plugins.flow_cytometry.analysis.autogate.models import Shape

CHANNELS = ("B220 (FITC-A)", "CD4 (PE-A)", "CD3 (Pacific Blue-A)", "CD8 (APC-Cy7-A)")


def _request(method_key, **kw):
    return StepRequest(method_key=method_key, population="T cells", channels=CHANNELS, **kw)


@pytest.mark.parametrize("info", METHODS, ids=lambda m: m.key)
def test_every_method_proposes_a_named_split_with_its_reasons(info):
    proposal = DemoEngine().propose(
        _request(info.key, x_channel="CD4 (PE-A)", y_channel="CD8 (APC-Cy7-A)")
    )

    assert proposal.method_key == info.key
    assert proposal.parent == "T cells"
    names = {r.name for r in proposal.plot.regions if r.fraction >= 0.1}
    assert names == {"CD4+ CD8−", "CD4− CD8+"}
    assert proposal.view_sections and proposal.reason
    assert proposal.plot.points.shape[1] == 2
    assert (proposal.plot.points >= 0).all() and (proposal.plot.points <= 1).all()


def test_density_valleys_cut_with_a_quadrant_on_the_users_axes():
    proposal = DemoEngine().propose(
        _request("valleys", x_channel="CD3 (Pacific Blue-A)", y_channel="B220 (FITC-A)")
    )

    assert {r.shape for r in proposal.plot.regions} == {Shape.QUADRANT}
    assert proposal.plot.x_label == "CD3 (Pacific Blue-A)"
    assert "CD3+ B220−" in {r.name for r in proposal.plot.regions}


def test_the_next_best_view_highlights_another_option():
    engine = DemoEngine()
    best = engine.propose(_request("pairs"))
    second = engine.propose(_request("pairs", view_rank=1))

    assert best.view_sections[0].highlight == (0,)
    assert second.view_sections[0].highlight == (1,)
    assert second.reason.startswith("Next-best")


def test_applying_to_the_group_skips_controls_and_flags_big_moves():
    samples = (("A", False), ("B", True), ("C", False), ("D", False))
    engine = DemoEngine()

    fixed = engine.preview_group(_request("pca", samples=samples), adaptive=False)
    adaptive = engine.preview_group(_request("pca", samples=samples), adaptive=True)

    assert [r.sample for r in fixed.rows] == ["A", "B", "C", "D"]
    assert fixed.rows[1].plot is None and "control" in fixed.rows[1].status
    assert not any(r.flagged for r in fixed.rows)
    assert all(r.shift == 0 for r in fixed.rows)
    assert [r.flagged for r in adaptive.rows] == [False, False, False, True]  # the 3rd panel drifts
    assert adaptive.rows[3].plot is not None and adaptive.rows[3].plot.ghosts


def test_compare_puts_your_gates_beside_every_method():
    outcomes = DemoEngine().compare(_request("pca"))

    assert [o.label for o in outcomes] == ["Your gates", *(m.name for m in METHODS)]
    assert outcomes[0].method_key == "" and not outcomes[0].agreement
    assert all(o.agreement for o in outcomes[1:])


def test_a_gates_story_has_its_facts_and_a_methods_paragraph():
    story = DemoEngine().story("CD4+ CD8−", "T cells", _request("pca", reference="S1"))

    assert story.gate == "CD4+ CD8−"
    assert dict(story.facts)["Method"] == "PCA"
    assert dict(story.facts)["Reference sample"] == "S1"
    assert dict(story.facts)["Split"] == "T cells → CD4+ CD8−"
    assert "CD4+ CD8−" in story.methods_text and "T cells" in story.methods_text
    assert story.sections[0].signed  # PCA leads with the loadings
