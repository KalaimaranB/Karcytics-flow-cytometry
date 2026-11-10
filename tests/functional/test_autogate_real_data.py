"""Auto gating on real recordings (tests/data/fcs), not just planted blobs.

Real populations are lopsided and overlap, detectors clip at their limits, and
valleys are shallower than in synthetic data: the engine has to find the
obvious populations anyway, and still find nothing in an unstained tube.
"""

from __future__ import annotations

import pytest

from karcytics_plugins.flow_cytometry.analysis.autogate import GatingEngine, StepRequest
from karcytics_plugins.flow_cytometry.analysis.axis_manager import AxisManager
from karcytics_plugins.flow_cytometry.analysis.experiment import Sample
from karcytics_plugins.flow_cytometry.analysis.fcs_io import load_fcs
from karcytics_plugins.flow_cytometry.analysis.state import FlowState
from tests.fixtures.daemon import in_process_daemon

pytestmark = pytest.mark.functional

SCATTER = ("FSC-A", "SSC-A")


def _engine(fcs_test_data_dir, name: str) -> tuple[GatingEngine, tuple[str, ...]]:
    state = FlowState()
    fcs = load_fcs(str(fcs_test_data_dir / f"Specimen_001_{name}.fcs"), in_process_daemon)
    state.data.experiment.samples["s"] = Sample(sample_id="s", display_name=name, fcs_data=fcs)
    markers = tuple(c for c in fcs.events.columns if c not in (*SCATTER, "Time"))
    return GatingEngine(state, AxisManager(state)), markers


def _request(method_key: str, channels: tuple[str, ...]) -> StepRequest:
    return StepRequest(
        method_key, "s", None, channels, ("s",), x_channel="FSC-A", y_channel="SSC-A"
    )


@pytest.mark.parametrize("method_key", ["pairs", "pca"])
def test_dead_cells_are_found_in_a_stained_sample(fcs_test_data_dir, method_key):
    engine, markers = _engine(fcs_test_data_dir, "Sample A")
    proposal = engine.propose(_request(method_key, markers))

    assert not isinstance(proposal, str), proposal
    dead = [r for r in proposal.gated if "PI+" in r.name]
    assert dead and 0.03 < dead[0].fraction < 0.2  # noqa: PLR2004
    assert len(proposal.gated) >= 2  # noqa: PLR2004


def test_debris_is_cut_off_on_forward_scatter(fcs_test_data_dir):
    engine, _markers = _engine(fcs_test_data_dir, "Sample A")
    proposal = engine.propose(_request("valleys", SCATTER))

    assert not isinstance(proposal, str), proposal
    cells = max(proposal.gated, key=lambda r: r.fraction)
    assert cells.name.startswith("FSC-Amid") and cells.fraction > 0.8  # noqa: PLR2004


def test_an_unstained_tube_has_no_marker_split(fcs_test_data_dir):
    engine, markers = _engine(fcs_test_data_dir, "Blank")
    result = engine.propose(_request("pairs", markers))
    assert isinstance(result, str) and "No clear split" in result
