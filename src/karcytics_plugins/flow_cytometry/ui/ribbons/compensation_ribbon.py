"""Compensation ribbon — matrix calculation, import, and application.

Provides toolbar actions for:
- Calculating a spillover matrix from single-stain controls
- Extracting an embedded matrix from FCS metadata ($SPILL)
- Importing a matrix from CSV/TSV files
- Viewing and editing the active matrix
- Applying compensation to all samples
"""

from __future__ import annotations

from pathlib import Path

from karcytics_sdk.plugin import get_logger
from karcytics_sdk.plugin.components import PrimaryButton, SecondaryButton
from karcytics_sdk.plugin.dialogs import show_error, show_info, show_warning
from karcytics_sdk.plugin.theme_fallback import Colors
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QWidget,
)

from karcytics_plugins.flow_cytometry.analysis.compensation import (
    apply_compensation,
    calculate_spillover_matrix,
    export_matrix_to_csv,
    extract_spill_from_fcs,
    import_matrix_from_csv,
)
from karcytics_plugins.flow_cytometry.analysis.experiment import SampleRole
from karcytics_plugins.flow_cytometry.analysis.state import FlowState

logger = get_logger(__name__, "flow_cytometry")


class CompensationRibbon(QWidget):
    """Toolbar ribbon for compensation actions.

    Signals:
        compensation_changed: Emitted after matrix is computed/imported/applied.
        matrix_view_requested: Emitted to open the matrix editor dialog.
    """

    compensation_changed = pyqtSignal()
    matrix_view_requested = pyqtSignal()

    def __init__(self, state: FlowState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        btn_calc = PrimaryButton("🔬 Calculate Matrix")
        btn_calc.setToolTip(
            "Compute spillover matrix from single-stain controls.\n"
            "Requires samples tagged with role 'Single Stain'."
        )
        btn_calc.clicked.connect(self._on_calculate)
        layout.addWidget(btn_calc)

        btn_extract = SecondaryButton("📄 Extract from FCS")
        btn_extract.setObjectName("ExtractFCSButton")
        btn_extract.setToolTip(
            "Read the $SPILL/$SPILLOVER keyword embedded in an FCS file's metadata."
        )
        btn_extract.clicked.connect(self._on_extract_from_fcs)
        layout.addWidget(btn_extract)

        btn_import = SecondaryButton("📥 Import CSV")
        btn_import.setToolTip("Import a spillover matrix from a CSV or TSV file.")
        btn_import.clicked.connect(self._on_import_csv)
        layout.addWidget(btn_import)

        btn_export = SecondaryButton("📤 Export CSV")
        btn_export.setToolTip("Export the current spillover matrix to CSV.")
        btn_export.clicked.connect(self._on_export_csv)
        layout.addWidget(btn_export)

        btn_apply = PrimaryButton("✅ Apply to All")
        btn_apply.setObjectName("ApplyAllButton")
        btn_apply.setToolTip("Apply the current compensation matrix to all loaded samples.")
        btn_apply.clicked.connect(self._on_apply_all)
        layout.addWidget(btn_apply)

        btn_view = PrimaryButton("⚙️ View/Edit Matrix")
        btn_view.setToolTip(
            "Open the Compensation Editor to fine-tune the matrix and view side-by-side scatter plots."
        )
        btn_view.clicked.connect(self._on_view_matrix)
        layout.addWidget(btn_view)

        btn_toggle = SecondaryButton("🔄 Toggle Compensation")
        btn_toggle.setToolTip(
            "Toggle compensation on/off for all loaded samples to verify raw vs compensated states."
        )
        btn_toggle.clicked.connect(self._on_toggle_compensation)
        layout.addWidget(btn_toggle)

        layout.addStretch()

        self._apply_theme_styles()

    def _apply_theme_styles(self) -> None:
        """Dynamically refresh colors when theme changes."""
        self.setObjectName(self.__class__.__name__)
        self.setStyleSheet(
            f"QWidget#{self.objectName()} {{ background: {Colors.BG_DARK}; border-bottom: 1px solid {Colors.BORDER}; }}"
        )

    # ── Actions ───────────────────────────────────────────────────────

    def _on_calculate(self) -> None:
        """Calculate spillover matrix from single-stain control samples."""
        exp = self._state.data.experiment

        # Find single-stain samples
        single_stains = exp.get_samples_by_role(SampleRole.SINGLE_STAIN)
        ss_data = [s.fcs_data for s in single_stains if s.fcs_data is not None]

        if len(ss_data) < 2:  # noqa: PLR2004
            show_warning(
                self,
                "Insufficient Controls",
                f"Found {len(ss_data)} single-stain controls.\n\n"
                "You need at least 2 single-stain samples to compute a "
                "spillover matrix.\n\n"
                "Assign sample roles in the Properties panel by selecting "
                "each sample in the tree.",
            )
            return

        # Find optional unstained control
        unstained_samples = exp.get_samples_by_role(SampleRole.UNSTAINED)
        unstained = None
        if unstained_samples and unstained_samples[0].fcs_data:
            unstained = unstained_samples[0].fcs_data

        try:
            comp = calculate_spillover_matrix(ss_data, unstained=unstained)
            self._state.data.compensation = comp

            matrix_str = "\n".join([", ".join([f"{v:.3f}" for v in row]) for row in comp.matrix])
            show_info(
                self,
                "Matrix Computed",
                f"Successfully computed a {comp.n_channels}×{comp.n_channels} "
                f"spillover matrix from {len(ss_data)} single-stain controls.\n\n"
                "Channels:\n" + ", ".join(comp.channel_names) + f"\n\nMatrix Values:\n{matrix_str}",
            )

            self.compensation_changed.emit()
            logger.info("Spillover matrix computed: %d×%d", comp.n_channels, comp.n_channels)

        except Exception as exc:
            logger.error("Compensation calculation failed: %s", exc)
            show_error(
                self,
                "Computation Error",
                f"Failed to compute compensation matrix:\n{exc}",
            )

    def _on_extract_from_fcs(self) -> None:
        """Extract $SPILL/$SPILLOVER from the first sample with one."""
        exp = self._state.data.experiment

        for sample in exp.samples.values():
            if sample.fcs_data is None:
                continue

            comp = extract_spill_from_fcs(sample.fcs_data)
            if comp is not None:
                self._state.data.compensation = comp

                matrix_str = "\n".join(
                    [", ".join([f"{v:.3f}" for v in row]) for row in comp.matrix]
                )
                from PyQt6.QtCore import QTimer

                def show_dialog():
                    show_info(
                        self,
                        "Matrix Extracted",
                        f"Found embedded {comp.n_channels}×{comp.n_channels} "  # noqa: B023
                        f"spillover matrix in:\n{sample.display_name}\n\n"  # noqa: B023
                        "Channels:\n"
                        + ", ".join(comp.channel_names)  # noqa: B023
                        + f"\n\nMatrix Values:\n{matrix_str}",  # noqa: B023
                    )

                QTimer.singleShot(0, show_dialog)
                self.compensation_changed.emit()
                return

        from PyQt6.QtCore import QTimer

        def _show_no_matrix_warning():
            show_warning(
                self,
                "No Matrix Found",
                "None of the loaded FCS files contain a $SPILL or $SPILLOVER "
                "keyword in their metadata.\n\n"
                "You can compute a matrix from single-stain controls or "
                "import one from CSV instead.",
            )

        QTimer.singleShot(0, _show_no_matrix_warning)

    def _on_import_csv(self) -> None:
        """Import a spillover matrix from CSV/TSV."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Spillover Matrix",
            "",
            "CSV Files (*.csv *.tsv *.txt);;All Files (*)",
        )
        if not path:
            return

        try:
            comp = import_matrix_from_csv(Path(path))
            self._state.data.compensation = comp

            show_info(
                self,
                "Matrix Imported",
                f"Imported {comp.n_channels}×{comp.n_channels} matrix "
                f"from:\n{Path(path).name}\n\n"
                "Channels:\n" + ", ".join(comp.channel_names),
            )
            self.compensation_changed.emit()

        except Exception as exc:
            logger.error("Matrix import failed: %s", exc)
            show_error(self, "Import Error", f"Failed to import matrix:\n{exc}")

    def _on_export_csv(self) -> None:
        """Export the current matrix to CSV."""
        if self._state.data.compensation is None:
            show_info(
                self,
                "No Matrix",
                "No compensation matrix is currently loaded.\nCalculate or import one first.",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Spillover Matrix",
            "spillover_matrix.csv",
            "CSV Files (*.csv);;TSV Files (*.tsv)",
        )
        if not path:
            return

        try:
            export_matrix_to_csv(self._state.data.compensation, Path(path))
            show_info(
                self,
                "Matrix Exported",
                f"Spillover matrix saved to:\n{Path(path).name}",
            )
        except Exception as exc:
            logger.error("Matrix export failed: %s", exc)

    def _on_apply_all(self) -> None:
        """Apply compensation to all loaded samples."""
        comp = self._state.data.compensation
        if comp is None:
            show_info(
                self,
                "No Matrix",
                "No compensation matrix is loaded.\nCalculate, extract, or import one first.",
            )
            return

        exp = self._state.data.experiment
        applied_count = 0
        already_compensated_count = 0
        no_data_count = 0

        for sample in exp.samples.values():
            if sample.fcs_data is None:
                no_data_count += 1
                continue
            if sample.is_compensated:
                already_compensated_count += 1
                continue

            try:
                compensated_df = apply_compensation(sample.fcs_data, comp)
                sample.fcs_data.events = compensated_df
                sample.fcs_data.is_compensated = True
                sample.is_compensated = True
                applied_count += 1
            except Exception as exc:
                logger.warning("Compensation failed for %s: %s", sample.display_name, exc)

        msg = f"Compensation applied to {applied_count} sample(s)."
        if already_compensated_count > 0:
            msg += f"\n{already_compensated_count} sample(s) skipped (already compensated)."
        if no_data_count > 0:
            msg += f"\n{no_data_count} sample(s) skipped (no data)."

        show_info(self, "Compensation Applied", msg)
        self.compensation_changed.emit()
        logger.info(
            "Compensation applied: %d applied, %d already compensated, %d no data.",
            applied_count,
            already_compensated_count,
            no_data_count,
        )

    def _on_view_matrix(self) -> None:
        """Open the compensation editor dialog."""
        from karcytics_plugins.flow_cytometry.ui.widgets.compensation_editor_dialog import (
            CompensationEditorDialog,
        )

        if self._state.data.compensation is None:
            show_info(
                self,
                "No Matrix",
                "No compensation matrix is currently loaded.\n"
                "Calculate, extract, or import one first.",
            )
            return

        dialog = CompensationEditorDialog(self._state, self)
        if dialog.exec():
            # Dialog modified state.data.compensation, need to re-apply
            self._on_apply_all()

    def _on_toggle_compensation(self) -> None:
        """Toggle compensation on/off for all samples."""
        exp = self._state.data.experiment

        toggled_count = 0
        new_state = None

        for sample in exp.samples.values():
            if sample.fcs_data is None:
                continue

            if sample.fcs_data.raw_events is None:
                continue

            # If we haven't decided the target state yet, base it on the first sample
            if new_state is None:
                new_state = not sample.fcs_data.is_compensated

            if new_state:  # Turn ON
                if self._state.data.compensation:
                    compensated_df = apply_compensation(
                        sample.fcs_data, self._state.data.compensation
                    )
                    sample.fcs_data.events = compensated_df
                    sample.fcs_data.is_compensated = True
                    sample.is_compensated = True
                    toggled_count += 1
            else:  # Turn OFF
                sample.fcs_data.events = sample.fcs_data.raw_events.copy()
                sample.fcs_data.is_compensated = False
                sample.is_compensated = False
                toggled_count += 1

        if toggled_count > 0:
            state_str = "ON" if new_state else "OFF"
            logger.info(f"Compensation Toggled: Turned {state_str} for {toggled_count} samples.")
            self.compensation_changed.emit()
        else:
            show_info(
                self,
                "No Action",
                "Could not toggle compensation. Ensure samples have a raw data backup and a matrix is loaded.",
            )
