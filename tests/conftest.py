import os
import sys
import types

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_repo_root, "src"))


from unittest.mock import MagicMock  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from PyQt6.QtWidgets import QLabel, QPushButton, QSplitter, QWidget  # noqa: E402

# Mock karcytics_sdk before it gets imported
mock_karcytics_sdk_plugin = MagicMock()


class DummyTaskBase:
    def __init__(self, *args, **kwargs):
        pass


from PyQt6.QtCore import pyqtSignal  # noqa: E402


class DummyPluginBase(QWidget):
    status_message = pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.plugin_id = kwargs.get("plugin_id", args[0] if args else "")

    def setup_workflow_autosave(self, has_saved_once, save, **kwargs):
        """Stub for PluginBase.setup_workflow_autosave (karcytics_sdk.plugin
        is mocked wholesale here) — returns a MagicMock standing in for the
        real WorkflowAutosaveController, since these tests exercise
        FlowCytometryPanel's own construction, not the SDK's autosave loop
        (that's covered in the SDK's own test suite).
        """
        return MagicMock()


class DummyAnalysisBase:
    def __init__(self, *args, **kwargs):
        self.plugin_id = kwargs.get("plugin_id", args[0] if args else "")
        self.signals = MagicMock()
        self._is_cancelled = False

    def is_cancelled(self):
        return self._is_cancelled


class DummyButton(QPushButton):
    def setHelpText(self, text: str, title: str = "") -> None:
        pass

    def _apply_theme_styles(self) -> None:
        pass


class DummyWorkspaceSaveButton(DummyButton):
    save_requested = pyqtSignal()
    update_requested = pyqtSignal()

    def set_workflow_active(self, active: bool):
        pass

    def set_dirty(self, dirty: bool):
        pass


class DummySplitter(QSplitter):
    pass


class DummyLabel(QLabel):
    pass


class DummyFooter(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__()

    def show_message(self, text: str) -> None:
        pass


from PyQt6.QtWidgets import (  # noqa: E402
    QComboBox,
    QLineEdit,
    QListWidget,
    QMenu,
    QProgressDialog,
    QSpinBox,
)


class DummyComboBox(QComboBox):
    pass


class DummyMenu(QMenu):
    pass


class DummyProgressDialog(QProgressDialog):
    def __init__(
        self,
        labelText="",  # noqa: N803
        cancelButtonText="",  # noqa: N803
        minimum=0,
        maximum=0,
        parent=None,
    ):
        super().__init__(labelText, cancelButtonText, minimum, maximum, parent)


class DummyLineEdit(QLineEdit):
    pass


class DummyListWidget(QListWidget):
    pass


class DummySpinBox(QSpinBox):
    pass


from karcytics_sdk.plugin.daemon import PluginDaemon  # noqa: E402

mock_karcytics_sdk_plugin.PluginBase = DummyPluginBase
mock_karcytics_sdk_plugin.PluginDaemon = PluginDaemon
mock_karcytics_sdk_plugin.AnalysisBase = DummyAnalysisBase
mock_karcytics_sdk_plugin.PluginState = DummyAnalysisBase
mock_karcytics_sdk_plugin.validate_file_exists = lambda path: (True, "")

mock_tasks = MagicMock()
mock_tasks.TaskBase = DummyTaskBase
mock_karcytics_sdk_plugin.tasks = mock_tasks
sys.modules["karcytics_sdk.plugin.tasks"] = mock_tasks


class MockComponents:
    pass


mock_components = MockComponents()
mock_components.PrimaryButton = DummyButton
mock_components.SecondaryButton = DummyButton
mock_components.BioSplitter = DummySplitter
mock_components.BioFooter = DummyFooter
mock_components.BioCaptionLabel = DummyLabel
mock_components.BioComboBox = DummyComboBox
mock_components.BioRunButton = DummyButton
mock_components.BioCancelButton = DummyButton
mock_components.BioStatusLabel = DummyLabel
mock_components.BioLineEdit = DummyLineEdit
mock_components.BioListWidget = DummyListWidget
mock_components.BioToggleButton = DummyButton
mock_components.BioSpinBox = DummySpinBox
mock_components.BioHelpButton = DummyButton
mock_components.BioProgressDialog = DummyProgressDialog
mock_components.AcademyButton = DummyButton
mock_components.BioMenu = DummyMenu
mock_components.WorkspaceSaveButton = DummyWorkspaceSaveButton
mock_components.theme_manager = MagicMock()
mock_karcytics_sdk_plugin.components = mock_components

sys.modules["karcytics_sdk"] = MagicMock()
sys.modules["karcytics_sdk.plugin"] = mock_karcytics_sdk_plugin
sys.modules["karcytics_sdk.plugin.components"] = mock_components
sys.modules["karcytics_sdk.plugin.events"] = MagicMock()
sys.modules["karcytics_sdk.plugin.workflow"] = MagicMock()

# Mock karcytics core and UI as well
mock_karcytics = MagicMock()
if "karcytics" not in sys.modules or not isinstance(sys.modules["karcytics"], types.ModuleType):
    sys.modules["karcytics"] = mock_karcytics
else:
    mock_ui = MagicMock()
    sys.modules["karcytics.ui"] = mock_ui
    sys.modules["karcytics"].ui = mock_ui
    sys.modules["karcytics_plugins.flow_cytometry"].ui = mock_ui


class DummyThemeMeta(type):
    def __getattr__(cls, name):
        if name.startswith("SIZE"):
            return "12"
        return "#000000"


class DummyColors(metaclass=DummyThemeMeta):
    pass


class DummyFonts(metaclass=DummyThemeMeta):
    pass


mock_theme = MagicMock()
mock_theme.Colors = DummyColors
mock_theme.Fonts = DummyFonts
mock_theme.theme_manager = MagicMock()
sys.modules["karcytics.ui.theme"] = mock_theme
sys.modules["karcytics_sdk.plugin.theme_fallback"] = mock_theme
sys.modules["karcytics_sdk.plugin.runtime_services"] = MagicMock()
sys.modules["karcytics.core"] = MagicMock()
sys.modules["karcytics.core.task_scheduler"] = MagicMock()
sys.modules["karcytics.shared"] = MagicMock()
sys.modules["karcytics.shared.ui"] = MagicMock()
sys.modules["karcytics.shared.ui.ui_components"] = mock_components


from karcytics_plugins.flow_cytometry.analysis.experiment import (  # noqa: E402
    Experiment,
    Sample,
)
from karcytics_plugins.flow_cytometry.analysis.state import FlowState  # noqa: E402

from .fixtures import *  # noqa: F403, E402


@pytest.fixture
def empty_state():
    """Returns a fresh FlowState with an empty experiment."""
    state = FlowState()
    state.data.experiment = Experiment()
    return state


@pytest.fixture
def sample_data():
    """Returns a dummy FCS DataFrame."""
    return pd.DataFrame(
        {
            "FSC-A": np.random.rand(1000) * 1024,
            "SSC-A": np.random.rand(1000) * 1024,
            "FL1-A": np.random.rand(1000) * 100,
        }
    )


@pytest.fixture
def sample_with_data(sample_data):
    """Returns a Sample object populated with dummy data."""
    sample = Sample(sample_id="s1", display_name="Sample 1")
    sample.fcs_data = MagicMock()
    sample.fcs_data.events = sample_data
    return sample


@pytest.fixture
def state_with_sample(empty_state, sample_with_data):
    """Returns a FlowState with one sample loaded."""
    empty_state.experiment.samples[sample_with_data.sample_id] = sample_with_data
    return empty_state
