"""ComparisonsWorker — runs one renderer off the main thread.

SRP: only responsibility is running renderer.render(**kwargs) on a QThread
and emitting the result Figure or an error string.
"""

from __future__ import annotations

import threadpoolctl
from karcytics_sdk.plugin.rendering.lock import MPL_RASTER_LOCK
from karcytics_sdk.plugin.worker_thread import OneShotWorkerThread
from PyQt6.QtCore import QObject

from .renderers.base import IPlotRenderer


class ComparisonsWorker(OneShotWorkerThread):
    """Background thread for comparison plot rendering.

    DIP: depends on IPlotRenderer, not on any concrete renderer class.
    The caller injects the concrete renderer instance at construction time.
    """

    def __init__(self, renderer: IPlotRenderer, kwargs: dict, parent: QObject) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._kwargs = kwargs

    def _execute(self):
        """SRP: call renderer.render() and return the resulting Figure.

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
        with threadpoolctl.threadpool_limits(1), MPL_RASTER_LOCK:
            return self._renderer.render(**self._kwargs)
