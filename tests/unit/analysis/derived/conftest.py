"""Shared builders for derived-parameter tests.

Every builder produces the same small B220/CD45 panel:
FSC-A (no marker), FITC-A = B220, APC-A = CD45 (omittable).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import FCSData


def build_fcs(
    fitc=(10.0, 4.0),
    apc=(2.0, 4.0),
    *,
    with_apc: bool = True,
    with_raw: bool = True,
    name: str = "s",
) -> FCSData:
    cols = {"FSC-A": [float(i + 1) for i in range(len(fitc))], "FITC-A": list(fitc)}
    channels, markers = ["FSC-A", "FITC-A"], ["", "B220"]
    if with_apc:
        cols["APC-A"] = list(apc)
        channels.append("APC-A")
        markers.append("CD45")
    df = pd.DataFrame(cols)
    return FCSData(Path(f"{name}.fcs"), channels, markers, df, df.copy() if with_raw else None)


@pytest.fixture
def make_fcs():
    """Factory fixture: ``make_fcs(fitc=..., apc=..., with_apc=..., with_raw=...)``."""
    return build_fcs


@pytest.fixture
def make_sample():
    """Factory fixture: ``make_sample("a", **build_fcs_kwargs)`` -> loaded Sample."""

    def _make(sample_id: str, **kwargs) -> Sample:
        fcs = build_fcs(name=sample_id, **kwargs)
        return Sample(sample_id=sample_id, display_name=f"Sample {sample_id.upper()}", fcs_data=fcs)

    return _make
