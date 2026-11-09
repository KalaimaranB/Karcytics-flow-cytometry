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


def test_auto_gating_sits_between_population_analysis_and_sample_lens():
    labels = [t.label for t in MainTab]
    i = labels.index("Auto Gating")
    assert labels[i - 1 : i + 2] == ["Population Analysis", "Auto Gating", "Sample Lens"]
    assert MainTab.restore("AUTO_GATING") is MainTab.AUTO_GATING
