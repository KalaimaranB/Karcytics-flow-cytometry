"""Available Channels / autofill regression coverage for SpectralViewer.

Guards against the bug where the channel list stayed empty whenever no
sample had been individually "opened" elsewhere in the UI (`view.
current_sample_id` unset) — `_refresh_sources` must build the list from
every loaded sample in the experiment, not just a single "current" one, and
`_autofill_from_samples` must then plot every detected channel automatically.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from karcytics_plugins.flow_cytometry.analysis.experiment import Experiment, Sample  # noqa: E402
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData  # noqa: E402
from karcytics_plugins.flow_cytometry.analysis.state import FlowState  # noqa: E402
from karcytics_plugins.flow_cytometry.ui.widgets import spectral_viewer as _sv_mod  # noqa: E402
from karcytics_plugins.flow_cytometry.ui.widgets.spectral_viewer import SpectralViewer  # noqa: E402

# conftest's DummyColors returns "#000000" for *any* attribute via a metaclass
# __getattr__ fallback — that shadows CHART_COLORS's real list-of-hex-strings
# shape in production, so pin a real class attribute on the exact `Colors`
# object spectral_viewer.py itself resolved at import time.
_sv_mod.Colors.CHART_COLORS = ["#58a6ff", "#3fb950", "#d29922"]

_CHANNELS = ["FSC-A", "SSC-A", "FITC-A", "PE-A", "APC-A", "Time"]
_MARKERS = ["", "", "B220", "CD4", "CD45", ""]


def _make_state_with_samples(n: int) -> FlowState:
    state = FlowState()
    state.data.experiment = Experiment()
    for i in range(n):
        sample = Sample(sample_id=f"s{i}", display_name=f"Sample {i}")
        sample.fcs_data = FCSData(
            file_path=Path(f"sample_{i}.fcs"), channels=list(_CHANNELS), markers=list(_MARKERS)
        )
        state.data.experiment.samples[sample.sample_id] = sample
    return state


def _fake_fluor_service():
    service = MagicMock()
    service.get_spectrum.return_value = {
        "em_data": [[500, 0.1], [520, 1.0], [540, 0.2]],
        "ex_data": [[450, 0.1], [488, 1.0], [500, 0.2]],
        "ab_data": [[450, 1.0]],
        "color": "#58a6ff",
        "qy": None,
        "ext_coeff": None,
    }
    return service


def test_refresh_sources_populates_without_a_current_sample():
    state = _make_state_with_samples(2)
    assert state.view.current_sample_id is None  # no sample individually "opened"

    viewer = SpectralViewer(state=state, fluor_service=_fake_fluor_service())
    viewer._refresh_sources()

    labels = [viewer._source_list.item(i).text() for i in range(viewer._source_list.count())]
    assert any("B220" in label for label in labels)
    assert any("CD4" in label for label in labels)
    assert any("CD45" in label for label in labels)
    # FSC/SSC/Time are excluded, and duplicates across the two samples are deduped
    assert viewer._source_list.count() == 3  # noqa: PLR2004


def test_refresh_sources_empty_experiment_stays_empty():
    state = FlowState()
    state.data.experiment = Experiment()
    viewer = SpectralViewer(state=state, fluor_service=_fake_fluor_service())
    viewer._refresh_sources()
    assert viewer._source_list.count() == 0


def test_autofill_plots_every_detected_channel_once():
    state = _make_state_with_samples(1)
    viewer = SpectralViewer(state=state, fluor_service=_fake_fluor_service())

    viewer._refresh_sources()
    assert not viewer._active_fluors
    viewer._autofill_from_samples()

    while getattr(viewer, "_autofill_timer", None) and viewer._autofill_timer.isActive():
        viewer._autofill_next()

    assert len(viewer._active_fluors) == 3  # noqa: PLR2004
    assert viewer._autofilled is True

    # A later manual removal shouldn't be silently undone by a second showEvent.
    first_query = next(iter(viewer._active_fluors))
    viewer._active_fluors.pop(first_query)
    viewer._refresh_sources()
    viewer._autofill_from_samples()

    while getattr(viewer, "_autofill_timer", None) and viewer._autofill_timer.isActive():
        viewer._autofill_next()

    assert len(viewer._active_fluors) == 2  # noqa: PLR2004
