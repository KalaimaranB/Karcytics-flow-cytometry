"""Sample Lens: check one sample's gating against a clustering of its events.

Qt-free; the tab lives in ``ui/widgets/sample_lens/``.
"""

from .agreement import Agreement, OtherRun, agreements
from .audit import Finding, FindingKind, audit
from .edges import SampleCheck, check_across, edge_fraction
from .scope import NOISE, LensPopulation, RunScope, build_scope, final_populations
from .synthesis import ProposedGate, propose_gates

__all__ = [
    "NOISE",
    "Agreement",
    "OtherRun",
    "agreements",
    "Finding",
    "FindingKind",
    "LensPopulation",
    "ProposedGate",
    "RunScope",
    "SampleCheck",
    "audit",
    "build_scope",
    "check_across",
    "edge_fraction",
    "final_populations",
    "propose_gates",
]
