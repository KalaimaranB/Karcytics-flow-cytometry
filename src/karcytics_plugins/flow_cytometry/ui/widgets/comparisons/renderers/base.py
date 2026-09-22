"""Abstract base for all comparison plot renderers.

ISP: narrow interface — only render() is required.
DIP: ComparisonsViewer depends on this, not on concrete renderer classes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from matplotlib.figure import Figure


class IPlotRenderer(ABC):
    """Single-responsibility: produce a matplotlib Figure from data kwargs.

    Subclasses must not import Qt, Karcytics theme, or FlowState — all
    necessary values are passed in as plain Python primitives via kwargs.
    This makes renderers independently testable without a Qt application.
    """

    def prepare(self, **kwargs) -> dict:
        """Optional heavy-computation step, run *before* MPL_RASTER_LOCK.

        ComparisonsWorker calls this on the background thread first, then
        acquires MPL_RASTER_LOCK and calls render() with whatever this
        returns (see worker.py). Default is a no-op passthrough — most
        renderers do cheap-enough work that splitting it out isn't worth
        the complexity. Override this only when render() would otherwise
        need real numpy/scipy computation (density estimation, histogram
        binning, etc.): see HistogramOverlayRenderer for the reference
        implementation. MPL_RASTER_LOCK is a process-wide lock shared with
        the main gating canvas's paint events — holding it around anything
        beyond the final matplotlib draw starves unrelated UI rendering
        elsewhere in the app for no thread-safety benefit (see
        karcytics_sdk.plugin.rendering.lock.RasterLock's docstring).
        """
        return kwargs

    @abstractmethod
    def render(self, **kwargs) -> Figure:
        """Render the plot and return a matplotlib Figure.

        Must be cheap: only matplotlib Figure/Axes construction and
        drawing calls. The caller (ComparisonsWorker) runs this on a
        background thread while holding MPL_RASTER_LOCK — see prepare().
        Implementations must be thread-safe.
        """
