"""Analysis task for off-thread plot rendering.

Uses the Karcytics TaskScheduler to render high-fidelity plots without blocking the UI.
Returns an RGBA byte buffer that can be loaded into a QImage/QPixmap.
"""

from __future__ import annotations

import typing
from typing import Any

import numpy as np
import pandas as pd
from karcytics_sdk.plugin import AnalysisBase, get_logger
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK as _MPL_LOCK

from karcytics_plugins.flow_cytometry.analysis.scaling import AxisScale
from karcytics_plugins.flow_cytometry.analysis.transforms import (
    TransformType,
    apply_transform,
)

logger = get_logger(__name__, "flow_cytometry")

# _MPL_LOCK: Shared with DataLayerRenderer — both must hold this lock around all
# matplotlib draw calls.


class RenderTask(AnalysisBase):
    """Asynchronous plot renderer."""

    def __init__(self, plugin_id: str = "flow_cytometry") -> None:
        super().__init__(plugin_id)
        self.config: dict = {}

    def configure(  # noqa: PLR0913
        self,
        data: pd.DataFrame | None = None,
        x_param: str = "",
        y_param: str | None = None,
        x_scale: AxisScale | None = None,
        y_scale: AxisScale | None = None,
        x_range: tuple[float, float] | None = None,
        y_range: tuple[float, float] | None = None,
        sample_id: str | None = None,
        peer_node_id: str | None = None,
        width_px: int = 400,
        height_px: int = 400,
        plot_type: str = "pseudocolor",
        max_events: int | None = 100000,
        quality_multiplier: float = 1.0,
        gates: list[Any] | None = None,
        selected_gate_id: str | None = None,
        colormap: str = "jet",
        s: float | None = None,
        render_config: dict | None = None,
        fmo_sample_id: str | None = None,
    ) -> None:
        """Set the rendering parameters."""
        self.config = {
            "data": data,
            "sample_id": sample_id,
            "fmo_sample_id": fmo_sample_id,
            "peer_node_id": peer_node_id,
            "x_param": x_param,
            "y_param": y_param,
            "x_scale": x_scale,
            "y_scale": y_scale,
            "x_range": x_range,
            "y_range": y_range,
            "width": width_px,
            "height": height_px,
            "plot_type": plot_type,
            "max_events": max_events,
            "quality_multiplier": quality_multiplier,
            "gates": gates or [],
            "selected_gate_id": selected_gate_id,
            "colormap": colormap,
            "s": s,
            "dpi": render_config.get("dpi", 150) if render_config else 150,
            "render_config": render_config or {},
            "show_gate_labels": render_config.get("show_gate_labels", True)
            if render_config
            else True,
            "show_axis_labels": render_config.get("show_axis_labels", True)
            if render_config
            else True,
        }

    def run(self, state: typing.Any | None = None) -> dict:  # noqa: PLR0912, PLR0915
        """Execute the render — called by TaskScheduler."""
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        c = self.config
        if not c:
            return {"error": "Not configured"}

        if c.get("data") is not None:
            data = c["data"]
            x_range = c["x_range"]
            y_range = c["y_range"]
        else:
            from ...analysis.axis_manager import AxisManager
            from ...analysis.population_service import PopulationService

            flow_state = typing.cast(typing.Any, state)

            pop_svc = PopulationService(flow_state)
            ax_mgr = AxisManager(flow_state)

            data = pop_svc.get_gated_events(c["sample_id"], c.get("peer_node_id"))
            if data is None or len(data) == 0:
                return {"error": "No data available"}

            x_range = c.get("x_range") or ax_mgr.calculate_range(data[c["x_param"]], c["x_param"])
            if c.get("y_param"):
                y_range = c.get("y_range") or ax_mgr.calculate_range(
                    data[c["y_param"]], c["y_param"]
                )
            else:
                y_range = None

        x_ch, y_ch = c["x_param"], c["y_param"]

        if x_ch not in data.columns:
            return {"error": f"Missing x_param: {x_ch}"}

        if y_ch is not None and y_ch not in data.columns:
            return {"error": f"Missing y_param: {y_ch}"}

        # 1. Use the same max_events logic as the main plot for perfect parity
        thumb_max = c.get("max_events", 100000)
        if thumb_max is None:
            thumb_max = len(data)

        if len(data) > thumb_max:
            data = data.sample(n=thumb_max, random_state=42)

        # 2. Transform raw data to display coordinates
        def _get_xform_params(scale):
            from ...analysis._utils import BiexponentialParameters

            return (
                BiexponentialParameters(scale).to_dict()
                if scale.transform_type == TransformType.BIEXPONENTIAL
                else {}
            )

        x_vis = apply_transform(
            data[x_ch].values.astype(np.float64),
            c["x_scale"].transform_type,
            **_get_xform_params(c["x_scale"]),
        )

        if y_ch is not None:
            y_vis = apply_transform(
                data[y_ch].values.astype(np.float64),
                c["y_scale"].transform_type,
                **_get_xform_params(c["y_scale"]),
            )
        else:
            y_vis = None

        # Extract FMO data if requested (for Histogram overlays)
        fmo_data_x = None
        fmo_sample_id = c.get("fmo_sample_id")
        if fmo_sample_id and c["plot_type"] == "Histogram" and c["x_param"]:
            try:
                flow_state = typing.cast(typing.Any, state)
                fmo_sample = flow_state.data.experiment.samples.get(fmo_sample_id)
                if (
                    fmo_sample
                    and fmo_sample.fcs_data is not None
                    and c["x_param"] in fmo_sample.fcs_data.events
                ):
                    fmo_raw_x = fmo_sample.fcs_data.events[c["x_param"]].values.astype(np.float64)

                    if len(fmo_raw_x) > thumb_max:
                        rng = np.random.default_rng(42)
                        fmo_raw_x = rng.choice(fmo_raw_x, size=thumb_max, replace=False)

                    fmo_data_x = apply_transform(
                        fmo_raw_x,
                        c["x_scale"].transform_type,
                        **_get_xform_params(c["x_scale"]),
                    )
            except Exception as e:
                logger.error(f"Failed to extract FMO data in RenderTask: {e}")

        # 3. Transform limits to display coordinates
        xlim = apply_transform(
            np.asarray(x_range),
            c["x_scale"].transform_type,
            **_get_xform_params(c["x_scale"]),
        )
        if y_range is not None and c.get("y_scale") is not None:
            ylim = apply_transform(
                np.asarray(y_range),
                c["y_scale"].transform_type,
                **_get_xform_params(c["y_scale"]),
            )
        else:
            ylim = None

        # 4. Render data layer using the EXACT same strategy as the main UI.
        # compute() is pure numpy/scipy — it runs *outside* _MPL_LOCK so the
        # expensive density/KDE work isn't serialized against other renders;
        # only draw() (the actual Agg rasterization) needs the lock below.
        from .renderers.factory import RenderStrategyFactory

        # Map plot_type string to strategy name
        strategy_name = "Pseudocolor" if c["plot_type"] == "pseudocolor" else c["plot_type"]
        strategy = RenderStrategyFactory.get_strategy(strategy_name)

        # Extract render_config values if available
        rc = c.get("render_config", {})

        # Call the strategy with the same parameters as the main plot
        # Note: we pass quality_multiplier from config for parity
        kwargs = {
            "max_events": thumb_max,
            "quality_multiplier": c.get("quality_multiplier", 1.0),
            "grid_size": int(512 * c.get("quality_multiplier", 1.0)),
            "cmap": c["colormap"],
            "s": c.get("s"),
            "nbins_scaling": rc.get("nbins_scaling"),
            "sigma_scaling": rc.get("sigma_scaling"),
            "density_threshold": rc.get("density_threshold"),
            "vibrancy_min": rc.get("vibrancy_min"),
            "vibrancy_range": rc.get("vibrancy_range"),
            "fmo_data_x": fmo_data_x,
        }

        if c["plot_type"] == "Histogram" and "histogram" in rc:
            kwargs.update(rc["histogram"])

        render_data = strategy.compute(x_vis, y_vis, xlim=xlim, ylim=ylim, **kwargs)  # type: ignore

        # 5–7. Figure creation, drawing, and buffer extraction are serialized
        # behind _MPL_LOCK because matplotlib's Agg C backend is not thread-safe
        # on macOS ARM: concurrent calls cause a SIGBUS / memory corruption.
        with _MPL_LOCK:
            base_dpi = 150
            target_dpi = c.get("dpi", 150)
            fig = Figure(figsize=(c["width"] / base_dpi, c["height"] / base_dpi), dpi=target_dpi)
            canvas = FigureCanvasAgg(fig)
            ax = fig.add_axes([0, 0, 1, 1])  # type: ignore
            ax.set_axis_off()
            fig.patch.set_facecolor("#FFFFFF")
            ax.set_facecolor("#FFFFFF")
            ax.set_xlim(xlim)
            if ylim is not None and c["plot_type"] != "Histogram":
                ax.set_ylim(ylim)

            strategy.draw(ax, render_data, **kwargs)  # type: ignore

            # 6. Render gate overlays (Identical to main FlowCanvas)
            if c.get("gates"):
                from .flow_services import CoordinateMapper, GateOverlayRenderer

                mapper = CoordinateMapper(c["x_scale"], c["y_scale"])
                # Thinner lines for subplots (0.6 instead of 2.5)
                show_gate_labels = c.get("show_gate_labels", True)
                renderer = GateOverlayRenderer(mapper, linewidth=0.6, show_labels=show_gate_labels)

                for gate in c["gates"]:
                    # Draw the gate if it matches the current axes.
                    # Range gates (gate.y_param=None) are 1-D — they match any Y context,
                    # and render_range draws them as full-height vertical boundary lines.
                    x_matches = gate.x_param == x_ch
                    y_matches = gate.y_param is None or gate.y_param == y_ch
                    if x_matches and y_matches:
                        is_selected = gate.gate_id == c.get("selected_gate_id")
                        renderer.render_gate(ax, gate, is_selected=is_selected)

            if c.get("show_axis_labels", True):
                ax.text(
                    0.5,
                    0.02,
                    x_ch,
                    transform=ax.transAxes,
                    ha="center",
                    va="bottom",
                    fontsize=6,
                    color="#555555",
                    weight="bold",
                )
                ax.text(
                    0.02,
                    0.5,
                    y_ch,
                    transform=ax.transAxes,
                    ha="left",
                    va="center",
                    rotation="vertical",
                    fontsize=6,
                    color="#555555",
                    weight="bold",
                )

            canvas.draw()
            rgba_buffer = canvas.buffer_rgba()
            image_data = bytes(rgba_buffer)

            # Free memory
            fig.clf()

        actual_width = int(c["width"] * (target_dpi / base_dpi))
        actual_height = int(c["height"] * (target_dpi / base_dpi))

        return {
            "image_data": image_data,
            "width": actual_width,
            "height": actual_height,
            "x_range": x_range,
            "y_range": y_range,
        }
