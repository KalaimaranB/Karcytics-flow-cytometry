"""A checklist of statistics, each with a help popover saying when to use it."""

from __future__ import annotations

from collections.abc import Iterable

from karcytics_sdk.plugin.components import BioHelpButton
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QVBoxLayout, QWidget

from ...analysis.statistics import StatType
from .checkbox_style import checkbox_qss

STAT_HELP = {
    StatType.COUNT: "<b>Count</b><br>Total number of events (cells/particles) in the population.<br><br><i>When to use:</i> Useful for quantifying absolute yield or analyzing absolute counts from volumetric data.",
    StatType.MEAN: "<b>Arithmetic Mean</b><br>The average fluorescence intensity.<br><br><i>When to use:</i> Use for linear data (like FSC or SSC). <b>Not recommended</b> for log-scaled fluorescence, as outliers heavily skew the mean.",
    StatType.MEDIAN: "<b>Median</b><br>The 50th percentile of fluorescence intensity.<br><br><i>When to use:</i> The standard metric for reporting fluorescence intensity. Robust against outliers and highly skewed log-normal distributions.",
    StatType.GEOMETRIC_MEAN: "<b>Geometric Mean</b><br>The average of the logarithmic values.<br><br><i>When to use:</i> Good for log-normally distributed fluorescence data. Often behaves similarly to the median.",
    StatType.MODE: "<b>Mode</b><br>The most frequent value (the peak of the histogram).<br><br><i>When to use:</i> Useful when comparing the primary peak position of a highly skewed or bimodal population.",
    StatType.SD: "<b>Standard Deviation (SD)</b><br>Measures the absolute spread of the data.<br><br><i>When to use:</i> Typically used on linear channels (like FSC/SSC) to quantify the width of a population.",
    StatType.CV: "<b>Coefficient of Variation (CV)</b><br>The standard deviation divided by the mean, expressed as a percentage.<br><br><i>When to use:</i> Critical for assessing peak sharpness in fluorescence channels. A high CV indicates a very broad, spread-out population.",
    StatType.MFI: "<b>Median Fluorescence Intensity (MFI)</b><br>Exactly the same as Median, but explicitly names Fluorescence.<br><br><i>When to use:</i> The standard choice for comparing expression levels of a fluorescent marker between samples.",
    StatType.PERCENT_PARENT: "<b>% Parent</b><br>The fraction of events relative to the immediate parent gate.<br><br><i>When to use:</i> Shows the step-by-step breakdown of your gating hierarchy (e.g. % CD4+ out of T-cells).",
    StatType.PERCENT_GRANDPARENT: "<b>% Grandparent</b><br>The fraction of events relative to the parent of the parent gate.<br><br><i>When to use:</i> Skips one generation, useful if the immediate parent is just a technical gate (like a doublet discriminator).",
    StatType.PERCENT_TOTAL: "<b>% Total</b><br>The fraction of events relative to all events in the sample.<br><br><i>When to use:</i> Represents the absolute frequency of this population within the entire un-gated tube.",
    StatType.MIN: "<b>Minimum</b><br>The lowest channel value in the population.<br><br><i>When to use:</i> Used primarily for quality control or verifying gate boundaries.",
    StatType.MAX: "<b>Maximum</b><br>The highest channel value in the population.<br><br><i>When to use:</i> Useful for detecting off-scale events or saturation.",
}

DEFAULT_STATS = frozenset({StatType.COUNT, StatType.PERCENT_PARENT, StatType.MFI})


class StatPicker(QWidget):
    """One checkbox per statistic; ★ marks those computed on a channel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatsCheckboxPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._boxes: dict[StatType, QCheckBox] = {}
        for stat in StatType:
            box = QCheckBox(stat.label + (" ★" if stat.needs_channel else ""))
            box.setToolTip(STAT_HELP[stat])
            box.setChecked(stat in DEFAULT_STATS)
            help_button = BioHelpButton()
            help_button.setHelpText(STAT_HELP[stat], f"{stat.label} Info")
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(box)
            row.addWidget(help_button)
            row.addStretch()
            layout.addLayout(row)
            self._boxes[stat] = box
        self._apply_theme_styles()

    def selected(self) -> list[StatType]:
        """The checked statistics, in list order."""
        return [stat for stat, box in self._boxes.items() if box.isChecked()]

    def set_selected(self, stats: Iterable[StatType]) -> None:
        chosen = set(stats)
        for stat, box in self._boxes.items():
            box.setChecked(stat in chosen)

    def _apply_theme_styles(self) -> None:
        self.setStyleSheet(checkbox_qss())  # rebuilt from the theme on each change
