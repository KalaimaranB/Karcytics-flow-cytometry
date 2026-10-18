"""Flow Cytometry Plugin Daemon Worker.

Long-lived worker process running in the plugin environment. Imports heavy dependencies
(FlowKit, Numba, UMAP, HDBSCAN, fcsparser) once on startup and processes length-prefixed
msgpack IPC requests over stdin/stdout.
"""

from __future__ import annotations

import base64
import io
import os
import struct
import sys
import time as _time
import traceback
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# Pre-set thread environment variables before heavy C extension imports
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

import msgpack
import numpy as np

# Optional pre-warm imports
try:
    import flowkit
except ImportError:
    flowkit = None

try:
    import fcsparser
except ImportError:
    fcsparser = None

try:
    import umap
except ImportError:
    umap = None

try:
    import hdbscan
except ImportError:
    hdbscan = None

# Bound concurrent in-process parses: BLAS/OMP threads are already pinned to 1
# above, so this only limits Python-level + native-parser concurrency. Kept
# modest rather than unbounded to cap peak memory (each in-flight file holds
# a raw array + its base64-encoded copy) and to avoid stacking too many
# concurrent calls into FlowKit/fcsparser's C extensions at once.
_MAX_BATCH_WORKERS = min(8, max(2, (os.cpu_count() or 4)))

# This subprocess's own stderr is not captured into the host app's log, so a
# hang in here is otherwise invisible from the app's log. Write directly to a
# fixed file instead — cheap, append-only, and readable independently of
# whatever IPC/log-forwarding state the daemon or app happen to be in.
_DEBUG_LOG_PATH = os.path.expanduser("~/.karcytics/flow_cytometry_daemon_debug.log")


def _dlog(msg: str) -> None:
    try:
        import datetime

        with open(_DEBUG_LOG_PATH, "a") as f:
            f.write(f"{datetime.datetime.now().isoformat()} [pid={os.getpid()}] {msg}\n")
    except Exception:
        pass


def _batch_deadline_seconds(n_paths: int) -> float:
    """How long handle_load_fcs_batch() waits before giving up on stragglers.

    Stays safely under the client's own per-batch IPC timeout (see
    fcs_io._call_daemon_batch: max(120.0, 30.0 * n_paths)) so the daemon can
    report a graceful partial result instead of the client giving up on the
    entire batch and falling back to a from-scratch local reload.
    """
    return max(30.0, 5.0 * n_paths)


def write_frame(data: dict[str, Any]) -> None:
    """Write length-prefixed msgpack frame to stdout."""
    payload = msgpack.packb(data, use_bin_type=True)
    header = struct.pack(">I", len(payload))
    sys.stdout.buffer.write(header + payload)
    sys.stdout.buffer.flush()


# This script always runs standalone (spawned directly as `python daemon_worker.py`
# by PluginDaemon, never imported as part of the karcytics_plugins package), so it
# can't use `from .constants import ...` — there is no parent package at runtime
# and the relative import raises ImportError on every call. That exception used to
# get caught by main()'s blanket except-and-loop-again handler, which turned the
# very first inbound request into an infinite loop dumping tracebacks to stdout
# and stderr as fast as the CPU allowed, which the host never drains — both pipes
# fill up within moments and wedge this process (and the host's blocked write())
# forever. Keep this constant local instead of importing it from the package.
DAEMON_HEADER_MIN_FIELDS = 4


def read_frame() -> dict[str, Any] | None:
    """Read length-prefixed msgpack frame from stdin."""
    header = sys.stdin.buffer.read(DAEMON_HEADER_MIN_FIELDS)
    if not header or len(header) < DAEMON_HEADER_MIN_FIELDS:
        return None
    length = struct.unpack(">I", header)[0]
    payload = sys.stdin.buffer.read(length)
    if not payload or len(payload) < length:
        return None
    return msgpack.unpackb(payload, raw=False)


def _encode_array(arr: np.ndarray) -> str:
    """Encode numpy array into base64 string using np.save."""
    buf = io.BytesIO()
    np.save(buf, arr, allow_pickle=False)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _decode_array(b64_str: str) -> np.ndarray:
    """Decode base64 string back into numpy array."""
    raw = base64.b64decode(b64_str.encode("ascii"))
    buf = io.BytesIO(raw)
    return np.load(buf, allow_pickle=False)


def handle_load_fcs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Load FCS file using pre-imported FlowKit or fcsparser."""
    path_str = kwargs.get("path", "")
    if not path_str or not os.path.exists(path_str):
        return {"error": f"FCS file not found: {path_str}"}

    _dlog(f"handle_load_fcs: start {os.path.basename(path_str)}")
    t_start = _time.monotonic()

    # 1. Try FlowKit first
    if flowkit is not None:
        try:
            _dlog(f"handle_load_fcs: calling flowkit.Sample() for {os.path.basename(path_str)}")
            sample = flowkit.Sample(path_str)
            _dlog(
                f"handle_load_fcs: flowkit.Sample() returned after "
                f"{_time.monotonic() - t_start:.2f}s for {os.path.basename(path_str)}"
            )
            raw_events = sample.as_dataframe(source="raw")
            channel_info = sample.channels
            channels = list(channel_info["pnn"])
            markers = [
                m if isinstance(m, str) and m.strip() else ""
                for m in channel_info.get("pns", [""] * len(channels))
            ]

            # Metadata extraction
            metadata = {}
            for k, v in getattr(sample, "metadata", {}).items():
                if isinstance(v, (str, int, float, bool)):
                    metadata[str(k)] = str(v)

            events_arr = raw_events.values.astype(np.float64)

            return {
                "status": "ok",
                "channels": channels,
                "markers": markers,
                "metadata": metadata,
                "events_b64": _encode_array(events_arr),
                "loader": "flowkit",
            }
        except Exception as fk_err:
            sys.stderr.write(f"FlowKit worker load failed for {path_str}: {fk_err}\n")

    # 2. Fallback to fcsparser
    if fcsparser is not None:
        try:
            meta, data = fcsparser.parse(path_str, reformat_meta=True, channel_naming="$PnN")
            channels = list(data.columns)
            markers = [str(meta.get(f"$P{i}S", "")) for i in range(1, len(channels) + 1)]
            metadata = {
                str(k).lstrip("$"): str(v)
                for k, v in meta.items()
                if isinstance(v, (str, int, float, bool))
            }
            events_arr = data.values.astype(np.float64)

            return {
                "status": "ok",
                "channels": channels,
                "markers": markers,
                "metadata": metadata,
                "events_b64": _encode_array(events_arr),
                "loader": "fcsparser",
            }
        except Exception as fcs_err:
            return {"error": f"fcsparser load failed for {path_str}: {fcs_err}"}

    return {"error": "Neither FlowKit nor fcsparser is available in worker process."}


def handle_load_fcs_batch(kwargs: dict[str, Any]) -> dict[str, Any]:  # noqa: C901
    """Load multiple FCS files concurrently within this single worker process.

    Runs in a bounded thread pool so a batch of files loads with real
    overlap instead of serializing one-request-per-file over the IPC
    pipe. Each file is isolated: one failure is reported per-path and
    never aborts or corrupts the rest of the batch.

    The daemon's main loop (see ``main()`` below) is single-threaded: it
    can't write this response, or answer any other request, until this
    function returns. A plain ``as_completed(future_to_path)`` with no
    timeout would block on the *slowest* file — so one stuck/corrupt FCS
    file would silently withhold every other file's already-finished
    result too, turning "9 fast files + 1 stuck one" into "nothing comes
    back at all" until the client's own outer timeout gives up on the
    whole batch. `deadline` bounds that: whatever hasn't finished in time
    is reported as a per-path timeout error instead, and the still-running
    thread is abandoned (not joined) so the response goes out promptly.

    The first file is always loaded on its own, before any concurrent
    fan-out — but bounded by a timeout of its own (see `_dlog` calls below
    if this is still hanging; check ~/.karcytics/flow_cytometry_daemon_debug.log,
    since this subprocess's stderr isn't captured by the host app's log).
    Empirically, a *cold* daemon (nothing loaded yet in this process)
    handling its first-ever call as an 8-way-concurrent batch reliably hung
    for minutes — flowutils' compiled Logicle transform (logicle_c) appears
    to have a first-use initialization race when multiple threads reach it
    at once. Loading the first file alone avoids racing it against other
    threads, but that call still needs its own timeout: an unprotected
    single call defeats the whole point of bounding everything else below it.
    """
    paths = kwargs.get("paths", [])
    if not paths:
        return {"status": "ok", "results": {}}

    _dlog(f"handle_load_fcs_batch: starting, {len(paths)} files")
    results: dict[str, Any] = {}
    first_path, *rest_paths = paths

    first_deadline = _batch_deadline_seconds(1)
    _dlog(
        f"handle_load_fcs_batch: loading first file alone (deadline={first_deadline:.0f}s): {first_path}"
    )
    t0 = _time.monotonic()
    first_executor = ThreadPoolExecutor(max_workers=1)
    first_future = first_executor.submit(handle_load_fcs, {"path": first_path})
    try:
        results[first_path] = first_future.result(timeout=first_deadline)
        _dlog(f"handle_load_fcs_batch: first file done after {_time.monotonic() - t0:.2f}s")
    except TimeoutError:
        _dlog(f"handle_load_fcs_batch: first file TIMED OUT after {_time.monotonic() - t0:.2f}s")
        results[first_path] = {"error": f"Timed out loading file after {first_deadline:.0f}s"}
    except Exception as exc:
        _dlog(
            f"handle_load_fcs_batch: first file raised after {_time.monotonic() - t0:.2f}s: {exc}"
        )
        results[first_path] = {"error": str(exc)}
    finally:
        first_executor.shutdown(wait=False, cancel_futures=True)

    if not rest_paths:
        _dlog("handle_load_fcs_batch: no remaining files, returning")
        return {"status": "ok", "results": results}

    max_workers = max(1, min(len(rest_paths), _MAX_BATCH_WORKERS))
    deadline = _batch_deadline_seconds(len(rest_paths))
    _dlog(
        f"handle_load_fcs_batch: fanning out {len(rest_paths)} remaining files across "
        f"{max_workers} workers (deadline={deadline:.0f}s)"
    )
    t1 = _time.monotonic()

    executor = ThreadPoolExecutor(max_workers=max_workers)
    future_to_path = {executor.submit(handle_load_fcs, {"path": p}): p for p in rest_paths}
    try:
        for future in as_completed(future_to_path, timeout=deadline):
            p = future_to_path[future]
            try:
                results[p] = future.result()
            except Exception as exc:
                results[p] = {"error": str(exc)}
    except TimeoutError:
        _dlog(f"handle_load_fcs_batch: fan-out TIMED OUT after {_time.monotonic() - t1:.2f}s")
    else:
        _dlog(f"handle_load_fcs_batch: fan-out finished after {_time.monotonic() - t1:.2f}s")
    finally:
        # wait=False: don't let a still-running straggler thread hold up
        # the response any further; it finishes on its own and is discarded.
        executor.shutdown(wait=False, cancel_futures=True)

    for p in rest_paths:
        if p not in results:
            sys.stderr.write(f"load_fcs_batch: {p} did not finish within {deadline:.0f}s\n")
            results[p] = {"error": f"Timed out loading file after {deadline:.0f}s"}

    _dlog(f"handle_load_fcs_batch: returning, total elapsed {_time.monotonic() - t0:.2f}s")
    return {"status": "ok", "results": results}


def handle_run_umap(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Fit UMAP and optional HDBSCAN clustering."""
    if umap is None:
        return {"error": "umap-learn is not installed in worker process."}

    x_b64 = kwargs.get("x_b64", "")
    params = kwargs.get("params", {})

    if not x_b64:
        return {"error": "No input matrix x_b64 provided."}

    x_mat = _decode_array(x_b64)

    n_neighbors = params.get("n_neighbors", 15)
    min_dist = params.get("min_dist", 0.1)
    metric = params.get("metric", "euclidean")
    random_seed = params.get("random_seed", 42)

    reducer = umap.UMAP(
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=random_seed,
        init="pca",
        low_memory=False,
        verbose=False,
    )
    embedding = reducer.fit_transform(x_mat)

    clusters_b64 = None
    if params.get("run_hdbscan", False):
        if hdbscan is None:
            return {"error": "hdbscan is not installed in worker process."}

        hdbscan_space = params.get("hdbscan_space", "high_dim")
        cluster_data = x_mat if hdbscan_space == "high_dim" else embedding
        min_cluster_size = params.get("min_cluster_size", 100)

        clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size)
        clusters = clusterer.fit_predict(cluster_data)
        clusters_b64 = _encode_array(clusters)

    res = {
        "status": "ok",
        "embedding_b64": _encode_array(embedding),
    }
    if clusters_b64:
        res["clusters_b64"] = clusters_b64

    return res


# ── PhenoGraph ──────────────────────────────────────────────────────────────
# Runs here, not in the app: the neighbour search and Leiden hold the GIL for
# seconds at a time, which froze the window when they ran in a worker thread.
# The graph (the costly part) is cached per run, so a new resolution only
# re-runs Leiden.

GRAPH_CACHE_SIZE = 3
_GRAPHS: OrderedDict[str, tuple[tuple, Any]] = OrderedDict()  # run uid -> (inputs, graph)
_clustering_module: Any = None


def _clustering() -> Any:
    """The plugin's Qt-free clustering package, loaded by path.

    Importing it through ``karcytics_plugins.flow_cytometry`` would run the
    plugin's ``__init__`` and pull Qt into this process.
    """
    global _clustering_module
    if _clustering_module is None:
        import importlib.util
        from pathlib import Path

        here = Path(__file__).resolve().parent / "clustering"
        spec = importlib.util.spec_from_file_location(
            "flow_clustering", here / "__init__.py", submodule_search_locations=[str(here)]
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["flow_clustering"] = module
        spec.loader.exec_module(module)
        _clustering_module = module
    return _clustering_module


def _phenograph_graph(uid: str, x: np.ndarray, k: int, seed: int) -> Any:
    """The run's graph: cached when the inputs match, else built (and cached)."""
    phenograph = _clustering().phenograph
    inputs = (x.shape, k, seed, float(x.sum()))
    cached = _GRAPHS.get(uid)
    if cached is not None and cached[0] == inputs:
        _GRAPHS.move_to_end(uid)
        return cached[1]
    graph = phenograph.build_graph(x, k, seed)
    _GRAPHS[uid] = (inputs, graph)
    while len(_GRAPHS) > GRAPH_CACHE_SIZE:
        _GRAPHS.popitem(last=False)
    return graph


def handle_run_phenograph(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Cluster with PhenoGraph (a first run, or the same run at a new resolution)."""
    x_b64 = kwargs.get("x_b64", "")
    if not x_b64:
        return {"error": "No input matrix x_b64 provided."}
    params = kwargs.get("params", {})
    seed = int(params.get("random_seed", 42))
    graph = _phenograph_graph(
        str(kwargs.get("run_uid", "")), _decode_array(x_b64), int(params.get("k", 30)), seed
    )
    result = _clustering().phenograph.recluster(
        graph,
        float(params.get("resolution", 1.0)),
        seed=seed,
        min_size=int(params.get("min_size", 10)),
    )
    return {
        "status": "ok",
        "clusters_b64": _encode_array(result.clusters),
        "edges_b64": _encode_array(result.edges),
        "connectivity_b64": _encode_array(result.connectivity),
        "layout_b64": _encode_array(result.layout),
    }


_HANDLERS: dict[str, Any] = {
    "ping": lambda _kwargs: {"status": "pong"},
    "load_fcs": handle_load_fcs,
    "load_fcs_batch": handle_load_fcs_batch,
    "run_umap": handle_run_umap,
    "run_phenograph": handle_run_phenograph,
    "cancel": lambda _kwargs: {"status": "cancelled"},
}


def main() -> None:
    """Worker daemon main loop."""
    sys.stderr.write("KARCYTICS_WORKER_READY\n")
    _dlog("main: daemon ready, entering request loop")
    write_frame({"status": "ready"})

    while True:
        try:
            frame = read_frame()
            if not frame:
                _dlog("main: read_frame() returned empty — exiting loop")
                break

            method = frame.get("method", "")
            kwargs = frame.get("kwargs", {})
            _dlog(f"main: received request method={method!r}")

            if method == "exit":
                break
            handler = _HANDLERS.get(method)
            res = handler(kwargs) if handler else {"error": f"Unknown method '{method}'"}
            if method == "load_fcs_batch":
                _dlog(
                    f"main: writing load_fcs_batch response, {len(res.get('results', {}))} results"
                )
            write_frame(res)

        except Exception as exc:
            err_msg = f"Daemon worker exception: {exc}\n{traceback.format_exc()}"
            sys.stderr.write(err_msg + "\n")
            write_frame({"error": str(exc)})


if __name__ == "__main__":
    main()
