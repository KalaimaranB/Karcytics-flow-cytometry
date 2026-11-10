"""Auto gating: splits a population into ordinary, editable gates, and records why.

Three methods share everything except how the view to split is chosen
(``views.py``; names in ``models.METHODS``). The Auto Gating tab talks only to
an :class:`~.engine.AutoGateEngine`; :class:`~.gating_engine.GatingEngine` is
the one there is, and :class:`~.commit.ProposalCommitter` adds accepted splits.
A gating template (``template.py``) is run by :class:`~.template_runner.TemplateRunner`.
"""

from .commit import ProposalCommitter
from .engine import AutoGateEngine
from .gating_engine import GatingEngine
from .models import METHODS, MethodInfo, StepRequest, method
from .template_runner import TemplateRunner

__all__ = [
    "METHODS",
    "AutoGateEngine",
    "GatingEngine",
    "MethodInfo",
    "ProposalCommitter",
    "StepRequest",
    "TemplateRunner",
    "method",
]
