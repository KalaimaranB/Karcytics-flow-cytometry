"""Flow Cytometry Workspace — Karcytics plugin entry point.

A scientist-centric flow cytometry analysis environment with workspace-based
navigation, FMO-guided gating, adaptive gates, and reusable workflow templates.
"""

import os
from typing import Any

__plugin_id__ = "flow_cytometry"


def _read_version() -> str:
    """Single source of truth: pyproject.toml's [project].version.

    A hardcoded copy of this string lived here before and silently drifted
    out of sync with pyproject.toml's real, CI-authoritative version (the
    release workflow reads pyproject.toml directly to tag/name releases —
    see .github/workflows/release.yml). Tries `importlib.metadata` first
    (the normal path once this plugin is installed as a package), then
    falls back to parsing pyproject.toml straight from the source tree —
    how this plugin is actually loaded today, via a sys.path insert rather
    than a pip install (see tests/conftest.py).
    """
    try:
        from importlib.metadata import version as _pkg_version

        return _pkg_version(__plugin_id__)
    except Exception:
        pass

    try:
        import tomllib
        from pathlib import Path

        pyproject_path = Path(__file__).resolve().parents[3] / "pyproject.toml"
        with pyproject_path.open("rb") as f:
            return tomllib.load(f)["project"]["version"]
    except Exception:
        return "0.0.0"


__version__ = _read_version()

# CRITICAL: Prevent OpenBLAS/MKL from spawning nested thread pools inside
# Qt's QThreadPool worker threads. Worker threads have small stacks, and
# nested BLAS parallelism (e.g. numpy.linalg.inv in KDE/FMO) causes stack
# overflows (EXC_BAD_ACCESS / SIGBUS) on macOS. Must be set before any
# numpy/scipy import, which is why this lives in __init__ ahead of imports.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

# pandas can silently call into pyarrow internally (e.g. via
# maybe_convert_objects when inferring dtypes on an object array/Index).
# pyarrow isn't even a declared dependency of this plugin, so if it ends up
# loaded at all it's the *host app's* copy shadowing through — see
# SegFaultCrash.md. Its bundled mimalloc allocator has crashed
# (EXC_BAD_ACCESS in mi_heap_main, i.e. first-time thread-local heap init)
# on a QThreadPool worker thread. Forcing the plain system allocator instead
# of mimalloc sidesteps that code path entirely, regardless of which pandas
# operation ends up triggering the pyarrow call. Same "must be set before
# the native lib initializes" constraint as the BLAS vars above.
os.environ["ARROW_DEFAULT_MEMORY_POOL"] = "system"


def register_courses(manager: Any) -> None:
    from .tutorials.courses import (
        course_1_fundamentals,
        course_2_gating,
        course_3_analysis,
    )

    # Prevent duplicate registration
    if __plugin_id__ not in manager.courses_by_module or not any(
        c.id == course_1_fundamentals.id for c in manager.courses_by_module[__plugin_id__]
    ):
        manager.register_storyboard(__plugin_id__, course_1_fundamentals)
        manager.register_storyboard(__plugin_id__, course_2_gating)
        manager.register_storyboard(__plugin_id__, course_3_analysis)


def get_panel_class() -> type:
    """Returns the main QWidget class that should be injected into the UI.

    Standard Karcytics entry point.  The core ``ModuleManager`` calls this
    function to obtain the class (not an instance) and then instantiates it
    into the central workspace container.
    """
    # Numba JIT warm-up is deliberately NOT started here. See
    # FlowCytometryPanel._start_numba_warmup for why: this used to run
    # eagerly, before Phase 1 construction even began, which raced Phase
    # 1/2's own CPU-bound work for the GIL — numba/llvmlite's compilation
    # holds it through most of the compile, so a competing thread can turn
    # a ~3s warmup into 100s+ and stall everything else in the process
    # (confirmed live), including the daemon's own request handling.

    # TEMPORARY diagnostic instrumentation (see PR discussion) — pinpoints
    # exactly which of get_panel_class()'s steps a stalled daemon subprocess
    # never gets past. logger.info() doesn't surface without a configured
    # handler; .warning() is the lowest level guaranteed visible in captured
    # stderr — same reasoning as main_panel.py's [phase2] breadcrumbs.
    from karcytics_sdk.plugin import get_logger

    logger = get_logger(__name__, "flow_cytometry")

    # Pre-warm the FCS daemon worker process so the first file import of the
    # session doesn't pay for subprocess startup + heavy imports on top of
    # actual file parsing.
    logger.warning("[phase1] get_panel_class: importing fcs_io")
    from .analysis.fcs_io import warmup_daemon

    logger.warning("[phase1] get_panel_class: calling warmup_daemon()")
    warmup_daemon()

    # Fix bokeh's own frozen-app template detection before anything can ever
    # trigger it (bokeh assumes that if the process is frozen, bokeh itself
    # must be bundled alongside it — false here, bokeh lives in this plugin's
    # own .venv). Cheap and synchronous by design — see transforms.py for why
    # this must never touch sys.frozen/sys._MEIPASS from a background thread.
    logger.warning("[phase1] get_panel_class: importing transforms")
    from .analysis.transforms import patch_bokeh_template_env

    logger.warning("[phase1] get_panel_class: calling patch_bokeh_template_env()")
    patch_bokeh_template_env()

    logger.warning("[phase1] get_panel_class: importing runtime_services")
    from karcytics_sdk.plugin.runtime_services import tutorial_manager as global_tutorial_manager

    logger.warning("[phase1] get_panel_class: calling register_courses()")
    register_courses(global_tutorial_manager)

    logger.warning("[phase1] get_panel_class: importing main_panel (FlowCytometryPanel)")
    from .ui.main_panel import FlowCytometryPanel

    logger.warning("[phase1] get_panel_class: done")
    return FlowCytometryPanel


def cleanup() -> None:
    """Module-level cleanup."""


def shutdown() -> None:
    """Module-level shutdown."""


# Late import: PluginContext lives in karcytics_sdk which depends on this package
# at runtime — importing it at module load would create a circular import.
from karcytics_sdk.plugin.context import PluginContext  # noqa: E402


def initialize(context: PluginContext) -> Any:
    """V3 Plugin Entry Point."""
    logger = context.get("logger")
    logger.info("Initializing Flow Cytometry Workspace with PluginContext")

    # Return the module itself so the core can call .get_panel_class(), .cleanup(), etc.
    import sys

    return sys.modules[__name__]
