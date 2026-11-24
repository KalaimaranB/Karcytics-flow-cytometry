"""Fluorophore spectra from FPbase, cached on disk.

``fpbase_query_for_channel`` turns an FCS channel (and its marker) into the dye
name to look up; ``FluorophoreService`` fetches that dye's spectra from FPbase's
GraphQL API through a ``CacheManager``.
"""

import json
import re
import urllib.request
from typing import Any

from karcytics_sdk.plugin import get_logger

from .api_cache import CacheManager
from .constants import FPBASE_MAX_MATCHES

logger = get_logger(__name__, "flow_cytometry")

# FCS channel spellings that differ from FPbase's dye names.
_CHANNEL_NAME_MAPPINGS = {
    "APC-Cy7": "APC/Cy7",
    "PerCP-Cy5-5": "PerCP-Cy5.5",
}

# Stains that are themselves the fluorescent dye (not an antibody carrying
# one). Their channel is named for the detector, e.g. PI is read in
# PerCP-Cy5-5-A, so the detector's dye would be the wrong spectrum.
_DIRECT_DYE_MARKERS = {
    "PI": "Propidium Iodide",
    "PROPIDIUM IODIDE": "Propidium Iodide",
    "7-AAD": "7-AAD",
    "7AAD": "7-AAD",
    "DAPI": "DAPI",
}


def fpbase_query_for_channel(channel: str, marker: str = "") -> str:
    """The FPbase dye name to look up for an FCS channel and its marker label."""
    direct = _DIRECT_DYE_MARKERS.get(marker.strip().upper())
    if direct:
        return direct
    # Strip the detector suffix (-A, -H, -W) without breaking tandem dye names.
    query = re.sub(r"-[AHW]$", "", channel).strip()
    for fcs_name, fpbase_name in _CHANNEL_NAME_MAPPINGS.items():
        query = query.replace(fcs_name, fpbase_name)
    return query


# Cache keys versioned so stale entries are ignored. Spectra moved to v4 when
# matching stopped resolving bare names to tandems ("APC" had been cached as
# APC/H7, "PE" as PE-Cy5).
_DYES_INDEX_KEY = "fpbase_dyes_index_v3"
_SPECTRUM_KEY_PREFIX = "fluor_v4_"

# Brilliant Violet / Ultraviolet dyes appear in FCS channels by their short name.
_SHORT_NAME_PREFIXES = {"bv": "brilliant violet", "buv": "brilliant ultraviolet"}

_GRAPHQL_URL = "https://www.fpbase.org/graphql/"
_GRAPHQL_HEADERS = {"User-Agent": "Karcytics/1.0", "Content-Type": "application/json"}

_DYES_QUERY = "{ dyes { name id qy extCoeff emMax exMax spectra { id subtype } } }"
_SPECTRUM_QUERY = """
query Spectrum($id: Int!) {
    spectrum(id: $id) {
        data
        color
        subtype
    }
}
"""


class FluorophoreService:
    """Fetches spectral data for fluorophores from FPbase (AB, EX, EM arrays + QY/EC)."""

    def __init__(self, cache: CacheManager):
        self._cache = cache

    # ── Private helpers ───────────────────────────────────────────────────────

    def _gql(self, payload: dict, timeout: int = 10) -> dict | None:
        """Execute a single GraphQL request. Returns the 'data' block or None."""
        req = urllib.request.Request(
            _GRAPHQL_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=_GRAPHQL_HEADERS,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8")).get("data")
        except Exception as e:
            logger.warning(f"FPbase GraphQL request failed: {e}")
            return None

    def _fetch_dye_index(self) -> dict[str, Any]:
        """Fetch and cache the full FPbase dye catalogue with metadata."""
        logger.info("Fetching FPbase dye index from GraphQL (v3)…")
        data = self._gql({"query": _DYES_QUERY})
        dyes_index: dict[str, Any] = {}
        if data:
            dyes = data.get("dyes", [])
            logger.info(f"FPbase: received {len(dyes)} dyes.")
            for d in dyes:
                dyes_index[d["name"].lower()] = d
            self._cache.set(_DYES_INDEX_KEY, dyes_index)
        else:
            logger.warning("FPbase dye index fetch returned no data.")
        return dyes_index

    def _fetch_spectrum_data(self, spec_id: int) -> dict | None:
        """Fetch a single spectrum's [[wl, intensity]] array by ID."""
        logger.debug(f"Fetching spectrum id={spec_id} from FPbase…")
        data = self._gql({"query": _SPECTRUM_QUERY, "variables": {"id": spec_id}})
        if data:
            return data.get("spectrum")
        return None

    def _match_dye(self, name: str, dyes_index: dict) -> dict | None:
        """Find the best-matching dye for a normalised name string.

        Whole-name matches come first, so a bare dye name never resolves to a
        tandem that merely contains it ('apc' to 'apc/h7', 'pe' to 'pe-cy5').
        """
        name = _expand_short_name(name)
        # 1. Exact match
        if name in dyes_index:
            logger.debug(f"FPbase exact match: '{name}'")
            return dyes_index[name]

        # Sort names by length so 'Fluorescein (FITC)' is checked before 'Fluorescein-Dextran (FITC)'
        sorted_names = sorted(dyes_index.keys(), key=len)
        key = _canonical(name)

        # 2. The same name spelt with other separators ('pe/cy7' for 'pe-cy7')
        # 3. A dye's own name before its aliases ('apc' for 'apc (allophycocyanin)')
        # 4. One of its aliases in parentheses ('fitc' for 'fluorescein (fitc)')
        for names_of in (lambda d: [d], _head, _aliases):
            for d_name in sorted_names:
                if key in (_canonical(n) for n in names_of(d_name)):
                    logger.debug(f"FPbase name match: '{d_name}' for '{name}'")
                    return dyes_index[d_name]

        # 5. Exact word match (e.g., 'fitc' matching 'fluorescein-dextran (fitc)')

        for d_name in sorted_names:
            words = set(re.split(r"\W+", d_name))
            if name in words:
                logger.debug(f"FPbase exact word match: '{d_name}' for '{name}'")
                return dyes_index[d_name]

        # 6. Substring match (both directions)
        for d_name in sorted_names:
            if name in d_name or d_name in name:
                logger.debug(f"FPbase partial match: '{d_name}' for '{name}'")
                return dyes_index[d_name]

        logger.debug(f"FPbase: no match found for '{name}'")
        return None

    # ── Public API ────────────────────────────────────────────────────────────

    def get_spectrum(self, fluorophore_name: str) -> dict[str, Any] | None:
        """Retrieve AB, EX, and EM spectrum arrays + QY/EC metadata for a fluorophore.

        Fetches experimental data from FPbase. Falls back to a simple peak dict
        for common dyes if offline or unrecognised.

        Args:
            fluorophore_name: Common fluorophore name (e.g. 'FITC', 'APC/Cy7').

        Returns:
            Dict with keys: em_data, ex_data, ab_data (raw [[wl,y]] arrays),
            color (hex), qy, ext_coeff, em_max, ex_max.
            Or None if completely unknown.
        """
        name = fluorophore_name.lower().strip()
        cache_key = f"{_SPECTRUM_KEY_PREFIX}{name}"

        cached = self._cache.get(cache_key)
        if cached:
            logger.debug(f"Cache hit for '{name}'")
            return cached

        # Load or fetch the dye index
        dyes_index = self._cache.get(_DYES_INDEX_KEY) or self._fetch_dye_index()

        if dyes_index:
            matched = self._match_dye(name, dyes_index)
            if matched:
                result: dict[str, Any] = {
                    "qy": matched.get("qy"),
                    "ext_coeff": matched.get("extCoeff"),
                    "em_max": matched.get("emMax"),
                    "ex_max": matched.get("exMax"),
                    "color": "#aaaaaa",
                }

                # Fetch every spectrum subtype that exists (AB, EX, EM)
                any_fetched = False
                for spec in matched.get("spectra", []):
                    subtype = spec["subtype"]  # "AB", "EX", or "EM"
                    spec_id = int(spec["id"])
                    sp = self._fetch_spectrum_data(spec_id)
                    if sp and sp.get("data"):
                        result[f"{subtype.lower()}_data"] = sp["data"]
                        if subtype == "EM":
                            result["color"] = sp.get("color", result["color"])
                        any_fetched = True

                if any_fetched:
                    self._cache.set(cache_key, result)
                    logger.info(
                        f"Cached full spectrum for '{name}' ({', '.join(k for k in ('ab_data', 'ex_data', 'em_data') if k in result)})."
                    )
                    return result

        logger.debug(f"No FPbase data found for '{name}'. Fallback disabled.")
        return None

    def search_dyes(self, query: str) -> list[str]:
        """Substring-search the FPbase dye catalogue.

        Args:
            query: Search string (≥ 2 chars recommended).

        Returns:
            Up to 20 matching canonical dye names.
        """
        dyes_index = self._cache.get(_DYES_INDEX_KEY) or self._fetch_dye_index()
        if not dyes_index:
            return []

        q = query.lower()
        matches = []
        for d_name, d_obj in dyes_index.items():
            if q in d_name:
                matches.append(d_obj["name"])
            if len(matches) >= FPBASE_MAX_MATCHES:
                break
        return matches


def _canonical(name: str) -> str:
    """A dye name with spaces, hyphens, slashes and underscores all one separator."""
    return re.sub(r"[\s/_-]+", "-", name.strip())


def _head(dye_name: str) -> list[str]:
    """The name before any parenthesised aliases: 'apc' for 'apc (allophycocyanin)'."""
    return [dye_name.split("(", 1)[0]] if "(" in dye_name else []


def _aliases(dye_name: str) -> list[str]:
    """The parenthesised aliases: ['r-pe', 'r-phycoerythrin'] for 'pe (r-pe / r-phycoerythrin)'."""
    inside = re.findall(r"\(([^)]*)\)", dye_name)
    return [alias for group in inside for alias in group.split(" / ")]


def _expand_short_name(name: str) -> str:
    """'bv421' to 'brilliant violet 421'; any other name unchanged."""
    match = re.fullmatch(r"(bv|buv)\s*(\d+)", name)
    return f"{_SHORT_NAME_PREFIXES[match[1]]} {match[2]}" if match else name
