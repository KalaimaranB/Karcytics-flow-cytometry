"""Numba JIT warm-up utility for the Flow Cytometry plugin.

Running a tiny UMAP on dummy data pre-compiles all numba kernels so that the
real UMAP analysis starts with a warm JIT cache and doesn't freeze the UI.
"""

from __future__ import annotations

import threading

import numpy as np

_warmup_done = False
_warmup_lock = threading.Lock()


def warmup_numba_jit() -> None:
    """Pre-compile numba-compiled UMAP kernels on a background thread.

    Call this once at plugin load time (before the user clicks Run UMAP).
    Subsequent UMAP calls will reuse the compiled code and won't JIT stall.
    """
    global _warmup_done
    with _warmup_lock:
        if _warmup_done:
            return
        _warmup_done = True

    t = threading.Thread(target=_do_warmup, name="numba-jit-warmup", daemon=True)
    t.start()


def _do_warmup() -> None:
    """Runs a tiny UMAP on random dummy data to trigger JIT compilation."""
    try:
        import umap as umap_lib  # karcytics: allow KS360 - heavy library

        # karcytics: allow KS360 - heavy library
        from tqdm import tqdm  # type: ignore

        # UMAP's epoch loop always instantiates a tqdm progress bar
        # internally (gated by `disable`, not by whether it's created at
        # all — passing verbose=False below only silences its output, it
        # still runs). tqdm's very first instantiation *of any kind* in a
        # process lazily creates a class-level multiprocessing.RLock() to
        # coordinate terminal output across processes — unconditionally,
        # in __new__, before disable is even checked. Nothing in this
        # single-process, non-interactive worker ever needs multi-process
        # terminal coordination, and this process exits via os._exit()
        # (ui_daemon_runtime.run(), to dodge a buffered-stdin-lock deadlock
        # on shutdown), which skips atexit — so that lock's normal
        # multiprocessing finalizer never runs and resource_tracker reports
        # it leaked. Installing a plain threading lock here, before the
        # first tqdm instance is ever created in this process, makes
        # get_lock() find one already set and skip creating the
        # multiprocessing one entirely — this is tqdm's own documented
        # mechanism for exactly this case, not a workaround.
        tqdm.set_lock(threading.RLock())

        # 80 points, 10 epochs — enough to compile all internal numba kernels,
        # fast enough to finish in ~3-5s even on a slow machine.
        rng = np.random.default_rng(0)
        x_mat = rng.standard_normal((80, 6)).astype(np.float32)

        umap_lib.UMAP(
            n_neighbors=5,
            min_dist=0.1,
            n_epochs=10,
            n_jobs=1,
            random_state=0,
            low_memory=False,
            verbose=False,
        ).fit_transform(x_mat)

    except Exception:
        pass  # Warm-up failure is non-fatal — the real run will JIT on demand
