"""FluorophoreService against a fake FPbase: matching, spectra, caching, going offline."""

from __future__ import annotations

import io
import json
import urllib.request

import pytest

from karcytics_plugins.flow_cytometry.analysis import biology_services
from karcytics_plugins.flow_cytometry.analysis.biology_services import FluorophoreService
from karcytics_plugins.flow_cytometry.analysis.constants import FPBASE_MAX_MATCHES

DYES = [
    {"name": "Fluorescein-Dextran (FITC)", "id": 1, "qy": 0.5, "extCoeff": 1, "emMax": 520,
     "exMax": 494, "spectra": [{"id": 11, "subtype": "EM"}]},
    {"name": "Fluorescein (FITC)", "id": 2, "qy": 0.79, "extCoeff": 70000, "emMax": 517,
     "exMax": 495, "spectra": [{"id": 21, "subtype": "EX"}, {"id": 22, "subtype": "EM"}]},
    {"name": "PE-Cy7", "id": 3, "qy": 0.8, "extCoeff": 1, "emMax": 778, "exMax": 565,
     "spectra": [{"id": 31, "subtype": "EM"}]},
]  # fmt: skip
SPECTRA = {
    21: {"data": [[480, 0.8], [495, 1.0]], "color": "#00ff00", "subtype": "EX"},
    22: {"data": [[510, 0.9], [517, 1.0]], "color": "#33cc33", "subtype": "EM"},
    31: {"data": [], "color": "#ff0000", "subtype": "EM"},  # FPbase has no points for it
}


class MemoryCache:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {}

    def get(self, key: str) -> dict | None:
        return self.store.get(key)

    def set(self, key: str, payload: dict) -> None:
        self.store[key] = payload


class FakeFPbase:
    """Answers the service's two GraphQL queries; counts the requests it gets."""

    def __init__(self, dyes: list[dict] = DYES) -> None:
        self.dyes = dyes
        self.requests: list[dict] = []
        self.offline = False

    def urlopen(self, request: urllib.request.Request, timeout: float) -> io.BytesIO:
        assert timeout > 0
        if self.offline:
            raise OSError("network unreachable")
        payload = json.loads(request.data)
        self.requests.append(payload)
        if "variables" in payload:
            data = {"spectrum": SPECTRA.get(payload["variables"]["id"])}
        else:
            data = {"dyes": self.dyes}
        return io.BytesIO(json.dumps({"data": data}).encode())


@pytest.fixture
def fpbase(monkeypatch) -> FakeFPbase:
    fake = FakeFPbase()
    monkeypatch.setattr(biology_services.urllib.request, "urlopen", fake.urlopen)
    return fake


@pytest.fixture
def service() -> FluorophoreService:
    return FluorophoreService(MemoryCache())


def test_a_common_name_finds_the_dye_by_whole_word_shortest_name_first(fpbase, service):
    spectrum = service.get_spectrum(" FITC ")

    assert spectrum is not None
    assert spectrum["em_max"] == 517  # Fluorescein (FITC), not the dextran conjugate
    assert spectrum["ex_data"] == SPECTRA[21]["data"]
    assert spectrum["em_data"] == SPECTRA[22]["data"]
    assert spectrum["color"] == "#33cc33"  # the emission spectrum's colour


def test_a_fetched_spectrum_is_cached_and_the_next_call_stays_offline(fpbase, service):
    first = service.get_spectrum("FITC")
    fpbase.offline = True

    assert service.get_spectrum("fitc") == first


def test_a_dye_whose_spectra_have_no_points_is_not_found_or_cached(fpbase, service):
    assert service.get_spectrum("PE-Cy7") is None
    assert "fluor_v4_pe-cy7" not in service._cache.store


def test_an_unknown_dye_is_not_found(fpbase, service):
    assert service.get_spectrum("Brilliant Nonexistent 999") is None


def test_offline_with_nothing_cached_finds_nothing_without_raising(fpbase, service):
    fpbase.offline = True

    assert service.get_spectrum("FITC") is None
    assert service.search_dyes("fluor") == []


def test_the_dye_index_is_fetched_once_and_reused(fpbase, service):
    service.search_dyes("fluor")
    service.search_dyes("pe")

    assert sum("variables" not in r for r in fpbase.requests) == 1


def test_search_matches_substrings_and_stops_at_the_cap(monkeypatch, service):
    many = [{"name": f"Alexa Fluor {i}", "spectra": []} for i in range(FPBASE_MAX_MATCHES + 5)]
    fake = FakeFPbase(dyes=many)
    monkeypatch.setattr(biology_services.urllib.request, "urlopen", fake.urlopen)

    found = service.search_dyes("ALEXA")

    assert len(found) == FPBASE_MAX_MATCHES
    assert found[0] == "Alexa Fluor 0"


CATALOGUE = {
    name.lower(): {"name": name}
    for name in (
        "APC/H7",
        "PE-Cy5",
        "PE-Cy7",
        "Cy7",
        "APC (allophycocyanin)",
        "Alexa Fluor 680-Allophycocyanin (APC)",
        "PE (R-PE / R-phycoerythrin)",
        "Fluorescein (FITC)",
        "Fluorescein-Dextran (FITC)",
        "Brilliant Violet 421",
    )
}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("apc", "APC (allophycocyanin)"),  # not the shorter tandem APC/H7
        ("pe", "PE (R-PE / R-phycoerythrin)"),  # not PE-Cy5
        ("r-phycoerythrin", "PE (R-PE / R-phycoerythrin)"),  # an alias
        ("fitc", "Fluorescein (FITC)"),  # an alias, shortest name first
        ("pe/cy7", "PE-Cy7"),  # another separator, not Cy7
        ("pe cy7", "PE-Cy7"),
        ("bv421", "Brilliant Violet 421"),
        ("pe-cy5", "PE-Cy5"),
    ],
)
def test_a_bare_dye_name_finds_the_dye_itself_not_a_tandem_containing_it(service, query, expected):
    match = service._match_dye(query, CATALOGUE)

    assert match is not None and match["name"] == expected


def test_a_spectrum_cached_under_the_old_key_is_fetched_again(fpbase, service):
    service._cache.set("fluor_v3_fitc", {"em_data": [[780, 1.0]]})  # the old, possibly wrong match

    assert service.get_spectrum("FITC")["em_max"] == 517
