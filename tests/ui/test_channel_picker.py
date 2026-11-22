"""The Comparisons tab's channel checklist: one channel or several, by plot type."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from PySide6.QtCore import Qt

from karcytics_plugins.flow_cytometry.analysis.derived.state import DerivedColumnsState
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.ui.widgets.comparisons.channel_picker import ChannelPicker
from karcytics_plugins.flow_cytometry.ui.widgets.comparisons.plot_spec import ChannelMode

pytestmark = pytest.mark.ui

RATIO = "derived:ratio"


@pytest.fixture
def fcs():
    channels = ["FSC-A", "SSC-A", "CD3", "CD4", "CD8", RATIO]
    data = FCSData(
        file_path=Path("s.fcs"),
        channels=channels,
        events=pd.DataFrame({ch: [1.0, 2.0] for ch in channels}),
    )
    data.derived = DerivedColumnsState(labels={RATIO: "CD4/CD8"})
    return data


@pytest.fixture
def picker(qtbot):
    widget = ChannelPicker()
    qtbot.addWidget(widget)
    return widget


def _listed(picker) -> list[str]:
    return [item.data(Qt.ItemDataRole.UserRole) for item in picker._items()]


def _click(picker, key: str) -> None:
    item = next(i for i in picker._items() if i.data(Qt.ItemDataRole.UserRole) == key)
    item.setCheckState(Qt.CheckState.Checked)


def test_several_channels_start_all_checked_without_scatter_or_derived(picker, fcs):
    picker.set_mode(ChannelMode.MULTI)
    picker.refresh(fcs)

    assert _listed(picker) == ["CD3", "CD4", "CD8"]
    assert picker.checked() == ["CD3", "CD4", "CD8"]
    assert picker._all_btn.isVisibleTo(picker)


def test_one_channel_mode_offers_derived_parameters_and_keeps_one_checked(picker, fcs):
    picker.set_mode(ChannelMode.SINGLE)
    picker.refresh(fcs)
    assert _listed(picker) == ["CD3", "CD4", "CD8", RATIO]
    assert picker.checked() == ["CD3"]
    assert not picker._all_btn.isVisibleTo(picker)

    _click(picker, "CD8")

    assert picker.checked() == ["CD8"]


def test_a_refresh_in_the_same_mode_keeps_the_choice(picker, fcs):
    picker.set_mode(ChannelMode.MULTI)
    picker.refresh(fcs)
    picker._none_btn.click()
    _click(picker, "CD4")

    picker.refresh(fcs)  # e.g. another sample checked

    assert picker.checked() == ["CD4"]


def test_a_new_mode_starts_from_a_clean_slate(picker, fcs):
    picker.set_mode(ChannelMode.SINGLE)
    picker.refresh(fcs)  # one channel checked: too few for a radar

    picker.set_mode(ChannelMode.MULTI)
    picker.refresh(fcs)

    assert picker.checked() == ["CD3", "CD4", "CD8"]


def test_plot_types_without_channels_hide_the_section(picker, fcs):
    picker.set_mode(ChannelMode.NONE)
    assert picker.isHidden()
