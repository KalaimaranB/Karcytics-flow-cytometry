"""End-to-end coverage for every registered Comparisons plot type.

This is the regression test for a real bug: a plot type ("Pseudocolor
Overlay") got added to ``PLOT_REGISTRY`` without a matching kwargs-building
branch, so selecting it and clicking Generate crashed with a raw
``KeyError`` — no validation caught it because nothing forced the branch to
exist. ``PlotTypeSpec`` (plot_spec.py) makes a missing builder a
registration-time dataclass error instead, and this test parametrizes over
*every* entry in ``PLOT_REGISTRY`` so a future plot type gets the same
"does it actually render" coverage automatically, without editing this file.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData
from karcytics_plugins.flow_cytometry.analysis.gating import RectangleGate
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from karcytics_plugins.flow_cytometry.ui.widgets.comparisons.plot_spec import (
    ChannelMode,
    SampleMode,
)
from karcytics_plugins.flow_cytometry.ui.widgets.comparisons.registry import PLOT_REGISTRY
from karcytics_plugins.flow_cytometry.ui.widgets.comparisons_viewer import Colors, ComparisonsViewer

# conftest's DummyColors returns "#000000" for *any* attribute via a metaclass
# __getattr__ fallback — that shadows CHART_COLORS's real list-of-hex-strings
# shape in production (see test_spectral_viewer_autofill.py for the same fix),
# so pin a real class attribute on the exact `Colors` object comparisons_viewer.py
# itself resolved at import time before _on_generate() injects it as "palette".
Colors.CHART_COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#a371f7", "#f778ba"]

_CHANNELS = ["FSC-A", "SSC-A", "CD3", "CD4", "CD8"]


def _make_sample(sample_id: str, seed: int) -> Sample:
    rng = np.random.default_rng(seed)
    n = 400
    events = pd.DataFrame({ch: rng.uniform(0, 100_000, n) for ch in _CHANNELS})
    fcs_data = FCSData(file_path=Path(f"{sample_id}.fcs"), channels=_CHANNELS, events=events)
    sample = Sample(sample_id=sample_id, display_name=sample_id, fcs_data=fcs_data)
    gate = RectangleGate("FSC-A", "SSC-A", x_min=10_000, x_max=90_000, y_min=10_000, y_max=90_000)
    sample.gate_tree.add_child(gate, name="Lymphocytes")
    return sample


@pytest.fixture
def two_sample_state() -> FlowState:
    """Two samples, each with FSC-A/SSC-A/CD3/CD4/CD8 and a shared 'Lymphocytes' gate."""
    state = FlowState()
    for i, sid in enumerate(("s1", "s2")):
        state.data.experiment.samples[sid] = _make_sample(sid, seed=i)
    return state


@pytest.mark.unit
def test_every_registry_entry_has_a_complete_spec():
    """PlotTypeSpec's dataclass fields being required is the structural fix:
    a plot type literally cannot be registered without every field —
    including build_kwargs — being supplied.
    """
    assert len(PLOT_REGISTRY) >= 5  # noqa: PLR2004
    for name, spec in PLOT_REGISTRY.items():
        assert callable(spec.build_kwargs), f"{name} has no kwargs builder"
        assert spec.renderer_cls is not None, f"{name} has no renderer"
        assert spec.options_panel_cls is not None, f"{name} has no options panel"
        assert spec.help_title and spec.help_body, f"{name} has no help text"


@pytest.mark.ui
@pytest.mark.parametrize("plot_name", list(PLOT_REGISTRY.keys()))
def test_plot_type_renders_without_crashing(qtbot, two_sample_state, plot_name):
    """Drives the exact same path ComparisonsWorker.run() does
    (spec.build_kwargs -> renderer.render()) for every registered plot type,
    using the UI's own current selection state — so it also exercises each
    plot type's sample/population/channel constraints, not just the renderer.
    """
    widget = ComparisonsViewer(two_sample_state)
    qtbot.addWidget(widget)

    idx = widget._plot_type_combo.findText(plot_name)
    assert idx >= 0, f"{plot_name} not in the plot type combo"
    widget._plot_type_combo.setCurrentIndex(idx)

    spec = PLOT_REGISTRY[plot_name]
    sample_ids = widget._selector.get_checked_sample_ids()
    assert sample_ids, f"{plot_name}: no sample checked after switching to it"
    if spec.sample_mode == SampleMode.SINGLE:
        assert len(sample_ids) == 1, (
            f"{plot_name} is SampleMode.SINGLE but {len(sample_ids)} samples are checked"
        )

    panel = widget._options_panels[plot_name]
    config = panel.get_config()
    pop_pairs = widget._selector.get_checked_populations()
    channel_keys = widget._get_checked_channels() if spec.channel_mode != ChannelMode.NONE else []

    kwargs = spec.build_kwargs(
        widget._state, widget._extractor, config, sample_ids, pop_pairs, channel_keys
    )
    kwargs.update(
        bg_color="#0d1117",
        fg_color="#e6edf3",
        border_color="#30363d",
        accent_color="#00bcd4",
        palette=["#00bcd4", "#ef5350", "#66bb6a"],
    )

    renderer = spec.renderer_cls()
    fig = renderer.render(**kwargs)

    assert fig is not None
    assert len(fig.axes) >= 1


@pytest.mark.ui
def test_single_sample_plot_type_cannot_have_two_samples_checked(qtbot, two_sample_state):
    """The exact bug report: selecting a second sample for a single-sample
    plot type (e.g. Pseudocolor Overlay) must not be possible through the UI.
    """
    widget = ComparisonsViewer(two_sample_state)
    qtbot.addWidget(widget)

    idx = widget._plot_type_combo.findText("🌈  Pseudocolor Overlay")
    widget._plot_type_combo.setCurrentIndex(idx)
    assert len(widget._selector.get_checked_sample_ids()) == 1

    # Try to check the second sample directly through the underlying list widget.
    from PyQt6.QtCore import Qt

    list_widget = widget._selector.sample_list.list_widget
    for i in range(list_widget.count()):
        item = list_widget.item(i)
        if item.checkState() != Qt.CheckState.Checked:
            item.setCheckState(Qt.CheckState.Checked)

    assert len(widget._selector.get_checked_sample_ids()) == 1


@pytest.mark.ui
def test_multi_sample_plot_type_allows_multiple_samples(qtbot, two_sample_state):
    widget = ComparisonsViewer(two_sample_state)
    qtbot.addWidget(widget)

    idx = widget._plot_type_combo.findText("🗺️  Channel Heatmap")
    widget._plot_type_combo.setCurrentIndex(idx)

    widget._selector.sample_list.set_all_checked(True)
    assert set(widget._selector.get_checked_sample_ids()) == {"s1", "s2"}


@pytest.mark.ui
def test_switching_from_single_to_multi_sample_mode_restores_multi_select(qtbot, two_sample_state):
    widget = ComparisonsViewer(two_sample_state)
    qtbot.addWidget(widget)

    pseudo_idx = widget._plot_type_combo.findText("🌈  Pseudocolor Overlay")
    widget._plot_type_combo.setCurrentIndex(pseudo_idx)
    assert len(widget._selector.get_checked_sample_ids()) == 1

    violin_idx = widget._plot_type_combo.findText("🎻  Violin Plot")
    widget._plot_type_combo.setCurrentIndex(violin_idx)
    widget._selector.sample_list.set_all_checked(True)
    assert set(widget._selector.get_checked_sample_ids()) == {"s1", "s2"}


def _cycle_and_render(widget, plot_names) -> None:
    for plot_name in plot_names:
        spec = PLOT_REGISTRY[plot_name]
        idx = widget._plot_type_combo.findText(plot_name)
        widget._plot_type_combo.setCurrentIndex(idx)

        sample_ids = widget._selector.get_checked_sample_ids()
        assert sample_ids, f"{plot_name}: no sample checked"

        panel = widget._options_panels[plot_name]
        config = panel.get_config()
        pop_pairs = widget._selector.get_checked_populations()
        channel_keys = (
            widget._get_checked_channels() if spec.channel_mode != ChannelMode.NONE else []
        )

        kwargs = spec.build_kwargs(
            widget._state, widget._extractor, config, sample_ids, pop_pairs, channel_keys
        )
        kwargs.update(
            bg_color="#0d1117",
            fg_color="#e6edf3",
            border_color="#30363d",
            accent_color="#00bcd4",
            palette=["#00bcd4", "#ef5350", "#66bb6a"],
        )
        fig = spec.renderer_cls().render(**kwargs)
        assert fig is not None, f"{plot_name} produced no figure"


@pytest.mark.ui
@pytest.mark.parametrize("plot_name", list(PLOT_REGISTRY.keys()))
def test_generate_button_produces_a_visible_canvas(qtbot, two_sample_state, plot_name):
    """Regression test for two real bugs neither `test_plot_type_renders_
    without_crashing` nor `_cycle_and_render` above could catch, because both
    call `renderer.render()` directly and skip the actual Generate Plot path
    (`_on_generate` -> `ComparisonsWorker` QThread -> `_on_render_done`):

    1. `_on_render_done` guarded the canvas-swap logic with
       `if container_layout:` — but a QLayout's truthiness in PyQt6 follows
       `__len__()`/`count()`, not identity, so an *empty* layout (true on
       every single Generate Plot click, since nothing was ever successfully
       added) silently skipped `addWidget()`. The figure always rendered
       correctly — Export/Download worked, since those read
       `self._current_figure` directly — but the canvas widget was never
       parented into the visible tree, so nothing ever appeared on screen,
       for every plot type, every time.
    2. `ComparisonsWorker.run()` calls `renderer.render()` — which ends in
       `fig.tight_layout()` for most renderers — on a QThread. tight_layout()
       computes tick space via `Transform.inverted()` -> `numpy.linalg.inv()`,
       a BLAS call; nested BLAS-thread-pool parallelism on this thread's
       small stack reproduced a real SIGBUS (confirmed with a full native
       backtrace pinning it to this exact call chain). Fixed by wrapping the
       render call in `threadpoolctl.threadpool_limits(1)`, mirroring the
       identical, already-proven fix for the same hazard in
       `analysis/fcs_io.py`'s `_auto_apply_spill`.
    """
    widget = ComparisonsViewer(two_sample_state)
    qtbot.addWidget(widget)
    widget.resize(1200, 800)
    widget.show()
    qtbot.waitExposed(widget)

    idx = widget._plot_type_combo.findText(plot_name)
    assert idx >= 0
    widget._plot_type_combo.setCurrentIndex(idx)

    widget._generate_btn.click()
    worker = widget._worker
    assert worker is not None, f"{plot_name}: Generate Plot did not spawn a worker"

    # Use waitUntil instead of waitSignal because the worker might finish
    # and emit its signal before we even enter a waitSignal block, causing a timeout.
    qtbot.waitUntil(lambda: widget._worker is None, timeout=30000)

    assert "Plot ready" in widget._status_lbl.text(), f"{plot_name}: {widget._status_lbl.text()}"
    canvas = widget._canvas_widget
    assert canvas is not None, f"{plot_name}: no canvas widget was created"
    assert canvas.parent() is widget._canvas_container, (
        f"{plot_name}: canvas was never parented into the visible container"
    )
    assert canvas.isVisible(), f"{plot_name}: canvas exists but is not visible"
    assert widget._display_stack.currentWidget() is widget._canvas_scroll


@pytest.mark.ui
def test_cycling_through_every_plot_type_always_renders(qtbot, two_sample_state):
    """Clicks through every plot type — forward through registry order, then
    backward — rendering after each switch. Catches mode-transition bugs a
    single fresh-widget-per-plot-type test can't: e.g. a channel checked
    under single-channel mode silently carrying over and leaving a
    multi-channel plot type under its minimum (the Radar Chart regression
    this suite caught), or an analogous issue only visible when unwinding
    back through single-sample plot types in the other direction.
    """
    widget = ComparisonsViewer(two_sample_state)
    qtbot.addWidget(widget)

    plot_names = list(PLOT_REGISTRY.keys())
    _cycle_and_render(widget, plot_names)
    _cycle_and_render(widget, reversed(plot_names))
