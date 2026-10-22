"""Checks on the Sample Lens tab: its run, findings, gating path and proposals."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ...analysis.state import FlowState
from ...ui.academy_context import AcademyContext
from .base import FlowUIValidator

if TYPE_CHECKING:
    from ...ui.widgets.sample_lens.sample_lens_tab import SampleLensTab


class _LensValidator(FlowUIValidator):
    """A check on what the Sample Lens tab is showing."""

    def validate_ui(self, _app_state: FlowState, ui: AcademyContext) -> bool:
        lens = ui.sample_lens
        if lens is None:
            return self.log_failure("Sample Lens tab missing.")
        return self.validate_lens(lens)

    @abstractmethod
    def validate_lens(self, lens: SampleLensTab) -> bool:
        pass


class LensSampleValidator(_LensValidator):
    """The lens is open on a sample whose name contains ``sample_name``."""

    def __init__(self, sample_name: str) -> None:
        self._sample_name = sample_name.casefold()

    def validate_lens(self, lens: SampleLensTab) -> bool:
        sample = lens.model.sample
        if sample is None or self._sample_name not in sample.display_name.casefold():
            return self.log_failure(f"Lens isn't on '{self._sample_name}'.")
        return True


class LensRunMethodValidator(_LensValidator):
    """The lens's run was made with ``method_key`` (``umap_hdbscan``, ``flowsom``, ``phenograph``)."""

    def __init__(self, method_key: str) -> None:
        self._key = method_key

    def validate_lens(self, lens: SampleLensTab) -> bool:
        from ...analysis.clustering import method_of

        run = lens.model.run
        if run is None or method_of(run).key != self._key:
            return self.log_failure(f"The lens's run isn't a '{self._key}' run.")
        return True


class LensKValidator(_LensValidator):
    """The lens's FlowSOM run is cut into ``k`` metaclusters."""

    def __init__(self, k: int) -> None:
        self._k = k

    def validate_lens(self, lens: SampleLensTab) -> bool:
        run = lens.model.run
        if run is None or run.get("k") != self._k:
            return self.log_failure(f"The lens's run isn't at k = {self._k}.")
        return True


class LensResolutionValidator(_LensValidator):
    """The lens's PhenoGraph run is re-clustered at ``resolution`` and re-audited.

    ``on_found`` gets the lens on every passing poll.
    """

    def __init__(self, resolution: float, on_found: Callable[[Any], None] | None = None) -> None:
        self._resolution = resolution
        self._on_found = on_found

    def validate_lens(self, lens: SampleLensTab) -> bool:
        run = lens.model.run
        value = run.get("resolution") if run is not None else None
        if lens.model.is_reclustering:
            return self.log_failure("Still re-clustering.")
        if value is None or abs(float(value) - self._resolution) > 1e-6:  # noqa: PLR2004
            return self.log_failure(f"The lens's run isn't at resolution {self._resolution}.")
        if self._on_found is not None:
            self._on_found(lens)
        return True


class LensAgreementValidator(_LensValidator):
    """The lens compares its findings with other runs of the population.

    ``on_found`` gets ``[(finding, agreement), ...]`` on every poll, so a
    step's text can say which findings the other methods share.
    """

    def __init__(self, on_found: Callable[[list[tuple[Any, Any]]], None] | None = None) -> None:
        self._on_found = on_found

    def validate_lens(self, lens: SampleLensTab) -> bool:
        model = lens.model
        pairs = list(zip(model.findings, model.agreements, strict=False))
        if not pairs or not any(a.compared for _f, a in pairs):
            return self.log_failure("No other run of this population to compare with.")
        if self._on_found is not None:
            self._on_found(pairs)
        return True


class LensRunReadyValidator(_LensValidator):
    """The lens is judging the gates against a run with clusters."""

    def validate_lens(self, lens: SampleLensTab) -> bool:
        scope = lens.model.scope
        if scope is None or not scope.has_clusters:
            return self.log_failure("No clustered run selected in the lens.")
        return True


class LensPopulationSelectedValidator(_LensValidator):
    """The population named ``name`` is selected in the lens."""

    def __init__(self, name: str) -> None:
        self._name = name.casefold()

    def validate_lens(self, lens: SampleLensTab) -> bool:
        model = lens.model
        if model.selected_node_id is None:
            return self.log_failure("No population selected in the lens.")
        if model.population_name(model.selected_node_id).casefold() != self._name:
            return self.log_failure(f"Lens selection isn't '{self._name}'.")
        return True


def _lens_findings(lens: SampleLensTab, kind: Any, gate: str | None) -> list[Any]:
    """The lens's findings of ``kind``, naming the population ``gate`` if given."""
    from ...analysis.population_matching import PATH_SEP

    return [
        f
        for f in lens.model.findings
        if f.kind is kind
        and (gate is None or (f.population or "").rsplit(PATH_SEP, 1)[-1].casefold() == gate)
    ]


class LensFindingValidator(_LensValidator):
    """The lens shows (or, with ``present=False``, no longer shows) a finding of ``kind``.

    ``gate`` narrows it to findings naming that population. ``on_found`` gets
    the first matching finding on every poll, so a step's text can name the
    real cluster (cluster numbers differ run to run).
    """

    def __init__(
        self,
        kind: Any,
        gate: str | None = None,
        present: bool = True,
        on_found: Callable[[Any], None] | None = None,
    ) -> None:
        self._kind = kind
        self._gate = gate.casefold() if gate else None
        self._present = present
        self._on_found = on_found

    def validate_lens(self, lens: SampleLensTab) -> bool:
        found = _lens_findings(lens, self._kind, self._gate)
        if found and self._on_found is not None:
            self._on_found(found[0])
        if bool(found) != self._present:
            return self.log_failure(
                f"{self._kind.value} finding {'missing' if self._present else 'still shown'}."
            )
        return True


class LensNoFindingsValidator(_LensValidator):
    """The lens reports no findings at all; ``on_findings`` gets them on every poll.

    Runs differ, so a course branches on what the learner's own run reports.
    """

    def __init__(self, on_findings: Callable[[list[Any]], None] | None = None) -> None:
        self._on_findings = on_findings

    def validate_lens(self, lens: SampleLensTab) -> bool:
        findings = list(lens.model.findings)
        if self._on_findings is not None:
            self._on_findings(findings)
        if findings:
            return self.log_failure(f"{len(findings)} finding(s) left.")
        return True


class LensFindingFocusedValidator(_LensValidator):
    """The learner clicked a finding of ``kind``: its clusters are circled on the map."""

    def __init__(self, kind: Any, on_found: Callable[[Any], None] | None = None) -> None:
        self._kind = kind
        self._on_found = on_found

    def validate_lens(self, lens: SampleLensTab) -> bool:
        found = _lens_findings(lens, self._kind, None)
        if not found:
            return self.log_failure(f"No {self._kind.value} finding.")
        if self._on_found is not None:
            self._on_found(found[0])
        if not any(lens.emphasis == f.clusters for f in found):
            return self.log_failure(f"The {self._kind.value} finding hasn't been clicked.")
        return True


class LensFocusValidator(_LensValidator):
    """The gating path is (or isn't) in focus mode."""

    def __init__(self, on: bool = True) -> None:
        self._on = on

    def validate_lens(self, lens: SampleLensTab) -> bool:
        if lens.path.focused != self._on:
            return self.log_failure(f"Focus mode isn't {'on' if self._on else 'off'}.")
        return True


class LensColumnsValidator(_LensValidator):
    """The gating path shows ``columns`` plots per row (0: all in one row)."""

    def __init__(self, columns: int) -> None:
        self._columns = columns

    def validate_lens(self, lens: SampleLensTab) -> bool:
        if lens.path.columns != self._columns:
            return self.log_failure(f"Plots per row isn't {self._columns or 'All'}.")
        return True


class LensPlotViewValidator(_LensValidator):
    """The path plot whose caption ends in ``target`` is shown as ``view``."""

    def __init__(self, target: str, view: str) -> None:
        self._target = target.casefold()
        self._view = view

    def validate_lens(self, lens: SampleLensTab) -> bool:
        for caption, view in lens.path.shown_views():
            if caption.casefold().endswith(self._target):
                if view == self._view:
                    return True
                return self.log_failure(f"'{self._target}' plot isn't shown as {self._view}.")
        return self.log_failure(f"No '{self._target}' plot on the path.")


class LensProposalValidator(_LensValidator):
    """The lens is previewing proposed gates; ``on_found`` gets their marker pairs."""

    def __init__(self, on_found: Callable[[list[str]], None] | None = None) -> None:
        self._on_found = on_found

    def validate_lens(self, lens: SampleLensTab) -> bool:
        if lens.proposal is None or not lens.proposal.steps:
            return self.log_failure("No gate proposal shown.")
        if self._on_found is not None:
            self._on_found(proposal_axes(lens))
        return True


def proposal_axes(lens: SampleLensTab) -> list[str]:
    """Each proposed gate's markers, in order: ["B220 vs CD3", "CD4 vs CD8"]."""
    from ...analysis.clustering.describe import short_marker
    from ...analysis.fcs_io import get_channel_marker_label

    sample, proposal = lens.model.sample, lens.proposal
    fcs = sample.fcs_data if sample is not None else None

    def marker(channel: str) -> str:
        return short_marker(get_channel_marker_label(fcs, channel)) if fcs else channel

    return [
        " vs ".join(marker(c) for c in (step.gate.x_param, step.gate.y_param) if c)
        for step in (proposal.steps if proposal is not None else ())
    ]


class LensProposalAddedValidator(_LensValidator):
    """Proposed gates were added: the open sample has a gated "Cluster N" population.

    UMAP exports can carry the same default name, so they don't count.
    """

    def validate_lens(self, lens: SampleLensTab) -> bool:
        import re

        from ...analysis.population_matching import populations
        from ...analysis.sample_lens.scope import is_cluster_population

        sample = lens.model.sample
        names = [
            node.name or ""
            for _, node in (populations(sample) if sample else [])
            if not is_cluster_population(node)
        ]
        if not any(re.fullmatch(r"Cluster -?\d+", name) for name in names):
            return self.log_failure("No proposed 'Cluster N' gate in the tree yet.")
        return True
