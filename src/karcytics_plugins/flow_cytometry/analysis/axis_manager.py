"""Axis manager for coordinate transformations and range management.

Decouples UI axis logic (GraphWindow, GroupPreview) from data logic.
Ensures consistent auto-ranging and scale synchronization across components.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from karcytics_sdk.plugin import CentralEventBus, get_logger

from . import events
from .channel_inference import ChannelInferenceStrategy, DerivedAwareChannelInference
from .constants import DERIVED_LOG_FLOOR, DERIVED_PREFIX
from .scaling import AxisScale, calculate_auto_range
from .transforms import TransformType

if TYPE_CHECKING:
    import pandas as pd

    from .state import FlowState

logger = get_logger(__name__, "flow_cytometry")


def _new_scale(channel: str, transform: TransformType) -> AxisScale:
    if channel.startswith(DERIVED_PREFIX):
        return AxisScale(transform_type=transform, log_floor=DERIVED_LOG_FLOOR)
    return AxisScale(transform_type=transform)


class AxisManager:
    """Coordinates axis scales and auto-ranging across the module.

    Publishes:
        events.AXIS_UPDATED(channel, scale):
            Published when a channel's scale is modified.
    """

    def __init__(
        self,
        state: FlowState,
        inference_strategy: ChannelInferenceStrategy | None = None,
    ):
        self._state = state
        self._inference_strategy = inference_strategy or DerivedAwareChannelInference(
            lambda: self._state.data.experiment.derived_parameters
        )
        if not hasattr(self._state.view, "fallback_scales"):
            self._state.view.fallback_scales = {}

    def get_scale(
        self,
        channel: str | None,
        sample_id: str | None = None,
        default_transform: TransformType | None = None,
    ) -> AxisScale:
        """Get the current scale for a channel from the sample's primary group."""
        if not channel:
            return AxisScale(transform_type=default_transform or TransformType.LINEAR)

        if not default_transform:
            default_transform = self._inference_strategy.infer_transform(channel)

        if sample_id:
            sample = self._state.data.experiment.samples.get(sample_id)
            if sample and sample.group_ids:
                group = self._state.data.experiment.groups.get(sample.group_ids[0])
                if group:
                    if channel not in group.channel_scales:
                        group.channel_scales[channel] = _new_scale(channel, default_transform)
                    return group.channel_scales[channel]

        if channel not in self._state.view.fallback_scales:
            self._state.view.fallback_scales[channel] = _new_scale(channel, default_transform)
        return self._state.view.fallback_scales[channel]

    def set_scale(
        self,
        channel: str,
        scale: AxisScale,
        notify: bool = True,
        sample_id: str | None = None,
    ):
        """Update a channel's scale in the sample's primary group and notify listeners."""
        saved = False
        if sample_id:
            sample = self._state.data.experiment.samples.get(sample_id)
            if sample and sample.group_ids:
                group = self._state.data.experiment.groups.get(sample.group_ids[0])
                if group:
                    group.channel_scales[channel] = scale.copy()
                    saved = True

        if not saved:
            self._state.view.fallback_scales[channel] = scale.copy()

        if notify:
            CentralEventBus.publish(events.AXIS_UPDATED, {"channel": channel, "scale": scale})

    def calculate_range(
        self, data: pd.Series, channel: str, sample_id: str | None = None
    ) -> tuple[float, float]:
        """Calculate the display range for a channel based on data and scale settings."""
        scale = self.get_scale(channel, sample_id)

        # If manual range is set, use it
        if scale.min_val is not None and scale.max_val is not None:
            return (scale.min_val, scale.max_val)

        # Otherwise auto-range
        data_np = data.to_numpy() if hasattr(data, "to_numpy") else np.asarray(data)
        return calculate_auto_range(data_np, scale.transform_type, scale.outlier_percentile)

    def update_auto_range(
        self, sample_id: str, channel: str, _axis_id: str = "x"
    ) -> tuple[float, float] | None:
        """Update the channel's scale with an auto-calculated range based on a sample."""
        sample = self._state.data.experiment.samples.get(sample_id)
        if not sample or not sample.has_data:
            return None

        assert sample.fcs_data is not None
        data = sample.fcs_data.events[channel]  # type: ignore
        new_range = self.calculate_range(data, channel, sample_id)

        scale = self.get_scale(channel, sample_id).copy()
        scale.min_val, scale.max_val = new_range
        self.set_scale(channel, scale, sample_id=sample_id)
        return new_range
