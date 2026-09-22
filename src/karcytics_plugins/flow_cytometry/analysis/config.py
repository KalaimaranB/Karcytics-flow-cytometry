"""Configuration management for Flow Cytometry module."""

from __future__ import annotations

from dataclasses import dataclass, field

from karcytics_sdk.plugin import PluginConfig

from . import constants


class FlowConfig:
    """Manages persistent user preferences for the flow module."""

    _config = PluginConfig("flow_cytometry")

    # Keys
    AUTO_RANGE = "auto_range_on_quality"
    LAST_X_PARAM = "last_x_param"
    LAST_Y_PARAM = "last_y_param"

    @classmethod
    def get_auto_range(cls) -> bool:
        return cls._config.get(cls.AUTO_RANGE, True)

    @classmethod
    def set_auto_range(cls, value: bool):
        cls._config.set(cls.AUTO_RANGE, value)
        cls._config.save()

    @classmethod
    def get_last_params(cls) -> tuple[str, str]:
        x = cls._config.get(cls.LAST_X_PARAM, "FSC-A")
        y = cls._config.get(cls.LAST_Y_PARAM, "SSC-A")
        return x, y

    @classmethod
    def set_last_params(cls, x: str, y: str):
        cls._config.set(cls.LAST_X_PARAM, x)
        cls._config.set(cls.LAST_Y_PARAM, y)
        cls._config.save()


# ── Available colormaps (scientist-friendly labels → matplotlib names) ────────
COLORMAPS: list[tuple[str, str]] = [
    ("Jet (Classic Flow)", "jet"),
    ("Viridis", "viridis"),
    ("Plasma", "plasma"),
    ("Inferno", "inferno"),
    ("Magma", "magma"),
    ("Cividis (CVD-safe)", "cividis"),
    ("Turbo", "turbo"),
    ("Cool", "cool"),
    ("Hot", "hot"),
    ("Rainbow", "gist_rainbow"),
    ("Spectral", "Spectral_r"),
    ("Yellow–Orange–Red", "YlOrRd"),
    ("Blue–Green", "BuGn"),
    ("Blues", "Blues_r"),
    ("Greens", "Greens_r"),
    ("RdYlBu (Diverging)", "RdYlBu"),
]


@dataclass
class PseudocolorConfig:
    """Settings for the Pseudocolor (density scatter) renderer."""

    # Scientist label → internal parameter
    colormap: str = "jet"  # matplotlib cmap name
    max_events: int = constants.MAIN_PLOT_MAX_EVENTS_OPTIMIZED
    # "Population Detail" → nbins_scaling
    population_detail: float = constants.NBINS_SCALING_FACTOR
    # "Population Smoothing" → sigma_scaling
    population_smoothing: float = constants.SIGMA_SCALING_FACTOR
    # "Background Suppression" → density_threshold
    background_suppression: float = constants.DENSITY_THRESHOLD_MIN
    # "Color Contrast" encodes vibrancy_min and vibrancy_range together
    vibrancy_min: float = constants.VIBRANCY_MIN
    vibrancy_range: float = constants.VIBRANCY_RANGE

    # New: Canonical visual styling
    point_size: float = 1.5
    opacity: float = 0.6

    def to_dict(self) -> dict:
        return {
            "colormap": self.colormap,
            "max_events": self.max_events,
            "population_detail": self.population_detail,
            "population_smoothing": self.population_smoothing,
            "background_suppression": self.background_suppression,
            "vibrancy_min": self.vibrancy_min,
            "vibrancy_range": self.vibrancy_range,
            "point_size": self.point_size,
            "opacity": self.opacity,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PseudocolorConfig:
        return cls(
            colormap=d.get("colormap", "jet"),
            max_events=d.get("max_events", constants.MAIN_PLOT_MAX_EVENTS_OPTIMIZED),
            population_detail=d.get("population_detail", constants.NBINS_SCALING_FACTOR),
            population_smoothing=d.get("population_smoothing", constants.SIGMA_SCALING_FACTOR),
            background_suppression=d.get("background_suppression", constants.DENSITY_THRESHOLD_MIN),
            vibrancy_min=d.get("vibrancy_min", constants.VIBRANCY_MIN),
            vibrancy_range=d.get("vibrancy_range", constants.VIBRANCY_RANGE),
            point_size=d.get("point_size", 1.5),
            opacity=d.get("opacity", 0.6),
        )


@dataclass
class DotPlotConfig:
    """Settings for the Dot Plot (simple scatter) renderer."""

    dot_color: str = "#2196F3"  # hex color
    dot_size: float = 2.0  # points²
    opacity: float = 0.25  # 0–1
    max_events: int = constants.MAIN_PLOT_MAX_EVENTS_OPTIMIZED

    def to_dict(self) -> dict:
        return {
            "dot_color": self.dot_color,
            "dot_size": self.dot_size,
            "opacity": self.opacity,
            "max_events": self.max_events,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DotPlotConfig:
        return cls(
            dot_color=d.get("dot_color", "#2196F3"),
            dot_size=d.get("dot_size", 2.0),
            opacity=d.get("opacity", 0.25),
            max_events=d.get("max_events", constants.MAIN_PLOT_MAX_EVENTS_OPTIMIZED),
        )


@dataclass
class HistogramConfig:
    """Settings for the 1D Histogram renderer."""

    bar_color: str = "#2196F3"  # hex color
    bins: int = 256
    auto_bins: bool = False  # auto-compute bins from data
    y_axis_mode: str = "count"  # "count" or "frequency"
    filled: bool = True  # False = outline only (step)
    smooth_kde: bool = False  # overlay a KDE curve

    fmo_color: str = "#888888"  # hex color for FMO overlay
    show_fmo_threshold: bool = True  # show the 99th percentile line for FMO overlays
    fmo_threshold_percentile: float = 99.0  # percentile for the threshold
    fmo_threshold_color: str = "#ff4444"  # color of the threshold line

    def to_dict(self) -> dict:
        return {
            "bar_color": self.bar_color,
            "bins": self.bins,
            "auto_bins": self.auto_bins,
            "y_axis_mode": self.y_axis_mode,
            "filled": self.filled,
            "smooth_kde": self.smooth_kde,
            "fmo_color": self.fmo_color,
            "show_fmo_threshold": self.show_fmo_threshold,
            "fmo_threshold_percentile": self.fmo_threshold_percentile,
            "fmo_threshold_color": self.fmo_threshold_color,
        }

    @classmethod
    def from_dict(cls, d: dict) -> HistogramConfig:
        return cls(
            bar_color=d.get("bar_color", "#2196F3"),
            bins=d.get("bins", 256),
            auto_bins=d.get("auto_bins", False),
            y_axis_mode=d.get("y_axis_mode", "count"),
            filled=d.get("filled", True),
            smooth_kde=d.get("smooth_kde", False),
            fmo_color=d.get("fmo_color", "#888888"),
            show_fmo_threshold=d.get("show_fmo_threshold", True),
            fmo_threshold_percentile=d.get("fmo_threshold_percentile", 99.0),
            fmo_threshold_color=d.get("fmo_threshold_color", "#ff4444"),
        )


@dataclass
class ContourConfig:
    """Settings for the 2D Contour renderer."""

    num_levels: int = 10
    smoothing: float = 1.5  # gaussian sigma
    color_mode: str = "black"  # "black" | "blue" | "colormap"
    colormap: str = "viridis"  # used when color_mode == "colormap"
    show_filled: bool = False
    show_dot_underlay: bool = False  # scatter dots under contours

    def to_dict(self) -> dict:
        return {
            "num_levels": self.num_levels,
            "smoothing": self.smoothing,
            "color_mode": self.color_mode,
            "colormap": self.colormap,
            "show_filled": self.show_filled,
            "show_dot_underlay": self.show_dot_underlay,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ContourConfig:
        return cls(
            num_levels=d.get("num_levels", 10),
            smoothing=d.get("smoothing", 1.5),
            color_mode=d.get("color_mode", "black"),
            colormap=d.get("colormap", "viridis"),
            show_filled=d.get("show_filled", False),
            show_dot_underlay=d.get("show_dot_underlay", False),
        )


@dataclass
class RenderConfig:
    """Global render configuration — one instance shared across all plots.

    Contains per-mode sub-configs. The active mode's config is picked by
    the data layer at render time.
    """

    pseudocolor: PseudocolorConfig = field(default_factory=PseudocolorConfig)
    dot_plot: DotPlotConfig = field(default_factory=DotPlotConfig)
    histogram: HistogramConfig = field(default_factory=HistogramConfig)
    contour: ContourConfig = field(default_factory=ContourConfig)

    # ── Backward-compatible flat properties (used by legacy rendering paths) ──
    @property
    def max_events(self) -> int:
        return self.pseudocolor.max_events

    @property
    def nbins_scaling(self) -> float:
        return self.pseudocolor.population_detail

    @property
    def sigma_scaling(self) -> float:
        return self.pseudocolor.population_smoothing

    @property
    def density_threshold(self) -> float:
        return self.pseudocolor.background_suppression

    @property
    def vibrancy_min(self) -> float:
        return self.pseudocolor.vibrancy_min

    @property
    def vibrancy_range(self) -> float:
        return self.pseudocolor.vibrancy_range

    def to_dict(self) -> dict:
        return {
            "pseudocolor": self.pseudocolor.to_dict(),
            "dot_plot": self.dot_plot.to_dict(),
            "histogram": self.histogram.to_dict(),
            "contour": self.contour.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> RenderConfig:
        # Support both the new nested format and the old flat format
        if "pseudocolor" in data:
            return cls(
                pseudocolor=PseudocolorConfig.from_dict(data.get("pseudocolor", {})),
                dot_plot=DotPlotConfig.from_dict(data.get("dot_plot", {})),
                histogram=HistogramConfig.from_dict(data.get("histogram", {})),
                contour=ContourConfig.from_dict(data.get("contour", {})),
            )
        # Legacy flat format — migrate to pseudocolor sub-config
        pc = PseudocolorConfig(
            max_events=data.get("max_events", constants.MAIN_PLOT_MAX_EVENTS_OPTIMIZED),
            population_detail=data.get("nbins_scaling", constants.NBINS_SCALING_FACTOR),
            population_smoothing=data.get("sigma_scaling", constants.SIGMA_SCALING_FACTOR),
            background_suppression=data.get("density_threshold", constants.DENSITY_THRESHOLD_MIN),
            vibrancy_min=data.get("vibrancy_min", constants.VIBRANCY_MIN),
            vibrancy_range=data.get("vibrancy_range", constants.VIBRANCY_RANGE),
        )
        return cls(pseudocolor=pc)
