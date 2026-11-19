"""FCS channel + marker → the FPbase dye name the Spectral viewer looks up."""

import pytest

from karcytics_plugins.flow_cytometry.analysis.biology_services import fpbase_query_for_channel


@pytest.mark.parametrize(
    ("channel", "marker", "expected"),
    [
        ("APC-A", "CD45", "APC"),
        ("APC-Cy7-A", "CD8", "APC/Cy7"),
        ("PerCP-Cy5-5-A", "", "PerCP-Cy5.5"),
        ("PerCP-Cy5-5-A", "PI", "Propidium Iodide"),
        ("PE-Cy5-A", " 7-aad ", "7-AAD"),
        ("Pacific Blue-A", "CD3", "Pacific Blue"),
    ],
)
def test_fpbase_query_for_channel(channel, marker, expected):
    assert fpbase_query_for_channel(channel, marker) == expected
