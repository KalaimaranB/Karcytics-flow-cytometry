"""Tests for the no-fallback failure behavior of the biexponential (Logicle) transform.

There used to be a resilience chain here: FlowKit's LogicleTransform -> flowutils
directly -> an arcsinh approximation. That was removed deliberately: an approximation
silently substitutes a mathematically different formula (arcsinh treats "width"
differently), producing a plausible-looking but numerically wrong plot with no visible
sign anything went wrong -- exactly the failure mode that let the Windows bokeh/frozen
bundle bug hide for so long. FlowKit failing to import or apply now must (a) report a
fatal diagnostic and (b) propagate the exception, not return a silently-wrong array.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

from karcytics_plugins.flow_cytometry.analysis import transforms


def _seed_fake_diagnostics(monkeypatch) -> MagicMock:
    """Replace the real `karcytics_sdk.plugin.runtime_services.diagnostics`
    singleton so the plugin's lazy `from karcytics_sdk.plugin.runtime_services
    import diagnostics` import resolves to a mock instead of forwarding to the
    (nonexistent, in a unit test) Hub process.

    `tests/conftest.py` replaces `sys.modules["karcytics_sdk.plugin"]` with a
    `MagicMock` for unrelated reasons (lightweight UI component stand-ins),
    leaving `sys.modules["karcytics_sdk.plugin.runtime_services"]` as an
    orphaned *real* entry from an earlier import. `importlib.import_module`
    resolves via that same flat `sys.modules` cache, matching exactly what
    `transforms.py`'s own `from karcytics_sdk.plugin.runtime_services import
    diagnostics` sees — unlike `monkeypatch.setattr("dotted.string", ...)` or
    `import a.b.c as x`, which both chase attributes through the *mocked*
    parent package instead and would silently patch a disconnected mock.
    """
    mock_diagnostics = MagicMock()
    real_module = importlib.import_module("karcytics_sdk.plugin.runtime_services")
    monkeypatch.setattr(real_module, "diagnostics", mock_diagnostics)
    return mock_diagnostics


@pytest.fixture(autouse=True)
def _reset_warning_flag(monkeypatch):
    monkeypatch.setattr(transforms, "_flowkit_logicle_warning_issued", False)


@pytest.mark.unit
class TestBiexponentialTransformNoFallback:
    def test_uses_real_flowkit_and_reports_nothing(self, monkeypatch):
        """The primary (only) path: FlowKit succeeds, no diagnostic is reported."""
        mock_diagnostics = _seed_fake_diagnostics(monkeypatch)

        data = np.array([-500.0, 0.0, 1.0, 100.0, 10_000.0, 200_000.0])
        result = transforms.biexponential_transform(data)

        assert result.shape == data.shape
        assert np.all(np.isfinite(result))
        mock_diagnostics.report_error.assert_not_called()

    def test_import_failure_reports_fatal_and_raises(self, monkeypatch):
        """`import flowkit` failing must be loud and must not return a value."""
        mock_diagnostics = _seed_fake_diagnostics(monkeypatch)

        # sys.modules[name] = None makes `import name` raise ImportError — this
        # simulates flowkit (or its bokeh dependency) failing to import, the exact
        # condition seen on Windows.
        monkeypatch.setitem(sys.modules, "flowkit", None)

        with pytest.raises(ImportError):
            transforms.biexponential_transform(np.array([1.0, 100.0]))

        mock_diagnostics.report_error.assert_called_once()
        _, kwargs = mock_diagnostics.report_error.call_args
        assert kwargs.get("fatal") is True

    def test_apply_failure_reports_fatal_and_raises(self, monkeypatch):
        """FlowKit importing fine but the transform itself failing must also be loud."""
        mock_diagnostics = _seed_fake_diagnostics(monkeypatch)

        def _boom(*_args, **_kwargs):
            raise RuntimeError("LogicleTransform.apply exploded")

        monkeypatch.setattr(transforms, "_get_logicle_transform", _boom)

        with pytest.raises(RuntimeError, match="exploded"):
            transforms.biexponential_transform(np.array([1.0, 100.0]))

        mock_diagnostics.report_error.assert_called_once()
        _, kwargs = mock_diagnostics.report_error.call_args
        assert kwargs.get("fatal") is True

    def test_no_arcsinh_fallback_symbol_remains(self):
        """Guard against the fallback chain quietly being reintroduced.

        Checks for actual fallback *usage*, not the word "flowutils" — that still
        legitimately appears in the docstring describing what FlowKit wraps.
        """
        import inspect

        source = inspect.getsource(transforms.biexponential_transform)
        assert "np.arcsinh" not in source
        assert "flowutils.transforms" not in source


@pytest.mark.unit
class TestInvertBiexponentialTransformNoFallback:
    def test_uses_real_flowkit_and_reports_nothing(self, monkeypatch):
        mock_diagnostics = _seed_fake_diagnostics(monkeypatch)

        data = np.array([0.0, 0.2, 0.5, 0.8, 1.0])
        result = transforms.invert_biexponential_transform(data)

        assert result.shape == data.shape
        assert np.all(np.isfinite(result))
        mock_diagnostics.report_error.assert_not_called()

    def test_apply_failure_reports_fatal_and_raises(self, monkeypatch):
        mock_diagnostics = _seed_fake_diagnostics(monkeypatch)

        def _boom(*_args, **_kwargs):
            raise RuntimeError("LogicleTransform.inverse exploded")

        monkeypatch.setattr(transforms, "_get_logicle_transform", _boom)

        with pytest.raises(RuntimeError, match="exploded"):
            transforms.invert_biexponential_transform(np.array([0.1, 0.5]))

        mock_diagnostics.report_error.assert_called_once()
        _, kwargs = mock_diagnostics.report_error.call_args
        assert kwargs.get("fatal") is True


def _purge_flowkit_bokeh_state() -> None:
    """Force flowkit/bokeh to be re-imported from scratch on the next `import`.

    Also clears bokeh's own `get_env()` lru_cache — it's a process-lifetime cache
    keyed on nothing (a bare `@lru_cache(None)` on a zero-arg function), so a
    previous test (or a previous production call) succeeding once would otherwise
    make every later call return the same cached Environment regardless of
    sys.frozen/_MEIPASS, silently defeating the whole point of these tests.
    """
    import bokeh.core.templates as bokeh_templates

    bokeh_templates.get_env.cache_clear()
    for name in list(sys.modules):
        if (
            name == "flowkit"
            or name.startswith("flowkit.")
            or name == "bokeh"
            or name.startswith("bokeh.")
        ):
            del sys.modules[name]


@pytest.mark.unit
class TestFrozenEnvironmentSimulation:
    """Regression coverage for the actual bug: bokeh's `get_env()` (imported as a
    side effect of `import flowkit`) checks `sys.frozen`/`sys._MEIPASS` globally to
    decide where its own Jinja2 templates live, wrongly assuming that if the
    *process* is frozen, bokeh itself must be bundled at the PyInstaller standard
    location. It never is here — bokeh lives in this plugin's own separate,
    non-frozen `.venv`. This is what actually broke on Windows; none of the
    dependency-resolution fixes (module shadowing, sys.path priority) touch it,
    because the *right* bokeh was always being imported — bokeh's own internal
    logic was just looking in the wrong place regardless.

    This needs no PyInstaller build, no frozen executable, and no CI `build` job —
    it reproduces the real condition directly and runs in milliseconds.
    """

    @pytest.fixture(autouse=True)
    def _isolate_module_state(self, monkeypatch):
        monkeypatch.setattr(transforms, "_bokeh_env_patched", False)
        _purge_flowkit_bokeh_state()
        yield
        # Some tests in this class (deliberately) leave bokeh's process-lifetime
        # get_env() lru_cache holding a *broken* Environment (built while
        # sys.frozen was faked) to reproduce the real bug. Under serial
        # execution the class's later tests happen to re-prime it correctly
        # before anything outside the class runs, hiding the leak. Under
        # parallel/xdist execution there's no such guarantee — an unrelated
        # test elsewhere in the same worker process that transitively imports
        # bokeh (e.g. via umap-learn) can inherit the broken cached
        # Environment and fail on a missing "file.html.jinja" template. Purge
        # again on teardown so nothing outside this class ever observes it.
        _purge_flowkit_bokeh_state()

    def test_simulated_frozen_state_reproduces_the_real_bug_when_unguarded(self, monkeypatch):
        """Proves the test condition itself is real, not a vacuous simulation.

        A bare `import flowkit`, with no frozen-state handling at all, must still
        fail under the simulated condition — otherwise this whole test class
        wouldn't actually be testing anything.
        """
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", "/nonexistent_meipass", raising=False)

        with pytest.raises(Exception, match="file.html.jinja"):
            import flowkit  # noqa: F401

    def test_biexponential_transform_survives_simulated_frozen_state(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", "/nonexistent_meipass", raising=False)

        result = transforms.biexponential_transform(np.array([1.0, 100.0, 10_000.0]))

        assert result.shape == (3,)
        assert np.all(np.isfinite(result))

    def test_invert_biexponential_transform_survives_simulated_frozen_state(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", "/nonexistent_meipass", raising=False)

        result = transforms.invert_biexponential_transform(np.array([0.1, 0.5]))

        assert result.shape == (2,)
        assert np.all(np.isfinite(result))

    def test_patch_bokeh_template_env_primes_cache_correctly(self, monkeypatch):
        """Directly tests `patch_bokeh_template_env()`: patch while "frozen", then
        confirm a raw (unpatched-call-site) template load succeeds afterward.
        """
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", "/nonexistent_meipass", raising=False)

        transforms.patch_bokeh_template_env()

        import bokeh.core.templates as bokeh_templates

        env = bokeh_templates.get_env()
        assert env.get_template("file.html.jinja").name == "file.html.jinja"

    def test_patch_never_touches_sys_frozen_or_meipass(self, monkeypatch):
        """Regression guard for the actual production incident: an earlier version
        of this fix "solved" the bug by temporarily deleting `sys._MEIPASS` around
        the first `import flowkit`. That crashed the whole plugin on load, because
        PyInstaller's own frozen import machinery reads `sys._MEIPASS` on every
        import, on every thread, for the life of the process — deleting it, even
        briefly, raced against unrelated concurrent imports and crashed them.

        The fix must never read-and-mutate those two attributes at all. Assert
        `patch_bokeh_template_env()` leaves them byte-for-byte untouched.
        """
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", "/nonexistent_meipass", raising=False)

        transforms.patch_bokeh_template_env()

        assert getattr(sys, "frozen", None) is True
        assert getattr(sys, "_MEIPASS", None) == "/nonexistent_meipass"

    def test_transform_functions_never_touch_sys_frozen_or_meipass(self, monkeypatch):
        """Same regression guard, exercised through the real call sites."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", "/nonexistent_meipass", raising=False)

        transforms.biexponential_transform(np.array([1.0, 100.0]))

        assert getattr(sys, "frozen", None) is True
        assert getattr(sys, "_MEIPASS", None) == "/nonexistent_meipass"
