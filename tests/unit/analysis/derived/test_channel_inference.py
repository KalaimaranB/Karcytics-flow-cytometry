"""DerivedAwareChannelInference — derived axes use their preferred scale."""

from karcytics_plugins.flow_cytometry.analysis.channel_inference import (
    DefaultChannelInference,
    DerivedAwareChannelInference,
)
from karcytics_plugins.flow_cytometry.analysis.derived import DerivedParameter
from karcytics_plugins.flow_cytometry.analysis.transforms import TransformType

LOG_RATIO = DerivedParameter("derived:a0000001", "R", "[A] / [B]", preferred_transform="log")
LIN_SUM = DerivedParameter("derived:b0000002", "S", "[A] + [B]", preferred_transform="linear")


def _strategy(definitions):
    return DerivedAwareChannelInference(lambda: definitions)


def test_derived_uses_preferred_transform():
    s = _strategy([LOG_RATIO, LIN_SUM])
    assert s.infer_transform(LOG_RATIO.param_id) == TransformType.LOG
    assert s.infer_transform(LIN_SUM.param_id) == TransformType.LINEAR


def test_unknown_derived_key_is_linear_not_biex():
    assert _strategy([]).infer_transform("derived:gone0000") == TransformType.LINEAR


def test_real_channels_defer_to_fallback():
    s = _strategy([LOG_RATIO])
    default = DefaultChannelInference()
    for ch in ("FSC-A", "SSC-H", "FITC-A", "Time", ""):
        assert s.infer_transform(ch) == default.infer_transform(ch)


def test_definitions_are_read_live():
    defs: list[DerivedParameter] = []
    s = _strategy(defs)
    assert s.infer_transform(LOG_RATIO.param_id) == TransformType.LINEAR
    defs.append(LOG_RATIO)
    assert s.infer_transform(LOG_RATIO.param_id) == TransformType.LOG
