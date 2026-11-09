"""Auto gating: splits a population into ordinary, editable gates, and records why.

Three methods share everything except how the view to split is chosen
(``models.METHODS``). The Auto Gating tab talks only to an
:class:`~.engine.AutoGateEngine`; :class:`~.demo.DemoEngine` stands in for
the analysis until it is built.
"""

from .demo import DemoEngine
from .engine import AutoGateEngine
from .models import METHODS, MethodInfo, StepRequest, method

__all__ = ["METHODS", "AutoGateEngine", "DemoEngine", "MethodInfo", "StepRequest", "method"]
