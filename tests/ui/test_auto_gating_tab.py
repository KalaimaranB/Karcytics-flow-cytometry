"""The Auto Gating tab on planted samples (see tests/fixtures/lens.py), driven by the demo engine."""

import pytest
from PySide6.QtCore import Qt

from karcytics_plugins.flow_cytometry.analysis.autogate import DemoEngine
from karcytics_plugins.flow_cytometry.analysis.experiment import SampleRole
from karcytics_plugins.flow_cytometry.main_tabs import MainTab
from karcytics_plugins.flow_cytometry.ui.widgets.auto_gating import AutoGatingTab
from tests.fixtures.lens import build_lens_state


@pytest.fixture
def tab(qtbot):
    state = build_lens_state()
    state.data.experiment.samples["s3"].role = SampleRole.FMO_CONTROL
    widget = AutoGatingTab(state, DemoEngine())
    qtbot.addWidget(widget)
    widget.resize(1500, 950)
    widget.show()
    widget.refresh_samples()
    return widget


def _pick_population(tab, name):
    combo = tab._sidebar._population
    combo.setCurrentIndex(
        next(i for i in range(combo.count()) if combo.itemText(i).strip() == name)
    )


def test_the_sidebar_fills_from_the_experiment(tab):
    sidebar = tab._sidebar
    assert sidebar._group.currentText() == "Tests · 4 samples"
    assert sidebar._sample.itemText(sidebar._sample.count() - 1) == "S3"  # the control goes last
    populations = [
        sidebar._population.itemText(i).strip() for i in range(sidebar._population.count())
    ]
    assert populations[:3] == ["All Events", "Lymphocytes", "T cells"]
    assert "CD4" in sidebar.channels() and "CD8" in sidebar.channels()


def test_proposing_shows_the_split_its_reason_and_the_tree(tab):
    _pick_population(tab, "T cells")
    tab._sidebar.propose_clicked.emit()

    build = tab._build
    assert build._title.text() == "Proposed split of T cells"
    assert build._plot.has_plot() and build._reason.text()
    assert build._accept.isEnabled() and build._accept.text() == "Accept · add 2 gates"
    rows = [tab._tree._list.item(i).text() for i in range(tab._tree._list.count())]
    assert any(r.strip().startswith("CD4+ CD8−") and r.endswith("proposed") for r in rows)


def test_switching_method_keeps_a_live_proposal(tab):
    _pick_population(tab, "T cells")
    tab._sidebar.propose_clicked.emit()
    tab._sidebar.set_method("valleys")

    assert tab._proposal is not None and tab._proposal.method_key == "valleys"
    assert tab._sidebar._axes.isVisibleTo(tab._sidebar)
    assert not tab._build._next.isVisibleTo(tab._build)  # you picked the axes: no "next view"


def test_accepting_changes_nothing_while_it_is_a_preview(tab):
    _pick_population(tab, "T cells")
    tab._sidebar.propose_clicked.emit()
    sample = tab._state.data.experiment.samples["s0"]
    before = len(list(sample.gate_tree.iter_dag()))

    tab._build.accept_clicked.emit()

    assert len(list(sample.gate_tree.iter_dag())) == before
    assert tab._build._status.text().startswith("Preview only")


def test_the_group_page_skips_the_control_and_compare_lists_every_method(tab):
    _pick_population(tab, "T cells")
    tab._sidebar.propose_clicked.emit()

    table = tab._apply._table
    assert table.rowCount() == 4  # noqa: PLR2004
    assert "control" in table.item(3, table.columnCount() - 1).text()
    assert tab._compare._columns.count() == 4  # noqa: PLR2004


def test_clicking_a_population_opens_why_this_gate(tab):
    _pick_population(tab, "T cells")
    tab._sidebar.propose_clicked.emit()
    tree = tab._tree._list
    item = next(
        tree.item(i) for i in range(tree.count()) if tree.item(i).text().strip() == "T cells"
    )
    tree.itemClicked.emit(item)

    assert tab._tabs.currentIndex() == 1
    assert tab._why._title.text() == "T cells"
    assert "Lymphocytes → T cells" in [v for _k, v in tab._why._story.facts]
    assert tab._why._methods_text.text()


def test_the_elsewhere_buttons_ask_for_their_tabs(tab, qtbot):
    asked = []
    tab.open_tab_requested.connect(asked.append)
    buttons = [
        b for b in tab._tree.findChildren(type(tab._sidebar._run)) if "Sample Lens" in b.text()
    ]
    qtbot.mouseClick(buttons[0], Qt.MouseButton.LeftButton)
    assert asked == [MainTab.SAMPLE_LENS]


def test_the_tab_never_widens_the_panel(tab):
    """The centre stack is as wide as its widest page's minimum, hidden or not.

    Without its scroll area this tab demanded ~1550 px, which opened the module
    in a huge window with squeezed sidebars on every other tab.
    """
    assert tab.minimumSizeHint().width() < 300  # noqa: PLR2004
    assert tab.minimumSizeHint().height() < 300  # noqa: PLR2004
