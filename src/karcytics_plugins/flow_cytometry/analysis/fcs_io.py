"""FCS file I/O — wraps FlowKit for robust FCS loading.

Uses ``flowkit.Sample`` for FCS 2.0/3.0/3.1 parsing, metadata
extraction, and channel naming.  Falls back to ``fcsparser`` if
FlowKit is unavailable.

Reference:
    FlowKit: https://github.com/whitews/FlowKit
    FCS standard: https://www.isac-net.org/
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.metadata
import importlib.util
import os
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from karcytics_sdk.plugin import get_logger

logger = get_logger(__name__, "flow_cytometry")

# TEMPORARY diagnostic instrumentation (see PR discussion) — this module's
# `import numpy`/`import pandas` is, as far as we can tell, the first time
# either gets imported in the daemon process (nothing loaded before this
# point in the startup path touches either). Bisecting the two confirms
# which one (if either) is where a stalled Windows CI daemon subprocess
# never gets past. .warning() is the lowest level guaranteed visible in
# captured stderr without a configured handler.
logger.warning("[phase1] fcs_io: importing numpy")
import numpy as np  # noqa: E402

logger.warning("[phase1] fcs_io: importing pandas")
import pandas as pd  # noqa: E402

logger.warning("[phase1] fcs_io: numpy/pandas imported")

from .constants import (  # noqa: E402
    DERIVED_PREFIX,
    FCS_LOCK_WARN_SECONDS,
    FCS_STRIP_RATIO_WARN,
)
from .derived.state import DerivedColumnsState  # noqa: E402


def _log_import_diagnostics() -> None:
    """Log import origins and versions for critical packages to aid debugging.

    Emits the module file path and version for a small set of packages that
    influence FCS loading behaviour. This is intentionally lightweight so it
    can be called on application startup without heavy overhead.
    """
    mods = ["flowkit", "FlowIO", "fcsparser", "numpy", "numba", "llvmlite"]
    entries = []
    for name in mods:
        try:
            spec = importlib.util.find_spec(name)
            mod_file = spec.origin if spec is not None else "not-found"
        except (ImportError, ValueError):
            mod_file = "error"

        try:
            # Prefer import to read __version__ when available
            module = importlib.import_module(name)
            ver = getattr(module, "__version__", None)
        except ImportError:
            module = None
            ver = None

        # Fallback to distribution metadata if module didn't expose __version__
        if ver is None:
            try:
                ver = importlib.metadata.version(name)
            except Exception:  # importlib.metadata.PackageNotFoundError not always exposed cleanly
                ver = "unknown"

        entries.append(f"{name} file={mod_file} version={ver}")

    logger.info(
        "Import diagnostics: python=%s executable=%s frozen=%s _MEIPASS=%s",
        ".".join(map(str, sys.version_info[:3])),
        sys.executable,
        getattr(sys, "frozen", "unset"),
        getattr(sys, "_MEIPASS", "unset"),
    )
    logger.info("Import diagnostics modules: %s", ", ".join(entries))
    logger.debug("sys.path head for diagnostics: %s", sys.path[:16])


def _inspect_native_dep(full_path: str, system: str) -> None:
    if not os.path.exists(full_path):
        return
    cmd = ["otool", "-L", full_path] if system == "Darwin" else ["ldd", full_path]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
        logger.debug("Native deps for %s: %s", full_path, out.stdout.replace("\n", "\\n"))
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("Failed to run %s on %s: %s", cmd[0], full_path, e)


def _inspect_distribution_files(name: str, system: str, max_files: int) -> None:
    try:
        dist = importlib.metadata.distribution(name)
        files = list(dist.files or [])[:max_files]
        logger.debug(
            "Distribution %s files (sample %d): %s",
            name,
            len(files),
            ", ".join(str(f) for f in files),
        )

        for f in files:
            if str(f).endswith((".so", ".dylib", ".pyd")):
                try:
                    full_path = str(dist.locate_file(f))
                    _inspect_native_dep(full_path, system)
                except Exception as e:
                    logger.debug("Could not locate file %s for distribution %s: %s", f, name, e)
    except importlib.metadata.PackageNotFoundError:
        logger.debug("No distribution metadata for %s", name)


def _deep_import_diagnostics(module_names: list[str], max_files: int = 50) -> None:
    """Collect deeper diagnostics for modules: distribution files and native deps.

    This logs discovered distribution files for each named package and for any
    native extension files attempts to inspect dynamic links using `otool -L`
    on macOS or `ldd` on Linux. The function is defensive and will never raise.
    """
    try:
        system = platform.system()
        logger.info(
            "Deep diagnostics: platform=%s, python=%s, exe=%s",
            system,
            ".".join(map(str, sys.version_info[:3])),
            sys.executable,
        )
        for var in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH", "PYTHONPATH", "PATH"):
            logger.debug("Env %s=%s", var, os.environ.get(var, ""))

        for name in module_names:
            try:
                spec = importlib.util.find_spec(name)
                origin = spec.origin if spec is not None else "not-found"
            except (ImportError, ValueError):
                origin = "error"

            try:
                ver = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                ver = (
                    getattr(sys.modules.get(name), "__version__", "unknown")
                    if name in sys.modules
                    else "unknown"
                )

            logger.info("Deep diag: module=%s origin=%s version=%s", name, origin, ver)
            _inspect_distribution_files(name, system, max_files)

    except Exception as e:
        logger.debug("Deep diagnostics failed: %s", e)


@dataclass
class FCSData:
    """Container for a loaded FCS dataset.

    Attributes:
        file_path:  Path to the source ``.fcs`` file.
        channels:   Ordered list of channel short names (e.g., ``FSC-A``).
        markers:    Ordered list of marker labels (e.g., ``CD4``).
                    May be empty if no staining annotations are present.
        events:     (N, C) DataFrame of raw event data.
        metadata:   FCS keyword dictionary (TEXT segment).
        _fk_sample: The underlying ``flowkit.Sample`` object, if loaded
                    via FlowKit.  Retained for downstream transform
                    and compensation operations.
        derived:    Bookkeeping for derived-parameter columns appended to
                    ``channels``/``events``; written only by
                    ``analysis/derived/sync.py``. Read labels through
                    :func:`derived_labels_of`.
    """

    file_path: Path
    channels: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)
    events: pd.DataFrame | None = None
    raw_events: pd.DataFrame | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    is_compensated: bool = False
    _fk_sample: object = field(default=None, repr=False)
    derived: DerivedColumnsState = field(
        default_factory=DerivedColumnsState, repr=False, compare=False
    )

    @property
    def num_events(self) -> int:
        """Total number of events."""
        return len(self.events) if self.events is not None else 0

    @property
    def num_channels(self) -> int:
        return len(self.channels)


def _decode_array(b64_str: str) -> np.ndarray:
    """Decode base64 string back into numpy array."""
    import base64
    import io

    raw = base64.b64decode(b64_str.encode("ascii"))
    buf = io.BytesIO(raw)
    return np.load(buf, allow_pickle=False)


def load_fcs(path: str | Path) -> FCSData:
    """Load an FCS file and return an :class:`FCSData` container.

    Uses the long-lived PluginDaemon worker process.
    """
    path = Path(path)
    from karcytics_sdk.plugin import validate_file_exists

    exists, msg = validate_file_exists(str(path))
    if not exists:
        raise FileNotFoundError(msg)

    try:
        return _load_with_flowkit(path)
    except Exception as exc:
        logger.warning(
            "FlowKit/Daemon loader failed for %s: %s — trying local fcsparser fallback.",
            path,
            exc,
        )
        return _load_with_fcsparser(path)


import threading  # noqa: E402

_daemon_lock = threading.Lock()

_warmup_done = False
_warmup_lock = threading.Lock()


def warmup_daemon() -> None:
    """Start the PluginDaemon worker process in the background.

    Call once at plugin load time. Spawning the subprocess and importing
    FlowKit/fcsparser/numpy inside it costs several seconds — paying that
    cost here means the first real ``load_fcs`` call in a session lands on
    an already-warm daemon instead of stalling behind a cold start.
    """
    global _warmup_done
    with _warmup_lock:
        if _warmup_done:
            return
        _warmup_done = True

    t = threading.Thread(target=_do_daemon_warmup, name="fcs-daemon-warmup", daemon=True)
    t.start()


def _do_daemon_warmup() -> None:
    try:
        from karcytics_sdk.plugin import PluginDaemon

        with _daemon_lock:
            PluginDaemon.start_instance("flow_cytometry")
    except Exception as exc:
        logger.warning("FCS daemon warm-up failed (will retry lazily on first load): %s", exc)


def _build_fcs_data_from_daemon_response(path: Path, res: dict[str, Any]) -> FCSData:
    """Decode a daemon ``load_fcs``-style response dict into an FCSData object."""
    channels = res["channels"]
    markers = res["markers"]
    metadata = res["metadata"]
    events_arr = _decode_array(res["events_b64"])
    events_df = pd.DataFrame(events_arr, columns=channels)

    # Copy only when there's actually an embedded spillover matrix to
    # preserve pre-compensation values from — the common case (no embedded
    # spill) leaves `events_df` untouched, so sharing the reference is
    # exactly equivalent and skips a full float64 duplicate per sample.
    raw_events_df = events_df.copy() if _has_embedded_spill(metadata) else events_df
    is_comp = _auto_apply_spill(path.name, events_df, metadata)

    return FCSData(
        file_path=path,
        channels=channels,
        markers=markers,
        events=events_df,
        raw_events=raw_events_df,
        metadata=metadata,
        is_compensated=is_comp,
    )


def _load_with_flowkit(path: Path) -> FCSData:
    """Load using the long-lived PluginDaemon worker process."""
    from karcytics_sdk.plugin import PluginDaemon

    with _daemon_lock:
        daemon = PluginDaemon.get_instance("flow_cytometry")
        res = daemon.call("load_fcs", {"path": str(path)})

    if "error" in res:
        raise ImportError(f"Daemon failed to load FCS file '{path.name}': {res['error']}")

    return _build_fcs_data_from_daemon_response(path, res)


def _split_existing_paths(
    paths: list[Path],
) -> tuple[list[Path], dict[Path, FCSData | Exception]]:
    """Separate paths that exist on disk from ones reported as missing.

    Missing paths are pre-populated into the result map as ``FileNotFoundError``
    so they never get sent to the daemon.
    """
    from karcytics_sdk.plugin import validate_file_exists

    valid: list[Path] = []
    out: dict[Path, FCSData | Exception] = {}
    for path in paths:
        exists, msg = validate_file_exists(str(path))
        if exists:
            valid.append(path)
        else:
            out[path] = FileNotFoundError(msg)
    return valid, out


def _call_daemon_batch(
    valid_paths: list[Path], cancel_poll: Callable[[], bool] | None
) -> dict[str, dict[str, Any]]:
    """Send one batched ``load_fcs_batch`` request and return its per-path results.

    Returns an empty dict (triggering a full local fallback for every path)
    if the daemon call itself failed outright, e.g. it couldn't start.
    """
    from karcytics_sdk.plugin import PluginDaemon

    t_lock_wait = time.monotonic()
    with _daemon_lock:
        lock_wait = time.monotonic() - t_lock_wait
        if lock_wait > FCS_LOCK_WARN_SECONDS:
            logger.info(f"_call_daemon_batch: waited {lock_wait:.2f}s to acquire _daemon_lock")
        daemon = PluginDaemon.get_instance("flow_cytometry")
        t_call = time.monotonic()
        res = daemon.call(
            "load_fcs_batch",
            {"paths": [str(p) for p in valid_paths]},
            cancel_poll=cancel_poll,
            # Deliberately tighter than it looks like it should be: the
            # daemon itself now bounds handle_load_fcs_batch to well under a
            # minute (see _batch_deadline_seconds), so under normal
            # conditions this returns in well under a second. A generous
            # client-side timeout here doesn't add safety margin — it adds
            # risk, because PluginDaemon.call() retries up to 3x on timeout,
            # killing and respawning the daemon each time, all on a plain
            # (non-daemon) thread. A 300s timeout could mean up to 15
            # minutes before daemon.call() ever returns control — and since
            # that thread is still alive, the whole app won't exit cleanly
            # even after the UI has long since moved on (this is what was
            # causing Karcytics to hang on quit rather than close promptly).
            timeout=min(90.0, max(45.0, 10.0 * len(valid_paths))),
        )
        logger.info(
            f"_call_daemon_batch: daemon.call('load_fcs_batch', {len(valid_paths)} files) "
            f"took {time.monotonic() - t_call:.2f}s"
        )

    if "error" in res:
        logger.warning(
            "Daemon batch load failed (%s) — trying local fcsparser fallback for all %d files.",
            res["error"],
            len(valid_paths),
        )
        return {}

    return res.get("results", {})


def _run_local_fallback(fallback_paths: list[Path]) -> dict[Path, FCSData | Exception]:
    """Load files the daemon couldn't handle via the local fcsparser reader.

    This path never touches the daemon, so it's free of the IPC lock and
    runs genuinely in parallel across a small bounded thread pool.
    """
    out: dict[Path, FCSData | Exception] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(fallback_paths))) as executor:
        future_to_path = {executor.submit(_load_with_fcsparser, p): p for p in fallback_paths}
        for future in as_completed(future_to_path):
            p = future_to_path[future]
            try:
                out[p] = future.result()
            except Exception as exc:
                out[p] = exc
    return out


def load_fcs_batch(
    paths: list[Path], cancel_poll: Callable[[], bool] | None = None
) -> dict[Path, FCSData | Exception]:
    """Load multiple FCS files via a single batched daemon round-trip.

    The daemon parses all files concurrently inside its own process (see
    ``handle_load_fcs_batch`` in ``daemon_worker.py``), so this gets real
    wall-clock parallelism instead of the single-file ``load_fcs`` path's
    one-request-per-file serialization through the daemon lock.

    Each path resolves independently to either an ``FCSData`` or an
    ``Exception`` — one bad file never fails the whole batch. Any file the
    daemon couldn't load falls back to the local ``fcsparser`` reader.
    """
    valid_paths, out = _split_existing_paths(paths)
    fallback_paths: list[Path] = []

    if valid_paths:
        batch_results = _call_daemon_batch(valid_paths, cancel_poll)
        for path in valid_paths:
            entry = batch_results.get(str(path))
            if entry is None or "error" in entry:
                if entry is not None:
                    logger.warning(
                        "Daemon batch load failed for %s: %s — trying local fcsparser fallback.",
                        path,
                        entry["error"],
                    )
                fallback_paths.append(path)
                continue
            try:
                out[path] = _build_fcs_data_from_daemon_response(path, entry)
            except Exception as exc:
                logger.warning("Failed to decode daemon response for %s: %s", path, exc)
                fallback_paths.append(path)

    if fallback_paths:
        out.update(_run_local_fallback(fallback_paths))

    return out


_SPILL_KEYS = ("$SPILLOVER", "$SPILL", "SPILLOVER", "SPILL", "spill", "spillover")


def _has_embedded_spill(metadata: dict) -> bool:
    """Cheaply predict whether `_auto_apply_spill` will find a spill string to parse.

    Lets callers skip the `raw_events` copy entirely when there's nothing to
    preserve it from — most loaded samples have no embedded spillover matrix
    at all, so `events_df.copy()` was previously made unconditionally only to
    sit there byte-identical to `events_df` forever.
    """
    return any(key in metadata for key in _SPILL_KEYS)


def _auto_apply_spill(filename: str, events_df: pd.DataFrame, metadata: dict) -> bool:
    """Apply an embedded spillover matrix to events_df in-place.

    BD FACSDiva and Beckman Coulter instruments embed the compensation
    matrix in the FCS TEXT segment as a comma-separated string under
    the key 'spill', '$SPILL', '$SPILLOVER', or 'SPILLOVER'.  This
    function finds whichever variant is present, parses it, and applies
    ``D_raw @ S⁻¹`` to the matching fluorescence columns.

    The mutation is in-place so the FCSData.events DataFrame already
    contains compensated values by the time the caller returns.
    """
    # All known key variants, checked in priority order
    spill_str: str | None = None
    for key in _SPILL_KEYS:
        if key in metadata:
            spill_str = str(metadata[key])
            break

    if not spill_str:
        return False  # No spill key — nothing to do

    try:
        parts = [p.strip() for p in spill_str.split(",") if p.strip()]
        n = int(parts[0])
        spill_channels = parts[1 : n + 1]
        values = [float(v) for v in parts[n + 1 : n + 1 + n * n]]

        if len(values) != n * n:
            logger.warning(
                "Spill string in %s malformed: expected %d values, got %d. "
                "Skipping auto-compensation.",
                filename,
                n * n,
                len(values),
            )
            return False

        spill_matrix = np.array(values, dtype=np.float64).reshape(n, n)

        # Only compensate channels that are actually in the DataFrame
        present = [ch for ch in spill_channels if ch in events_df.columns]
        if not present:
            logger.warning(
                "Spill channels %s not found in %s data columns %s. Skipping auto-compensation.",
                spill_channels,
                filename,
                list(events_df.columns),
            )
            return False

        idx = [spill_channels.index(ch) for ch in present]
        sub_spill = spill_matrix[np.ix_(idx, idx)]
        # Belt-and-suspenders on top of the OPENBLAS_NUM_THREADS=1 etc. set in
        # __init__.py: this runs on a QThreadPool worker thread (small stack),
        # and nested BLAS parallelism inside np.linalg.inv causes stack
        # overflows (EXC_BAD_ACCESS/SIGBUS) on macOS. The env vars only take
        # effect if set before OpenBLAS/MKL first initializes — if some other
        # import already triggered that (e.g. the host app's own numpy usage
        # before this plugin loads), they're a no-op, so force it explicitly
        # here at the actual call site instead of relying on process state.
        import threadpoolctl

        with threadpoolctl.threadpool_limits(1):
            sub_inv = np.linalg.inv(sub_spill)

        raw = events_df[present].values.astype(np.float64)
        # Suppress divide-by-zero / overflow — expected for extreme flow events
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            events_df[present] = raw @ sub_inv

        logger.info(
            "Auto-applied embedded spill compensation to %s (%d/%d channels: %s)",
            filename,
            len(present),
            n,
            present,
        )
        return True

    except (ValueError, IndexError, np.linalg.LinAlgError) as exc:
        logger.warning(
            "Failed to auto-apply spill compensation for %s: %s",
            filename,
            exc,
        )
        return False


def _load_with_fcsparser(path: Path) -> FCSData:  # noqa: C901, PLR0915, PLR0912
    """Fallback loader using fcsparser.

    Handles a common cytometer export quirk where the data section recorded in
    the FCS header is a few bytes larger than the actual file (typically 1–3
    events short).  When the standard ``fcsparser.parse`` call fails with a
    reshape error, we fall back to direct numpy binary reading using only the
    metadata header offsets and load as many *complete* events as the file
    actually contains.
    """
    import fcsparser

    logger.debug(
        "fcsparser loaded from %s, version=%s",
        getattr(fcsparser, "__file__", "unknown"),
        getattr(fcsparser, "__version__", "unknown"),
    )

    # ── Try standard fcsparser load first ──────────────────────────────
    try:
        meta, data = fcsparser.parse(str(path), reformat_meta=True, channel_naming="$PnN")
        channels = list(data.columns)
        events_df = data.copy()

        # Extract marker names from metadata ($PnS)
        markers = [meta.get(f"$P{i}S", "") for i in range(1, len(channels) + 1)]

    except Exception as parse_exc:
        # ── Fallback: read raw binary, truncating to complete events ────
        logger.warning(
            "fcsparser standard parse failed for %s (%s). "
            "Attempting tolerant binary read as a fallback.",
            path.name,
            parse_exc,
        )

        # Read metadata only to get header offsets
        meta_raw = fcsparser.parse(str(path), meta_data_only=True, reformat_meta=False)
        logger.debug(
            "fcsparser meta header values: BEGINDATA=%s ENDDATA=%s BYTEORD=%s TOT=%s PAR=%s",
            meta_raw.get("$BEGINDATA"),
            meta_raw.get("$ENDDATA"),
            meta_raw.get("$BYTEORD"),
            meta_raw.get("$TOT"),
            meta_raw.get("$PAR"),
        )

        n_params = int(meta_raw.get("$PAR", 0))
        begin_data = int(meta_raw.get("$BEGINDATA", 0))
        claimed_events = int(meta_raw.get("$TOT", 0))
        byteord_str = meta_raw.get("$BYTEORD", "1,2,3,4").strip()
        dtype_prefix = "<" if byteord_str.startswith("1") else ">"

        # Determine the on-disk element type from $DATATYPE/$PnB instead of
        # assuming FCS float32 — a truncated $DATATYPE=I (integer-mode) file
        # would otherwise be reinterpreted with the wrong byte width and
        # silently produce corrupted event values.
        datatype = str(meta_raw.get("$DATATYPE", "F")).strip().upper()
        pnb_values = [int(meta_raw.get(f"$P{i}B", 32)) for i in range(1, n_params + 1)]
        distinct_bits = set(pnb_values)
        if len(distinct_bits) > 1:
            logger.warning(
                "Mixed $PnB bit-widths %s in %s; the tolerant binary reader assumes "
                "a uniform width and will use %d bits, which may misalign columns.",
                sorted(distinct_bits),
                path.name,
                max(distinct_bits),
            )
        bits = max(distinct_bits) if distinct_bits else 32

        if datatype == "D":
            numpy_kind, bits = "f", 64
        elif datatype == "F":
            numpy_kind, bits = "f", 32
        elif datatype == "I":
            numpy_kind = "u"
            if bits not in (8, 16, 32, 64):
                raise RuntimeError(
                    f"Cannot parse {path.name}: unsupported integer bit-width "
                    f"$PnB={bits} in tolerant binary reader."
                ) from parse_exc
        else:
            logger.warning(
                "Unrecognized $DATATYPE=%s in %s; assuming float32.", datatype, path.name
            )
            numpy_kind, bits = "f", 32

        dtype = np.dtype(f"{dtype_prefix}{numpy_kind}{bits // 8}")

        bytes_per_event = n_params * dtype.itemsize
        if bytes_per_event == 0:
            raise RuntimeError(
                f"Cannot parse {path.name}: 0 parameters or zero-byte event size in header."
            ) from parse_exc

        file_size = path.stat().st_size
        available_bytes = file_size - begin_data

        # Read at most what the header claims — this prevents ingesting junk
        # bytes that lie past the real data end in truncated FCS files.
        # If the file is shorter than the header claims, read as many complete
        # events as the file actually contains.
        claimed_bytes = claimed_events * bytes_per_event
        read_bytes = min(available_bytes, claimed_bytes)
        actual_events = read_bytes // bytes_per_event

        if actual_events <= 0:
            raise RuntimeError(
                f"Cannot recover usable events from {path.name}: "
                f"n_params={n_params}, available_bytes={available_bytes}"
            ) from parse_exc

        with open(path, "rb") as fh:
            fh.seek(begin_data)
            raw = np.frombuffer(fh.read(actual_events * bytes_per_event), dtype=dtype)

        # Convert to native float64 so downstream numpy operations (matrix
        # multiply in _auto_apply_spill, matplotlib, etc.) work regardless of
        # the instrument's byte order.
        array_2d = raw.reshape(actual_events, n_params).astype(np.float64)

        # Channel names from $PnN — needed below to resolve which column is
        # the FSC channel, since parameter order is convention, not
        # guaranteed by the FCS spec.
        channels = [meta_raw.get(f"$P{i}N", f"Ch{i}") for i in range(1, n_params + 1)]

        # ── Garbage event filter ────────────────────────────────────────────
        # Truncated files can contain non-finite (NaN/Inf) or physically
        # impossible values in the last few events.  We apply two filters:
        #
        #  1. np.isfinite — removes NaN and ±Inf from any partial trailing event.
        #  2. FSC threshold — the cytometer records a $THRESHOLD keyword (e.g.
        #     "FSC,5000") below which no events should exist.  Denormal values
        #     like 6e-39 (IEEE 754 garbage from reading past real data end) are
        #     far below this and are stripped here.  If $THRESHOLD is absent we
        #     fall back to requiring FSC-A > 0 (all real scatter is positive).

        # Step 1: finite check across all channels
        valid_rows = np.all(np.isfinite(array_2d), axis=1)

        # Step 2: FSC threshold from the header (format: "channel,value[,...]").
        # Note: fcsparser with reformat_meta=False keeps "$" on standard FCS
        # keywords like $BYTEORD but stores instrument keywords like THRESHOLD
        # without a prefix — so we look up "THRESHOLD", not "$THRESHOLD".
        threshold_str = meta_raw.get("THRESHOLD", "")
        fsc_min = 0.0
        if threshold_str:
            parts = [p.strip() for p in threshold_str.split(",")]
            for i in range(0, len(parts) - 1, 2):
                if parts[i].upper().startswith("FSC"):
                    with contextlib.suppress(ValueError):
                        fsc_min = float(parts[i + 1])
                    break

        # Fallback: if no threshold keyword, any FSC-A below 1.0 is a denormal
        # artefact — real acquisition thresholds are always in the hundreds+.
        if fsc_min <= 0:
            fsc_min = 1.0

        # Resolve the actual FSC column by name — don't assume it's
        # parameter 1. Falls back to column 0 (with a warning) if no
        # channel is named FSC-something.
        fsc_col = next(
            (i for i, name in enumerate(channels) if name.upper().startswith("FSC")), None
        )
        if fsc_col is None:
            logger.warning(
                "No FSC channel found in %s (channels: %s); applying FSC threshold to "
                "parameter 1 as a fallback.",
                path.name,
                channels,
            )
            fsc_col = 0

        valid_rows &= array_2d[:, fsc_col] >= fsc_min

        n_stripped = actual_events - int(valid_rows.sum())
        total_stripped = claimed_events - int(valid_rows.sum())

        if claimed_events > 0 and (total_stripped / claimed_events) > FCS_STRIP_RATIO_WARN:
            pct = (total_stripped / claimed_events) * 100
            msg = (
                f"Data Integrity Warning for {path.name}: This file appears truncated or corrupted — "
                f"{pct:.1f}% of events were discarded during import. Results from this sample may be unreliable."
            )
            logger.warning(msg)
            from karcytics_sdk.plugin.runtime_services import diagnostics

            diagnostics.report_error(msg, fatal=False)

        if n_stripped > 0:
            logger.warning(
                "Stripped %d artefact events from %s "
                "(non-finite or below FSC threshold %.0f — truncated file).",
                n_stripped,
                path.name,
                fsc_min,
            )
            array_2d = array_2d[valid_rows]
            actual_events = len(array_2d)

        # Marker names from $PnS (channel names were already resolved above,
        # before the garbage filter, to determine the FSC column).
        markers = [meta_raw.get(f"$P{i}S", "") for i in range(1, n_params + 1)]

        events_df = pd.DataFrame(array_2d, columns=channels)

        # Reform metadata: strip leading "$" so downstream code sees consistent keys
        meta = {k.lstrip("$"): v for k, v in meta_raw.items()}

        logger.info(
            "Tolerant binary read of %s: %d events × %d channels "
            "(header claimed %d events — %d events truncated).",
            path.name,
            actual_events,
            n_params,
            int(meta_raw.get("$TOT", actual_events)),
            int(meta_raw.get("$TOT", actual_events)) - actual_events,
        )

    # ── Auto-apply embedded spillover matrix (same as FlowKit path) ────
    # Copy only when there's actually something to preserve — see the
    # matching comment in `_build_fcs_data_from_daemon_response`.
    raw_events_df = events_df.copy() if _has_embedded_spill(meta) else events_df
    is_comp = _auto_apply_spill(path.name, events_df, meta)

    logger.info(
        "Loaded %s via fcsparser: %d events × %d channels",
        path.name,
        len(events_df),
        len(channels),
    )

    return FCSData(
        file_path=path,
        channels=channels,
        markers=markers,
        events=events_df,
        raw_events=raw_events_df,
        metadata=meta,
        is_compensated=is_comp,
    )


def get_fluorescence_channels(data: FCSData) -> list[str]:
    """Return channel names that are likely fluorescence (not scatter/time).

    Heuristic: exclude names starting with FSC, SSC, Time.

    Args:
        data: A loaded :class:`FCSData`.

    Returns:
        List of fluorescence channel names.
    """
    exclude = ("FSC", "SSC", "Time", "time", DERIVED_PREFIX)
    return [ch for ch in data.channels if not ch.startswith(exclude)]


def derived_labels_of(data: object) -> dict[str, str]:
    """Derived-parameter display labels of ``data`` (``{}`` if none).

    Tolerates FCSData stand-ins (tests, older pickles) that predate the field.
    """
    state = getattr(data, "derived", None)
    return state.labels if isinstance(state, DerivedColumnsState) else {}


def get_channel_marker_label(data: FCSData, channel: str) -> str:
    """Return the display label for a channel.

    If a marker is mapped to this channel, returns ``"Marker (Channel)"``,
    otherwise returns just the channel name.

    Args:
        data:    A loaded :class:`FCSData`.
        channel: The channel short name.

    Returns:
        A human-readable label.
    """
    derived_label = derived_labels_of(data).get(channel)
    if derived_label is not None:
        return derived_label
    try:
        idx = data.channels.index(channel)
        marker = data.markers[idx] if idx < len(data.markers) else ""
        if marker:
            return f"{marker} ({channel})"
    except ValueError:
        pass
    return channel
