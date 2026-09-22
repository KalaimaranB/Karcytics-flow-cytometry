"""Per-plot-type kwargs builders: translate (state, UI selection, options
config) into the exact keyword arguments each renderer's ``render()``
expects.

Each function has the signature described by
``plot_spec.KwargsBuilder`` and is referenced by exactly one
``PlotTypeSpec.build_kwargs`` in ``registry.py`` — that's the only place
they're wired in, so a missing or mismatched builder is a registry-time
error, not a render-time crash. Callers guarantee ``sample_ids`` is
non-empty before calling any of these (ComparisonsViewer validates that
once, generically, before dispatching).

These functions legitimately need ``FlowState``/``ComparisonsDataExtractor``,
which is exactly why they live here rather than on the renderers themselves:
``IPlotRenderer`` subclasses are documented to stay Qt/state-free so they're
testable as pure Figure-producing functions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from karcytics_plugins.flow_cytometry.analysis.statistics import StatType

if TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState

    from .data_extractor import ComparisonsDataExtractor


def build_violin_kwargs(
    state: FlowState,
    extractor: ComparisonsDataExtractor,
    config: dict,
    sample_ids: list[str],
    pop_pairs: list[tuple],
    channel_keys: list[str],
) -> dict:
    if not channel_keys:
        raise ValueError("Select a single channel for the violin plot.")
    kwargs = dict(config)
    channel = channel_keys[0]
    ch_labels = extractor.get_channel_list(state, sample_ids[0])
    ch_label = next((lbl for lbl, k in ch_labels if k == channel), channel)

    # One population per sample. pop_pairs are (sid, nid, label); take the
    # first checked population per sample.
    sid_to_node: dict[str, str | None] = {}
    for pp in pop_pairs:
        pp_sid, pp_nid = pp[0], pp[1]
        if pp_sid not in sid_to_node:
            sid_to_node[pp_sid] = pp_nid

    data_per_label: dict[str, np.ndarray] = {}
    for sid in sample_ids:
        sample = state.data.experiment.samples.get(sid)
        label = sample.display_name if sample else sid
        node_id = sid_to_node.get(sid)
        vals = extractor.get_events_for_population(state, sid, node_id, channel)
        if len(vals) > 0:
            data_per_label[label] = vals

    kwargs["data_per_label"] = data_per_label
    kwargs["channel_label"] = ch_label
    return kwargs


def build_heatmap_kwargs(
    state: FlowState,
    extractor: ComparisonsDataExtractor,
    config: dict,
    sample_ids: list[str],
    pop_pairs: list[tuple],
    channel_keys: list[str],
) -> dict:
    if not channel_keys:
        raise ValueError("Select at least one channel for the heatmap.")
    if not pop_pairs:
        raise ValueError("Select at least one population for the heatmap.")

    kwargs = dict(config)
    stat_map = {
        "median": StatType.MEDIAN,
        "mean": StatType.MEAN,
        "geometric_mean": StatType.GEOMETRIC_MEAN,
    }
    stat_type = stat_map.get(config.get("stat", "median"), StatType.MEDIAN)

    matrix, row_labels, col_labels = extractor.get_statistic_matrix(
        state, pop_pairs, channel_keys, stat_type
    )
    kwargs["matrix"] = matrix
    kwargs["row_labels"] = row_labels
    kwargs["col_labels"] = col_labels
    return kwargs


_RADAR_MIN_CHANNELS = 3


def build_radar_kwargs(
    state: FlowState,
    extractor: ComparisonsDataExtractor,
    config: dict,
    sample_ids: list[str],
    pop_pairs: list[tuple],
    channel_keys: list[str],
) -> dict:
    if len(channel_keys) < _RADAR_MIN_CHANNELS:
        raise ValueError("Select at least 3 channels for the radar chart.")
    if not pop_pairs:
        raise ValueError("Select at least one population for the radar chart.")

    kwargs = dict(config)
    ch_label_map = {}
    for sid in sample_ids:
        for lbl, k in extractor.get_channel_list(state, sid):
            ch_label_map[k] = lbl
    col_labels = [ch_label_map.get(ch, ch) for ch in channel_keys]

    use_median = config.get("stat", "median") != "mean"

    data: dict[str, list[float]] = {}
    for sid, nid, plabel in pop_pairs:
        sample = state.data.experiment.samples.get(sid)
        if not sample or sample.fcs_data is None:
            continue
        key = f"{sample.display_name} / {plabel}"
        df = sample.fcs_data.events
        if nid and sample.gate_tree:
            node = sample.gate_tree.find_node_by_id(nid)
            if node:
                df = node.apply_hierarchy(df)
        vals_per_ch = []
        for ch in channel_keys:
            assert df is not None
            if ch in df.columns:
                arr = df[ch].to_numpy(dtype=float)
                arr = arr[np.isfinite(arr)]
                vals_per_ch.append(
                    float(np.median(arr) if use_median else np.mean(arr)) if len(arr) > 0 else 0.0
                )
            else:
                vals_per_ch.append(0.0)
        data[key] = vals_per_ch

    kwargs["data"] = data
    kwargs["channel_labels"] = col_labels
    return kwargs


def build_histogram_overlay_kwargs(
    state: FlowState,
    extractor: ComparisonsDataExtractor,
    config: dict,
    sample_ids: list[str],
    pop_pairs: list[tuple],
    channel_keys: list[str],
) -> dict:
    if not channel_keys:
        raise ValueError("Select a channel for the histogram overlay.")

    kwargs = dict(config)
    channel = channel_keys[0]
    ch_labels = extractor.get_channel_list(state, sample_ids[0])
    ch_label = next((lbl for lbl, k in ch_labels if k == channel), channel)

    data_per_label = {}
    for sid, nid, plabel in pop_pairs:
        sample = state.data.experiment.samples.get(sid)
        if not sample:
            continue
        sample_name = sample.display_name
        key = sample_name if nid is None else f"{sample_name} / {plabel}"
        vals = extractor.get_events_for_population(state, sid, nid, channel)
        if len(vals) > 0:
            data_per_label[key] = vals

    if not data_per_label:
        raise ValueError("No event data found for the selected samples and populations.")

    kwargs["data_per_label"] = data_per_label
    kwargs["channel_label"] = ch_label
    return kwargs


def _extract_overlay_layers(  # noqa: PLR0913
    state: FlowState,
    extractor: ComparisonsDataExtractor,
    pop_pairs: list[tuple],
    active_sid: str,
    x_channel: str,
    y_channel: str,
    x_scale_type,
    y_scale_type,
    x_tf_kwargs: dict,
    y_tf_kwargs: dict,
) -> list[dict]:
    from karcytics_plugins.flow_cytometry.analysis.transforms import apply_transform

    layers = []
    for sid, nid, plabel in pop_pairs:
        if sid != active_sid or nid is None:
            continue  # other samples (shouldn't occur in single-sample mode), or All Events
        lx, ly = extractor.get_2d_events_for_population(
            state, active_sid, nid, x_channel, y_channel
        )
        lx = apply_transform(lx, x_scale_type, **x_tf_kwargs)
        ly = apply_transform(ly, y_scale_type, **y_tf_kwargs)
        layers.append({"label": plabel, "x": lx, "y": ly})
    return layers


def build_pseudocolor_overlay_kwargs(
    state: FlowState,
    extractor: ComparisonsDataExtractor,
    config: dict,
    sample_ids: list[str],
    pop_pairs: list[tuple],
    channel_keys: list[str],  # noqa: ARG001 — this plot type owns its own X/Y pickers
) -> dict:
    x_channel = config.get("x_channel")
    y_channel = config.get("y_channel")
    if not x_channel or not y_channel:
        raise ValueError("Select X and Y axis channels for the pseudocolor overlay.")

    kwargs = dict(config)

    # Single-sample plot type (SampleMode.SINGLE): the sample checklist is
    # forced to one checked sample, so sample_ids[0] is *the* sample.
    active_sid = sample_ids[0]
    sample = state.data.experiment.samples.get(active_sid)
    if not sample:
        raise ValueError("Selected sample not found.")

    # Axis scaling — shared with the workspace tab's "⚙ Transforms" dialog
    # via the exact same AxisScale model and apply_transform()/
    # compute_axis_limits() functions the main gating canvas uses, so a
    # channel looks the same whether viewed here or there. See
    # PseudocolorOverlayOptionsPanel's embedded AxisTransformPanels.
    from karcytics_plugins.flow_cytometry.analysis.scaling import (
        AxisScale,
        compute_axis_limits,
        get_transform_kwargs,
    )
    from karcytics_plugins.flow_cytometry.analysis.transforms import apply_transform

    x_scale = AxisScale.from_dict(config.get("x_scale", {}))
    y_scale = AxisScale.from_dict(config.get("y_scale", {}))
    x_tf_kwargs = get_transform_kwargs(x_scale)
    y_tf_kwargs = get_transform_kwargs(y_scale)

    base_x_raw, base_y_raw = extractor.get_2d_events_for_population(
        state, active_sid, None, x_channel, y_channel
    )
    xlim = compute_axis_limits(base_x_raw, x_scale, x_tf_kwargs)
    ylim = compute_axis_limits(base_y_raw, y_scale, y_tf_kwargs)
    base_x = apply_transform(base_x_raw, x_scale.transform_type, **x_tf_kwargs)
    base_y = apply_transform(base_y_raw, y_scale.transform_type, **y_tf_kwargs)

    layers = _extract_overlay_layers(
        state,
        extractor,
        pop_pairs,
        active_sid,
        x_channel,
        y_channel,
        x_scale.transform_type,
        y_scale.transform_type,
        x_tf_kwargs,
        y_tf_kwargs,
    )

    if not layers:
        raise ValueError("Select at least one gated population (besides All Events) to overlay.")

    # Pre-compute the (expensive: fast_histogram + gaussian_filter +
    # map_coordinates + rankdata over up to PSEUDOCOLOR_MAX_EVENTS points)
    # density coloring for the base layer here, *before* the renderer runs
    # under ComparisonsWorker's MPL_RASTER_LOCK. That lock exists to serialize
    # matplotlib's C-level Agg/FreeType drawing calls against RenderTask's
    # background rendering of the main canvas — it was never meant to guard
    # pure-numpy data prep, and holding it for the whole duration of this
    # computation (which can take seconds on a real gated population)
    # needlessly starves the main canvas's paintEvent retries the whole time.
    from karcytics_plugins.flow_cytometry.analysis.config import PseudocolorConfig
    from karcytics_plugins.flow_cytometry.analysis.rendering import compute_pseudocolor_base_density

    # Shared with the workspace tab's Pseudocolor render mode — see
    # PseudocolorOverlayOptionsPanel's embedded PseudocolorSettingsPanel.
    pc_cfg = PseudocolorConfig.from_dict(config.get("pseudocolor_config", {}))

    kwargs["base_density"] = compute_pseudocolor_base_density(
        base_x,
        base_y,
        pc_cfg.max_events,
        enabled=config.get("show_density_base", True),
        nbins_scaling=pc_cfg.population_detail,
        sigma_scaling=pc_cfg.population_smoothing,
        density_threshold=pc_cfg.background_suppression,
        vibrancy_min=pc_cfg.vibrancy_min,
        vibrancy_range=pc_cfg.vibrancy_range,
    )
    kwargs["base_x"] = base_x
    kwargs["base_y"] = base_y
    kwargs["base_label"] = "All Events"
    kwargs["layers"] = layers
    kwargs["sample_label"] = sample.display_name
    kwargs["colormap"] = pc_cfg.colormap
    kwargs["base_point_size"] = pc_cfg.point_size
    kwargs["base_opacity"] = pc_cfg.opacity
    kwargs["xlim"] = xlim
    kwargs["ylim"] = ylim
    kwargs["x_scale"] = x_scale
    kwargs["y_scale"] = y_scale
    kwargs["x_transform_kwargs"] = x_tf_kwargs
    kwargs["y_transform_kwargs"] = y_tf_kwargs

    # Fixed (non-theme-following) chrome, matching the main gating canvas's
    # own white plot background — the jet colormap's low-density floor is a
    # dark blue that disappears against the app's dark theme. Set explicitly
    # here (rather than left to ComparisonsViewer's generic theme injection)
    # because this is the one Comparisons plot type drawn over a colormap
    # instead of flat themed chrome. See pseudocolor_overlay_renderer.py.
    from karcytics_plugins.flow_cytometry.ui.widgets.comparisons.renderers.pseudocolor_overlay_renderer import (
        DEFAULT_BG,
        DEFAULT_BORDER,
        DEFAULT_FG,
        JET_SAFE_OVERLAY_PALETTE,
    )

    kwargs["bg_color"] = DEFAULT_BG
    kwargs["fg_color"] = DEFAULT_FG
    kwargs["border_color"] = DEFAULT_BORDER
    kwargs["palette"] = JET_SAFE_OVERLAY_PALETTE
    return kwargs
