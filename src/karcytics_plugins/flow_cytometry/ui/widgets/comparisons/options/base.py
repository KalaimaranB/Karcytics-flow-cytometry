"""Abstract base for all comparison plot options panels.

ISP: narrow interface — only get_config() and apply_theme() are required.
DIP: ComparisonsViewer depends on this, not on concrete panel classes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QWidget

if TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.state import FlowState


class IOptionsPanel(QWidget):
    """Single-responsibility: own the Qt controls for one plot type's settings.

    Subclasses must not contain rendering logic.  They are pure data-capture
    widgets whose only job is to return a config dict consumed by the renderer.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

    def get_config(self) -> dict:
        """Return the current control values as a plain dict.

        The dict is passed directly to IPlotRenderer.render() as **kwargs.
        Keys must match what the corresponding renderer expects.
        """
        raise NotImplementedError

    def apply_theme(self, colors: dict) -> None:
        """Re-style all child widgets using the supplied color palette dict.

        Called by ComparisonsViewer whenever the Karcytics theme changes.
        Receives a flat dict of color hex strings (e.g. 'fg_primary', 'bg_dark').
        """
        raise NotImplementedError

    def populate_channels(
        self, channels: list[tuple[str, str]], sample_id: str | None = None
    ) -> None:
        """Optional: populate channel dropdowns from (label, key) pairs.

        ``sample_id`` is the currently-active sample this channel list came
        from — panels that need to pull raw data on demand (e.g. for an
        Auto-Range button) can stash it. Concrete panels that expose channel
        pickers should override this. Default is a no-op so callers can call
        it unconditionally.
        """

    def bind_state(self, state: FlowState) -> None:
        """Optional: seed initial control values from the shared FlowState.

        Concrete panels that want to default to app-wide settings (e.g.
        mirroring the workspace tab's global render config) should override
        this. Default is a no-op so callers can call it unconditionally.
        """
