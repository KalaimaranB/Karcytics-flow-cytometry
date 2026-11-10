"""The Auto Gating tab on planted samples (see tests/fixtures/lens.py), with the real engine."""

import pytest
from PySide6.QtCore import Qt

from karcytics_plugins.flow_cytometry.analysis.autogate import GatingEngine, ProposalCommitter
from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.experiment import SampleRole
from karcytics_plugins.flow_cytometry.analysis.services.derived_parameter_service import (
    DerivedParameterService,
)
from karcytics_plugins.flow_cytometry.main_tabs import MainTab
from karcytics_plugins.flow_cytometry.ui.widgets.auto_gating import AutoGatingTab
from karcytics_plugins.flow_cytometry.ui.widgets.auto_gating.auto_gating_tab import (
    APPLY,
    COMPARE,
    WHY,
)
from tests.fixtures.lens import TreeController, build_lens_state


@pytest.fixture
def tab(qtbot):
    state = build_lens_state()
    state.data.experiment.samples["s3"].role = SampleRole.FMO_CONTROL
    committer = ProposalCommitter(TreeController(state), DerivedParameterService(state))
    widget = AutoGatingTab(state, GatingEngine(state, AxisManager(state)), committer)
    qtbot.addWidget(widget)
    widget.resize(1500, 950)
    widget.show()
    widget.refresh_samples()
    return widget


def _t_cells(tab):
    return tab._state.data.experiment.samples["s0"].gate_tree.children[0].children[0]


def _propose_on_t_cells(tab, method_key="pca"):
    sidebar = tab._sidebar
    sidebar._x_axis.setCurrentIndex(sidebar._x_axis.findData("CD4"))  # density valleys' axes
    sidebar._y_axis.setCurrentIndex(sidebar._y_axis.findData("CD8"))
    tab._sidebar.set_method(method_key)
    tab._sidebar.set_population(_t_cells(tab).node_id)
    tab._sidebar.propose_clicked.emit()


def test_the_sidebar_fills_from_the_experiment(tab):
    sidebar = tab._sidebar
    assert sidebar._group.currentText() == "Tests · 4 samples"
    assert sidebar._sample.itemText(sidebar._sample.count() - 1) == "S3"  # the control goes last
    populations = [
        sidebar._population.itemText(i).strip() for i in range(sidebar._population.count())
    ]
    assert populations[:3] == ["All Events", "Lymphocytes", "T cells"]
    assert sidebar.channels() == ("CD3", "CD4", "CD8", "CD56")  # scatter listed, unticked
    assert sidebar._channels.count() == 6  # noqa: PLR2004 - FSC-A and SSC-A too
    assert sidebar.axes() == ("FSC-A", "SSC-A")  # the usual first split
    assert sidebar.cells_first() and tab._request().cells_first  # on by default


def test_proposing_shows_the_split_its_reason_and_dashed_nodes_in_the_tree(tab):
    _propose_on_t_cells(tab)

    build = tab._build
    assert build._title.text() == "Proposed split of T cells"
    assert build._plot.has_plot() and "PC1" in build._reason.text()
    assert build._accept.isEnabled() and build._accept.text().startswith("Accept · add")
    view = tab._tree._view
    assert view._proposed and all(nid in view._node_map for nid in view._proposed)


def test_a_population_with_no_clear_split_says_why(tab):
    tab._sidebar._min_valley.setValue(0.95)
    tab._sidebar.set_method("valleys")
    tab._sidebar._x_axis.setCurrentIndex(tab._sidebar._x_axis.findData("CD3"))
    tab._sidebar._y_axis.setCurrentIndex(tab._sidebar._y_axis.findData("CD56"))
    tab._sidebar.set_population(_t_cells(tab).children[0].node_id)  # CD4+: one population
    tab._sidebar.propose_clicked.emit()

    assert tab._proposal is None
    assert not tab._build._plot.has_plot()
    assert "valley" in tab._build._plot._empty_text


def test_accepting_adds_the_gates_under_the_population(tab):
    _propose_on_t_cells(tab, "pairs")
    names = tab._proposal.plot.main_names
    before = {c.node_id for c in _t_cells(tab).children}

    tab._build.accept_clicked.emit()

    added = [c.name for c in _t_cells(tab).children if c.node_id not in before]
    assert added == list(names)
    assert tab._build._status.text().startswith("Added")
    assert not tab._tree._view._proposed  # nothing dashed any more


def test_clicking_an_accepted_gate_explains_it_and_picks_it(tab):
    _propose_on_t_cells(tab, "pairs")
    tab._build.accept_clicked.emit()
    new = _t_cells(tab).children[-1]

    tab._tree._view.node_clicked.emit(new.node_id)

    assert tab._sidebar.population()[0] == new.node_id  # split it next
    assert tab._why._title.text() == new.name
    assert "Marker-pair search" in tab._why._methods_text.text()
    tab._tree._view.node_clicked.emit(_t_cells(tab).node_id)
    assert tab._why._title.text() == "T cells: drawn by hand"


def test_the_group_and_compare_pages_fill_when_shown(tab):
    _propose_on_t_cells(tab, "valleys")
    tab._tabs.setCurrentIndex(APPLY)
    table = tab._apply._table
    assert table.rowCount() == 4  # noqa: PLR2004
    statuses = [table.item(r, table.columnCount() - 1).text() for r in range(4)]
    assert "control" in statuses[3]
    assert statuses[2].startswith("Review")  # S2's CD4 is dimmer

    tab._tabs.setCurrentIndex(COMPARE)
    assert tab._compare._columns.count() == 4  # noqa: PLR2004


def test_the_why_page_starts_empty(tab):
    tab._tabs.setCurrentIndex(WHY)
    assert "Click an auto gate" in tab._why._title.text()


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
