"""Whole-figure plots rendered off the GUI thread.

`IPlotRenderer` builds a complete matplotlib `Figure` from plain data;
`FigureRenderWorker` runs one on a background thread and emits the result.
Widgets show the Figure in a canvas when it arrives. (Per-axes drawing on the
gating canvas is a different contract: `renderers.base.DisplayStrategy`.)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import threadpoolctl
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK
from karcytics_sdk.plugin.worker_thread import OneShotWorkerThread
from matplotlib.figure import Figure
from PySide6.QtCore import QObject


class IPlotRenderer(ABC):
    """Single-responsibility: produce a matplotlib Figure from data kwargs.

    Subclasses must not import Qt, Karcytics theme, or FlowState — all
    necessary values are passed in as plain Python primitives via kwargs.
    This makes renderers independently testable without a Qt application.
    """

    def prepare(self, **kwargs) -> dict:
        """Optional heavy-computation step, run *before* MPL_RASTER_LOCK.

        FigureRenderWorker calls this on the background thread first, then
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
        drawing calls. The caller (FigureRenderWorker) runs this on a
        background thread while holding MPL_RASTER_LOCK — see prepare().
        Implementations must be thread-safe.
        """


class FigureRenderWorker(OneShotWorkerThread):
    """Runs one `IPlotRenderer` on a background thread and emits its Figure.

    The caller injects the concrete renderer; this depends only on `IPlotRenderer`.
    """

    def __init__(self, renderer: IPlotRenderer, kwargs: dict, parent: QObject) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._kwargs = kwargs

    def _execute(self):
        """SRP: call renderer.prepare() then renderer.render(), returning the Figure.

        prepare() runs first, on this background thread, *without* holding
        MPL_RASTER_LOCK — it's where a renderer does any real numpy/scipy
        computation (density estimation, histogram binning, ...). Only
        render()'s matplotlib Figure/Axes construction and drawing calls run
        under the lock. Renderers that don't override prepare() (the
        default no-op) behave exactly as before this split existed.

        Renderers build matplotlib Figures and call tight_layout(), which
        invokes the Agg/FreeType C backend. That backend is not thread-safe
        against RenderTask's concurrent rendering of the main canvas / group
        previews on other threads, so MPL_RASTER_LOCK (the same lock
        RenderTask holds) must be held here too.

        Separately, tight_layout() computes each axis's tick space via
        Transform.inverted(), which calls numpy.linalg.inv() — a BLAS call.
        Reproduced with a real backtrace: on this QThread's small stack,
        nested BLAS-thread-pool parallelism inside that inv() call
        crashes the whole process with SIGBUS (EXC_BAD_ACCESS), the same
        hazard already fixed at its other known call site (see
        analysis/fcs_io.py's `_auto_apply_spill`). The OPENBLAS_NUM_THREADS=1
        env var set at plugin init only takes effect if set before
        OpenBLAS/MKL first initializes — a no-op if the host app's own numpy
        usage already triggered that first — so force it explicitly here too,
        at the actual call site, rather than relying on process-wide state.
        """
        with threadpoolctl.threadpool_limits(1):
            prepared_kwargs = self._renderer.prepare(**self._kwargs)
            with MPL_RASTER_LOCK:
                return self._renderer.render(**prepared_kwargs)
