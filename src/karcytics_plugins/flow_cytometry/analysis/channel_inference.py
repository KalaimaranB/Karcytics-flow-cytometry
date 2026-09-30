from collections.abc import Callable, Iterable
from typing import Protocol

from .derived.models import DerivedParameter, is_derived_key
from .transforms import TransformType


class ChannelInferenceStrategy(Protocol):
    """Strategy for inferring the default transformation for a channel."""

    def infer_transform(self, channel: str) -> TransformType: ...


class DefaultChannelInference:
    """Default logic: Linear for Scatter/Time, Biexponential for Fluorescence."""

    def infer_transform(self, channel: str) -> TransformType:
        if not channel:
            return TransformType.LINEAR

        is_fluo = not any(x in channel.upper() for x in ["FSC", "SSC", "TIME"])
        return TransformType.BIEXPONENTIAL if is_fluo else TransformType.LINEAR


class DerivedAwareChannelInference:
    """Derived parameters use their own preferred scale; others defer.

    The name heuristic would call every ``derived:`` key "fluorescence"
    (-> biexponential), which crushes ratio-scale data.

    Args:
        definitions: Returns the current definitions. A callable rather than
            a list because the experiment is swapped out on workspace load.
        fallback: Strategy for real detector channels.
    """

    def __init__(
        self,
        definitions: Callable[[], Iterable[DerivedParameter]],
        fallback: ChannelInferenceStrategy | None = None,
    ) -> None:
        self._definitions = definitions
        self._fallback = fallback or DefaultChannelInference()

    def infer_transform(self, channel: str) -> TransformType:
        if not is_derived_key(channel):
            return self._fallback.infer_transform(channel)
        for defn in self._definitions():
            if defn.param_id == channel:
                return TransformType(defn.preferred_transform)
        return TransformType.LINEAR
