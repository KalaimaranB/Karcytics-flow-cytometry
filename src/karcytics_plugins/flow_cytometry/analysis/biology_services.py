"""Services for querying biological databases.

Adheres to SOLID principles:
- SRP: Services only handle data fetching and parsing.
- DIP: They depend on a cache manager interface, rather than hardcoding disk logic.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from karcytics_sdk.plugin import get_logger

from .api_cache import CacheManager
from .constants import FPBASE_MAX_MATCHES, HTTP_OK

logger = get_logger(__name__, "flow_cytometry")

# Cache key versioned so stale old-format entries are ignored
_DYES_INDEX_KEY = "fpbase_dyes_index_v3"

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
        """Find the best-matching dye for a normalised name string."""
        # 1. Exact match
        if name in dyes_index:
            logger.debug(f"FPbase exact match: '{name}'")
            return dyes_index[name]

        # Sort names by length so 'Fluorescein (FITC)' is checked before 'Fluorescein-Dextran (FITC)'
        sorted_names = sorted(dyes_index.keys(), key=len)

        # 2. Exact word match (e.g., 'fitc' matching 'fluorescein (fitc)')

        for d_name in sorted_names:
            words = set(re.split(r"\W+", d_name))
            if name in words:
                logger.debug(f"FPbase exact word match: '{d_name}' for '{name}'")
                return dyes_index[d_name]

        # 3. Substring match (both directions)
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
        cache_key = f"fluor_v3_{name}"

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


class MarkerService:
    """Fetches biological marker information from UniProt."""

    def __init__(self, cache: CacheManager):
        self._cache = cache

    def get_marker_info(self, marker_name: str) -> dict[str, Any] | None:
        """Retrieve biological details for a given CD marker or protein.

        Args:
            marker_name: e.g., 'CD4', 'CD8'

        Returns:
            Dictionary with marker metadata.
        """
        marker_name = marker_name.upper().strip()
        if not marker_name:
            return None

        cache_key = f"marker_{marker_name}"
        cached_data = self._cache.get(cache_key)
        if cached_data:
            return cached_data

        # Ping UniProt for Human (9606) marker
        url = (
            f"https://rest.uniprot.org/uniprotkb/search"
            f"?query=(gene:{urllib.parse.quote(marker_name)})+AND+(organism_id:9606)&format=json"
        )

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Karcytics/1.0"})
            with urllib.request.urlopen(req, timeout=5.0) as response:
                if response.status == HTTP_OK:
                    data = json.loads(response.read().decode("utf-8"))
                    results = data.get("results", [])

                    if results:
                        best_doc = results[0]
                        acc = best_doc.get("primaryAccession", "")

                        protein_desc = best_doc.get("proteinDescription", {})
                        rec_name = protein_desc.get("recommendedName", {})
                        full_name = rec_name.get("fullName", {}).get(
                            "value", f"{marker_name} Molecule"
                        )

                        description = "Biological function details are unavailable."
                        for comment in best_doc.get("comments", []):
                            if comment.get("commentType") == "FUNCTION":
                                texts = comment.get("texts", [])
                                if texts:
                                    description = texts[0].get("value", "")
                                    break

                        result = {
                            "name": marker_name,
                            "label": full_name,
                            "description": description,
                            "ontology": "UniProtKB",
                            "iri": f"https://www.uniprot.org/uniprotkb/{acc}/entry" if acc else "",
                        }
                        self._cache.set(cache_key, result)
                        return result
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to fetch marker info for {marker_name} from UniProt: {e}")

        # Fallback stub
        return {
            "name": marker_name,
            "label": f"{marker_name} Molecule",
            "description": f"Biological information for {marker_name} is currently unavailable offline.",
            "ontology": "Unknown",
            "iri": "",
        }
