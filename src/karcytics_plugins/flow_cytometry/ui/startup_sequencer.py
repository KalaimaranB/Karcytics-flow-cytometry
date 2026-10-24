"""Phase 2 of the panel's startup, and the loader's Ready Gate handshake.

The Hub's loader shows the panel once `panel_ready` fires (heavy widgets built)
and cross-fades into it on `data_ready` (data loaded, first render done);
`panel_ready` always comes first. See PluginBase's "Ready Gate" notes in the SDK.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.dialogs import show_warning
from PySide6.QtCore import QTimer

if TYPE_CHECKING:
    from PySide6.QtCore import SignalInstance
    from PySide6.QtWidgets import QWidget

logger = get_logger(__name__, "flow_cytometry")

_LOAD_WATCHDOG_MS = 45_000  # covers a numba JIT cold start
_SETTLE_MS = 300  # lets the restored canvases paint before the cross-fade

Step = tuple[str, Callable[[], None]]


class StartupSequencer:
    """Builds Phase 2 one step per event-loop turn, then emits the Ready Gate signals."""

    def __init__(
        self, panel_ready: SignalInstance, data_ready: SignalInstance, dialog_parent: QWidget
    ) -> None:
        self._panel_ready = panel_ready
        self._data_ready = data_ready
        self._dialog_parent = dialog_parent
        self._queue: list[Step] = []
        self._take_deferred_load: Callable[[], Callable[[], None] | None] = lambda: None
        self._awaiting_data = False  # a handed-over workflow is still loading
        self._data_ready_emitted = False
        panel_ready.connect(self._start_numba_warmup)

    def start(
        self, steps: list[Step], take_deferred_load: Callable[[], Callable[[], None] | None]
    ) -> None:
        """Runs `steps` one per tick so the loader animation gets a frame between them.

        `take_deferred_load` returns the load of a workflow the Hub handed over
        before Phase 2 finished (None when there is none).
        """
        self._queue = list(steps)
        self._take_deferred_load = take_deferred_load
        QTimer.singleShot(0, self._run_next)

    def _run_next(self) -> None:
        if not self._queue:
            self._finish()
            return
        name, step = self._queue.pop(0)
        logger.debug("[phase2] step start: %s", name)
        step()
        logger.debug("[phase2] step done: %s", name)
        QTimer.singleShot(0, self._run_next)

    def _finish(self) -> None:
        self._data_ready_emitted = False
        load = self._take_deferred_load()
        # panel_ready first, so the loader shows "Loading data…" before the load
        # (one tick later) blocks on FCS I/O.
        self._panel_ready.emit()
        if load is None:
            QTimer.singleShot(0, self.emit_data_ready_once)
            return
        self._awaiting_data = True
        QTimer.singleShot(_LOAD_WATCHDOG_MS, self.on_load_watchdog_timeout)
        QTimer.singleShot(0, load)

    def data_loaded(self) -> None:
        """A workflow's samples finished loading."""
        if self._awaiting_data:
            self._awaiting_data = False
            QTimer.singleShot(_SETTLE_MS, self.emit_data_ready_once)
        else:
            self.emit_data_ready_once()

    def emit_data_ready_once(self) -> None:
        if not self._data_ready_emitted:
            logger.info("Emitting data_ready")
            self._data_ready_emitted = True
            self._data_ready.emit()

    def on_load_watchdog_timeout(self) -> None:
        """Opens the workspace anyway, with a warning, if the handed-over load stalled.

        Most likely one sample's FCS file stalled the reload (see
        WorkflowService.reload_fcs_data); silently cross-fading into samples and
        gates showing 0 events would hide that.
        """
        if self._awaiting_data:
            self._awaiting_data = False  # warn once; data_loaded() then has nothing to wait for
            logger.error(
                "FCS reload did not complete within 45s — forcing UI to show anyway. "
                "Samples/gates may display as empty or 0 events until the load finishes."
            )
            show_warning(
                self._dialog_parent,
                "Workspace Load Taking Too Long",
                "Sample data is still loading after 45 seconds, so the workspace is "
                "opening before it's finished.\n\n"
                "Some samples or gates may show 0 events until loading completes in "
                "the background. If this persists, check the logs for a stuck FCS file.",
            )
        self.emit_data_ready_once()

    @staticmethod
    def _start_numba_warmup() -> None:
        """Pre-compiles UMAP's numba kernels on a thread, only once Phase 2 is built.

        Not earlier: numba's JIT holds the GIL through most of a compile, so
        alongside startup's own CPU-bound construction it contended for 100s+
        (from ~3s alone) and blocked the Qt event loop, so the daemon looked
        hung. After `panel_ready` it only competes with idle time.
        """
        # karcytics: allow KS360 - off the Phase 1 path
        from ..analysis.numba_warmup import warmup_numba_jit

        warmup_numba_jit()
