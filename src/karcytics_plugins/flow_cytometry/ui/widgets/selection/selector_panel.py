"""Composed sample + population selector: the single integration point used
by StatisticsExplorer and ComparisonsViewer in place of each tab building
its own sample checklist and population tree.

There used to be a separate checkable sample list here alongside the
population grid, but the grid's columns already ARE every experiment
sample — a population's cell is only enabled for samples it actually
applies to, and a whole sample's column can be included/excluded with one
column-header click. A second widget answering the same "which samples"
question independently was redundant for every plot type except one
(Pseudocolor Overlay's "exactly one sample" constraint), which the grid
itself now enforces directly via `PopulationSelectionPopup.
set_single_sample_mode()`. See that module for the constraint's mechanics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .population_selection_popup import PopulationSelectionPopup

if TYPE_CHECKING:
    from karcytics_plugins.flow_cytometry.analysis.experiment import Sample


def _get_theme_tokens():
    from karcytics_sdk.plugin.theme_fallback import Colors

    return Colors


def _section_label(text: str) -> QLabel:
    Colors = _get_theme_tokens()
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {Colors.FG_SECONDARY}; font-weight: bold; font-size: 11px;"
        " text-transform: uppercase; letter-spacing: 0.5px;"
    )
    return lbl


class SampleAndPopulationSelector(QWidget):
    """A population-selection popup trigger — despite the name (kept for API
    stability), there's now exactly one section: the grid IS the sample
    selector too, via its column headers. See module docstring for why the
    once-separate sample checklist is gone.

    Signals:
        selectionChanged: emitted whenever checked samples or populations
            change — the one signal callers need to re-run their compute/plot.
    """

    selectionChanged = pyqtSignal()

    def __init__(
        self,
        *,
        multi_population: bool = True,
        population_help_text: str = (
            "Select which populations to include, per sample. Click 'Edit "
            "Population Selection' to open the picker — check any cell to "
            "include that population for that sample, click a population's "
            "name to toggle it for every sample, or click a sample's column "
            "header to toggle every population for that sample."
        ),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._samples: dict[str, Sample] = {}

        from karcytics_sdk.plugin.components import BioHelpButton, SecondaryButton

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        pop_hdr = QHBoxLayout()
        pop_hdr.addWidget(_section_label("Populations"))
        pop_help = BioHelpButton()
        pop_help.setHelpText(population_help_text, "Populations")
        pop_hdr.addWidget(pop_help)
        pop_hdr.addStretch()
        layout.addLayout(pop_hdr)

        self._summary_lbl = QLabel("No populations selected.")
        self._summary_lbl.setWordWrap(True)
        layout.addWidget(self._summary_lbl)

        self.population_edit_button = SecondaryButton("🔲 Edit Population Selection")
        self.population_edit_button.clicked.connect(self._open_population_popup)
        layout.addWidget(self.population_edit_button)

        self.population_selector = PopulationSelectionPopup(self)
        self.population_selector.set_multi_select(multi_population)
        self._apply_summary_styles()

        self.population_selector.selectionChanged.connect(self._on_populations_changed)

    def refresh(self, samples: dict[str, Sample]) -> None:
        """Repopulate from {sample_id: Sample}, preserving prior checks."""
        self._samples = samples
        self.population_selector.refresh(samples)
        self.selectionChanged.emit()

    def set_multi_population(self, enabled: bool) -> None:
        self.population_selector.set_multi_select(enabled)

    def set_sample_mode(self, single: bool) -> None:
        """Force single-sample selection for plot types that are only
        defined for one sample (e.g. Pseudocolor Overlay).
        """
        self.population_selector.set_single_sample_mode(single)

    def get_checked_sample_ids(self) -> list[str]:
        """Every sample id with at least one checked population, ordered to
        match `self._samples` rather than arbitrary set order.
        """
        active = {sid for sid, _nid, _label in self.get_checked_populations()}
        return [sid for sid in self._samples if sid in active]

    def get_checked_populations(self) -> list[tuple[str, str | None, str]]:
        return self.population_selector.get_checked_populations()

    def _open_population_popup(self) -> None:
        self.population_selector.show_near(self.population_edit_button)

    def _on_populations_changed(self) -> None:
        self._summary_lbl.setText(self.population_selector.summary_text())
        self.selectionChanged.emit()

    def _apply_summary_styles(self) -> None:
        Colors = _get_theme_tokens()
        self._summary_lbl.setStyleSheet(
            f"color: {Colors.FG_SECONDARY}; font-size: 11px; background: transparent;"
        )
