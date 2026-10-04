"""The before/after preview for every sample at once, one row per sample.

Each row is an image rendered on a worker thread (the task scheduler), so
a dozen samples don't freeze the editor: a row shows a placeholder until
its first image arrives, and keeps its last image while a newer one is on
the way.
"""

from __future__ import annotations

from typing import Any

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.managed_task import FunctionalTask
from karcytics_sdk.plugin.theme_fallback import Fonts, theme_manager
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from karcytics_plugins.flow_cytometry.ui.widgets.compensation_preview import (
    VIEW_BOTH,
    PreviewRequest,
    render_preview_image,
)

logger = get_logger(__name__, "flow_cytometry")

_ROW_HEIGHT = 250
_MIN_ROW_WIDTH = 560
# All four plots side by side need more room than a pair.
_MIN_ROW_WIDTH_BOTH = 760
_SCROLLBAR_ALLOWANCE = 24  # so a row never needs a horizontal scrollbar
_STALE = {"stale": True}


class CompensationPreviewGrid(QScrollArea):
    """A scrolling column of per-sample previews, rendered in the background."""

    def __init__(self, scheduler: Any | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if scheduler is None:
            from karcytics_sdk.plugin.runtime_services import task_scheduler

            scheduler = task_scheduler
        self._scheduler = scheduler
        self._rows: dict[str, QLabel] = {}  # by sample id
        self._pending: dict[str, str] = {}  # task id → sample id
        # Bumped on every request, so renders already queued for an older
        # one give up instead of drawing what nobody will see.
        self._generation = 0
        self._is_alive = True

        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("CompensationPreviewGrid")
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._message = QLabel()
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._message)
        self._layout.addStretch()
        self.setWidget(content)
        theme_manager.apply_style(
            content,
            "#CompensationPreviewGrid { background: {BG_DARKEST}; }"
            f" QLabel {{ color: {{FG_DISABLED}}; font-size: {Fonts.SIZE_SMALL}px;"
            " background: {BG_DARK}; border: 1px dashed {BORDER}; border-radius: 4px; }",
        )

        scheduler.task_finished.connect(self._on_task_finished)
        scheduler.task_error.connect(self._on_task_error)
        self.destroyed.connect(self.cleanup)

    # ── Public API ────────────────────────────────────────────────────

    def show_requests(self, requests: list[tuple[str, str, PreviewRequest | str]]) -> None:
        """Show one row per ``(sample id, sample name, request)``, in order.

        A string in place of a request is shown as that row's message (the
        sample can't be previewed).
        """
        self._generation += 1
        self._pending.clear()
        self._message.setVisible(not requests)
        wanted = {sample_id for sample_id, _, _ in requests}
        for sample_id in [s for s in self._rows if s not in wanted]:
            self._rows.pop(sample_id).deleteLater()

        ratio = self.devicePixelRatioF()
        for position, (sample_id, name, request) in enumerate(requests):
            row = self._row(sample_id, position)
            if isinstance(request, str):
                row.setPixmap(QPixmap())
                row.setText(request)
                continue
            if row.pixmap().isNull():
                row.setText(f"Rendering {name}…")  # placeholder until the first image
            wide = request.view == VIEW_BOTH
            width = max(
                self.width() - _SCROLLBAR_ALLOWANCE, _MIN_ROW_WIDTH_BOTH if wide else _MIN_ROW_WIDTH
            )
            self._submit(sample_id, request, width, ratio)

    def show_message(self, message: str) -> None:
        self.show_requests([])
        self._message.setText(message)

    def cleanup(self) -> None:
        if not self._is_alive:
            return
        self._is_alive = False
        self._generation += 1
        for signal, slot in (
            (self._scheduler.task_finished, self._on_task_finished),
            (self._scheduler.task_error, self._on_task_error),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass  # already disconnected

    # ── Rows ──────────────────────────────────────────────────────────

    def _row(self, sample_id: str, position: int) -> QLabel:
        row = self._rows.get(sample_id)
        if row is None:
            row = QLabel()
            row.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.setFixedHeight(_ROW_HEIGHT)
            self._rows[sample_id] = row
        # Row 0 of the layout is the message label.
        if self._layout.indexOf(row) != position + 1:
            self._layout.insertWidget(position + 1, row)
        return row

    def _submit(self, sample_id: str, request: PreviewRequest, width: int, ratio: float) -> None:
        generation = self._generation

        def _render() -> dict:
            if generation != self._generation:
                return _STALE
            result = render_preview_image(request, width, _ROW_HEIGHT, ratio)
            result["pixel_ratio"] = ratio
            return result

        task = FunctionalTask(_render, "flow_cytometry", f"Compensation preview: {sample_id}")
        worker = self._scheduler.submit(task, None)
        self._pending[str(getattr(worker, "task_id", ""))] = sample_id

    def _on_task_finished(self, task_id: str, results: dict) -> None:
        sample_id = self._pending.pop(str(task_id), None)
        row = self._rows.get(sample_id) if sample_id is not None else None
        if not self._is_alive or row is None or not results.get("image_data"):
            return
        image = QImage(
            results["image_data"],
            results["width"],
            results["height"],
            QImage.Format.Format_RGBA8888,
        ).copy()  # the buffer is freed with ``results``
        image.setDevicePixelRatio(results.get("pixel_ratio", 1.0))
        row.setText("")
        row.setPixmap(QPixmap.fromImage(image))

    def _on_task_error(self, task_id: str, message: str) -> None:
        sample_id = self._pending.pop(str(task_id), None)
        row = self._rows.get(sample_id) if sample_id is not None else None
        if not self._is_alive or row is None:
            return
        logger.warning("Compensation preview failed for %s: %s", sample_id, message)
        row.setPixmap(QPixmap())
        row.setText("Couldn't render this sample's preview.")
