"""The main tab order and how a saved tab is read back."""

from karcytics_plugins.flow_cytometry.main_tabs import MainTab


def test_the_last_three_tabs_follow_the_workflow():
    assert [t.label for t in MainTab][-3:] == ["Sample Lens", "Statistics", "Comparisons"]


def test_a_saved_name_restores_its_tab():
    assert MainTab.restore("SAMPLE_LENS") is MainTab.SAMPLE_LENS
    assert MainTab.restore("NOPE") is None


def test_a_saved_index_is_read_in_the_old_order():
    assert MainTab.restore(4) is MainTab.STATISTICS
    assert MainTab.restore(8) is MainTab.SAMPLE_LENS
    assert MainTab.restore(1) is MainTab.GATING
    assert MainTab.restore(9) is None
