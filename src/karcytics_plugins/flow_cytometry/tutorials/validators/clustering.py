"""Checks on Population Analysis: UMAP/HDBSCAN, FlowSOM and PhenoGraph runs."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np

from ...analysis.clustering.describe import HI
from ...analysis.state import FlowState
from ...ui.academy_context import AcademyContext
from .base import FlowUIValidator, FlowValidator

if TYPE_CHECKING:
    from ...ui.academy_context import ClusterResultsSnapshot, PopulationAnalysisSnapshot
    from ...ui.widgets.cluster_map_view import ClusterMapView
    from ...ui.widgets.flowsom_tree import FlowsomTreeView
    from ...ui.widgets.phenograph_graph import PhenographGraphView


class UmapSampleSelectedValidator(FlowUIValidator):
    """Verifies the Population Analysis sidebar's sample combo shows a specific sample."""

    def __init__(self, sample_substr: str) -> None:
        self._sample = sample_substr.lower()

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        pa = _population_analysis(ui)
        if pa is None:
            return self.log_failure("Population analysis viewer missing.")
        current = pa.sample_label.lower()
        if self._sample not in current:
            return self.log_failure(f"Selected sample is '{current}', expected '{self._sample}'.")
        return True


class UmapGateSelectedValidator(FlowUIValidator):
    """Verifies the Population Analysis sidebar's population/gate combo matches a target."""

    def __init__(self, gate_substr: str) -> None:
        self._gate = gate_substr.lower()

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        pa = _population_analysis(ui)
        if pa is None:
            return self.log_failure("Population analysis viewer missing.")
        current = pa.gate_label.lower()
        if self._gate not in current:
            return self.log_failure(f"Selected gate is '{current}', expected '{self._gate}'.")
        return True


class UmapChannelExcludedValidator(FlowUIValidator):
    """Verifies specific channels (by raw FCS channel key) are unchecked in the
    Population Analysis channel list, and every other channel stays checked.
    """

    def __init__(self, *excluded_channel_keys: str) -> None:
        self._excluded = {k.lower() for k in excluded_channel_keys}

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        pa = _population_analysis(ui)
        if pa is None:
            return self.log_failure("Population analysis viewer missing.")
        checks = pa.channel_checks
        if not checks:
            return self.log_failure("Channel list is empty — no sample selected yet.")

        for channel, is_checked in checks.items():
            key = channel.lower()
            if key in self._excluded and is_checked:
                return self.log_failure(f"Channel '{key}' should be excluded but is still checked.")
            if key not in self._excluded and not is_checked:
                return self.log_failure(f"Channel '{key}' should stay included but is unchecked.")
        return True


class UmapRunNameProvidedValidator(FlowUIValidator):
    """Verifies the Population Analysis run-name field is non-empty."""

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        pa = _population_analysis(ui)
        if pa is None:
            return self.log_failure("Population analysis viewer missing.")
        if not pa.run_name.strip():
            return self.log_failure("Run name is empty.")
        return True


class UmapSubsampleValueValidator(FlowUIValidator):
    """Verifies the Population Analysis subsample-events slider matches a target percentage."""

    def __init__(self, expected_pct: int) -> None:
        self._expected = expected_pct

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        pa = _population_analysis(ui)
        if pa is None:
            return self.log_failure("Population analysis viewer missing.")
        current = pa.subsample_percent
        if current != self._expected:
            return self.log_failure(f"Subsample is {current}%, expected {self._expected}%.")
        return True


class UmapHdbscanEnabledValidator(FlowUIValidator):
    """Verifies the Population Analysis HDBSCAN checkbox is checked."""

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        pa = _population_analysis(ui)
        if pa is None:
            return self.log_failure("Population analysis viewer missing.")
        if not pa.hdbscan_enabled:
            return self.log_failure("HDBSCAN checkbox is not checked.")
        return True


class UmapResultsReadyValidator(FlowUIValidator):
    """Verifies a UMAP run has fully finished: real results are in, and neither
    the background analysis nor the animation is still in flight.

    Mirrors the same three-flag check ``_check_transition_to_results()``
    uses internally, so this reports "ready" at exactly the moment the
    real UI would itself transition to showing results.
    """

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        pa = _population_analysis(ui)
        if pa is None:
            return self.log_failure("Population analysis viewer missing.")
        if pa.is_running:
            return self.log_failure("Analysis is still running.")
        if pa.is_animating:
            return self.log_failure("Animation is still playing.")
        if not pa.has_results:
            return self.log_failure("No results yet.")
        return True


class ClusterResultsTabActiveValidator(FlowUIValidator):
    """Verifies the results panel's own sub-tab widget (Plot Gallery /
    Interactive Map / Population Statistics) is showing a specific tab.
    """

    def __init__(self, tab_label: str) -> None:
        self._label = tab_label.lower()

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        panel = _results_panel(ui)
        if panel is None:
            return self.log_failure("Cluster results tabs not available yet.")
        current = panel.tab_label.lower()
        if self._label not in current:
            return self.log_failure(f"Active results tab is '{current}', expected '{self._label}'.")
        return True


class UmapMarkerColoredValidator(FlowUIValidator):
    """Verifies the Interactive Map's marker/cluster-ID dropdown is showing a specific marker."""

    def __init__(self, label_substr: str) -> None:
        self._label = label_substr.lower()

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        panel = _results_panel(ui)
        label = panel.color_label if panel is not None else None
        if label is None:
            return self.log_failure("Interactive map combo not available yet.")
        current = label.lower()
        if self._label not in current:
            return self.log_failure(
                f"Interactive map is showing '{current}', expected '{self._label}'."
            )
        return True


def _population_analysis(ui: AcademyContext) -> PopulationAnalysisSnapshot | None:
    viewer = ui.population_analysis
    return viewer.academy_snapshot() if viewer is not None else None


def _results_panel(ui: AcademyContext) -> ClusterResultsSnapshot | None:
    """The clustering results on screen, if any."""
    pa = _population_analysis(ui)
    return pa.results if pa is not None else None


def _flowsom_tree(ui: AcademyContext) -> FlowsomTreeView | None:
    """The FlowSOM Tree view of the results on screen, if a FlowSOM run is showing."""
    panel = _results_panel(ui)
    return panel.tree if panel is not None else None


class ClusteringMethodValidator(FlowUIValidator):
    """The Population Analysis Algorithm menu is set to ``method_key``."""

    def __init__(self, method_key: str) -> None:
        self._key = method_key

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        pa = _population_analysis(ui)
        if pa is None or pa.method_key != self._key:
            return self.log_failure(f"Algorithm isn't '{self._key}'.")
        return True


class NewRunSelectedValidator(FlowUIValidator):
    """History shows [ New Run ]: the settings are editable again."""

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        pa = _population_analysis(ui)
        if pa is None or not pa.new_run_selected:
            return self.log_failure("A past run is selected in History.")
        return True


class FlowsomResultsReadyValidator(FlowUIValidator):
    """A FlowSOM run finished and its tree is on screen."""

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        pa = _population_analysis(ui)
        if pa is None or pa.is_running:
            return self.log_failure("FlowSOM is still running.")
        if _flowsom_tree(ui) is None:
            return self.log_failure("No FlowSOM tree on screen yet.")
        return True


class FlowsomColorValidator(FlowUIValidator):
    """The FlowSOM tree is coloured by ``marker``; ``on_found`` gets the tree view."""

    def __init__(self, marker: str, on_found: Callable[[Any], None] | None = None) -> None:
        self._marker = marker.casefold()
        self._on_found = on_found

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        tree = _flowsom_tree(ui)
        if tree is None:
            return self.log_failure("No FlowSOM tree on screen.")
        if not tree.academy_snapshot().color_label.casefold().endswith(self._marker):
            return self.log_failure(f"Tree isn't coloured by '{self._marker}'.")
        if self._on_found is not None:
            self._on_found(tree)
        return True


class FlowsomKValidator(FlowUIValidator):
    """The FlowSOM run on screen is cut into ``k`` metaclusters; ``on_found`` gets the tree."""

    def __init__(self, k: int, on_found: Callable[[Any], None] | None = None) -> None:
        self._k = k
        self._on_found = on_found

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        tree = _flowsom_tree(ui)
        if tree is None or tree.academy_snapshot().run.get("k") != self._k:
            return self.log_failure(f"The run isn't at k = {self._k}.")
        if self._on_found is not None:
            self._on_found(tree)
        return True


def clusters_positive_for(view: ClusterMapView, marker: str) -> list[str]:
    """Tags of a cluster map's clusters that are + for ``marker`` ("M0", "C3", ...), largest first."""

    snap = view.academy_snapshot()
    return [
        snap.method.tag(summary.cluster)
        for summary in snap.summaries
        if any(
            m.casefold() == marker.casefold() and level >= HI
            for m, level in zip(summary.markers, summary.level, strict=True)
        )
    ]


metaclusters_positive_for = clusters_positive_for


def _phenograph_graph(ui: AcademyContext) -> PhenographGraphView | None:
    """The Cluster Graph view of the results on screen, if a PhenoGraph run is showing."""
    panel = _results_panel(ui)
    return panel.graph if panel is not None else None


class PhenographResultsReadyValidator(FlowUIValidator):
    """A PhenoGraph run finished and its cluster graph is on screen; ``on_found`` gets the view."""

    def __init__(self, on_found: Callable[[Any], None] | None = None) -> None:
        self._on_found = on_found

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        pa = _population_analysis(ui)
        if pa is None or pa.is_running:
            return self.log_failure("PhenoGraph is still running.")
        graph = _phenograph_graph(ui)
        if graph is None:
            return self.log_failure("No cluster graph on screen yet.")
        if self._on_found is not None:
            self._on_found(graph)
        return True


class PhenographColorValidator(FlowsomColorValidator):
    """The cluster graph is coloured by ``marker``; ``on_found`` gets the graph view."""

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        graph = _phenograph_graph(ui)
        if graph is None:
            return self.log_failure("No cluster graph on screen.")
        if not graph.academy_snapshot().color_label.casefold().endswith(self._marker):
            return self.log_failure(f"Graph isn't coloured by '{self._marker}'.")
        if self._on_found is not None:
            self._on_found(graph)
        return True


class PhenographResolutionValidator(FlowUIValidator):
    """The PhenoGraph run on screen is clustered at ``resolution``; ``on_found`` gets the graph."""

    def __init__(self, resolution: float, on_found: Callable[[Any], None] | None = None) -> None:
        self._resolution = resolution
        self._on_found = on_found

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        graph = _phenograph_graph(ui)
        value = graph.academy_snapshot().run.get("resolution") if graph is not None else None
        if value is None or abs(float(value) - self._resolution) > 1e-6:  # noqa: PLR2004
            return self.log_failure(f"The run isn't at resolution {self._resolution}.")
        if self._on_found is not None:
            self._on_found(graph)
        return True


class UmapBestBCellClusterValidator(FlowUIValidator):
    """Computes which real HDBSCAN cluster is this run's B-cell population —
    the one with the largest *contrast* between the given marker and every
    other marker (mean marker expression minus the mean of all other
    markers' means) — and verifies the user has isolated exactly that row
    in Export Populations: its checkbox is the only one checked (cluster
    -1, HDBSCAN's noise bucket, is never a candidate and must be unchecked
    like everything else), and its name field reads the expected name.

    A pure "highest marker expression, ties broken by lowest everything
    else" ranking (lexicographic on marker expression first) can pick a
    cluster that's elevated on *every* marker — e.g. a doublet/artifact
    population — over a cluster with a clean single-marker-positive
    profile, since the marker-expression term dominates the comparison
    before the "everything else" term ever matters. The contrast score
    instead rewards clusters that are specifically high on the target
    marker and specifically low elsewhere, which is what actually
    identifies a real single-lineage-positive population.

    Cluster ID *numbering* isn't stable run-to-run (only the clustering
    itself is, for fixed params/seed), so this never hardcodes an ID —
    ``on_progress``, if given, is called with a fresh instruction string
    naming the real, freshly-computed cluster ID on every poll, the same
    live-bubble-text idiom ``TutorialFilesProvisionedValidator`` uses in
    course1.py.
    """

    def __init__(
        self,
        on_progress: Callable[[str], None] | None = None,
        marker_label_substr: str = "b220",
        expected_name: str = "UMAP B Cells",
    ) -> None:
        self._on_progress = on_progress
        self._marker_substr = marker_label_substr.lower()
        # Comparison is case-insensitive (`_expected_name`), but the bubble
        # instruction text should still show the properly-capitalized name
        # the user is asked to type — `_expected_name_display` keeps that
        # original casing instead of interpolating the lowercased form.
        self._expected_name_display = expected_name
        self._expected_name = expected_name.lower()

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:

        panel = _results_panel(ui)
        results = panel.results if panel is not None else None
        rows = panel.cluster_rows if panel is not None else {}
        if not results or not rows:
            return self.log_failure("Results panel not ready yet.")

        clusters = np.asarray(results.get("clusters"))
        intensities = np.asarray(results.get("intensities"))
        labels = results.get("channel_labels") or []
        if clusters.size == 0 or intensities.size == 0 or not labels:
            return self.log_failure("UMAP results incomplete.")

        marker_idx = next(
            (i for i, lbl in enumerate(labels) if self._marker_substr in lbl.lower()), None
        )
        if marker_idx is None:
            return self.log_failure(f"No channel label matches '{self._marker_substr}'.")

        real_ids = sorted({int(c) for c in clusters.tolist() if int(c) != -1})
        if not real_ids:
            return self.log_failure("No real (non-noise) clusters found.")

        means = {cid: intensities[clusters == cid].mean(axis=0) for cid in real_ids}
        num_channels = intensities.shape[1]

        def score(cid: int) -> float:
            m = means[cid]
            marker_mean = float(m[marker_idx])
            if num_channels <= 1:
                return marker_mean
            others_mean = float((m.sum() - m[marker_idx]) / (num_channels - 1))
            return marker_mean - others_mean

        best_cid = max(real_ids, key=score)

        if self._on_progress is not None:
            self._on_progress(
                "Scanning your run's real numbers 🔬<br><br>"
                f"**Cluster ID {best_cid}** has the sharpest contrast between the "
                "marker you colored the map by and every other marker — "
                "specifically high on that one, specifically low on the rest — "
                "that's your B-cell population.<br><br>"
                f"Uncheck every row EXCEPT **ID {best_cid}** — including ID -1, "
                "that's HDBSCAN's noise bucket, not a real population — then "
                f"rename ID {best_cid}'s field to **{self._expected_name_display}**."
            )

        return self._rows_match_expected(rows, best_cid)

    def _rows_match_expected(self, rows: dict[Any, tuple[bool, str]], best_cid: int) -> bool:
        for cid, (checked, name) in rows.items():
            should_check = int(cid) == best_cid
            if checked != should_check:
                return self.log_failure(
                    f"Cluster {cid} checked={checked}, expected {should_check}."
                )
            if should_check and name.strip().lower() != self._expected_name:
                return self.log_failure(
                    f"Best cluster name is '{name}', expected '{self._expected_name}'."
                )
        return True


class ClusteredRunValidator(FlowValidator):
    """A sample whose name contains ``sample_name`` has a UMAP run with clusters."""

    def __init__(self, sample_name: str) -> None:
        self._sample_name = sample_name.casefold()

    def validate_flow(self, app_state: FlowState) -> bool:
        samples = app_state.data.experiment.samples
        for key, runs in app_state.data.umap_results.items():
            sample = samples.get(key.split("::", 1)[0])
            if sample is None or self._sample_name not in sample.display_name.casefold():
                continue
            if any(run.get("clusters") is not None for run in runs):
                return True
        return self.log_failure(f"No clustered run on '{self._sample_name}'.")
