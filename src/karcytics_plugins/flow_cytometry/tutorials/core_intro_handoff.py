"""Flow Cytometry half of the Hub's `core_intro` onboarding tour.

The Hub's own `core_intro_v1` course (``karcytics/tutorials/core_intro.py``)
used to walk the user through this module directly, back when Flow Cytometry
ran in-process and the Hub could `findChild()` its buttons. Now that this
plugin runs as a genuinely separate OS process (the V3 isolated engine), the
Hub can no longer reach into its widget tree at all — so this course is the
in-module continuation of that same tour, run entirely by this plugin's own
local Academy engine (`karcytics_sdk.plugin.runtime_services.tutorial_manager`),
the exact mechanism `course1_fundamentals` already proves works for spotlighting
this plugin's own real widgets from inside its own process.

Deliberately **not** registered via `register_courses()` / listed in this
plugin's own Academy catalogue (`AcademyCatalogWindow`) — it's the Hub's tour
content, just executed here; a user picking their own course from Help >
Academy should never see it. It's registered and auto-started only from
`ui_daemon.py`'s `on_panel_ready` hook, gated on `KARCYTICS_ACADEMY_HANDOFF`
(see that file, and `plugin_loader.py::_instantiate_isolated_overlay` on the
Hub side, which sets the flag that becomes that env var).

On completion, `ui_daemon.py` sends an `academy_handoff_complete` event back
to the Hub over the existing daemon IPC channel, which resumes `core_intro_v1`
at its graduation phase (see `karcytics/core/plugins/loader.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from karcytics_sdk.plugin.tutorial_models import (
    ActionStep,
    ConsentStep,
    Course,
    InfoStep,
    InteractionStep,
    VerificationStep,
)

from .validators import PopupClosedValidator, PreferencesPageValidator, WorkflowSavedValidator

CORE_INTRO_HANDOFF_COURSE_ID = "core_intro_module_v1"

# SDKPreferencesDialog's object name (karcytics_sdk.plugin.ui_preferences.
# PREFERENCES_DIALOG_OBJECT_NAME) — spelled out rather than imported so this
# module still loads against an SDK older than that constant.
_PREFERENCES_DIALOG = "PreferencesDialog"

# The SDK menu bar gives Preferences… QAction.MenuRole.PreferencesRole, which
# macOS moves out of Edit into the app-name menu ("Flow Cytometry" — the
# isolated window's app name, see ui_daemon.py's window_title).
_PREFERENCES_MENU_PATH = (
    "the **Flow Cytometry** menu at the top of your screen → **Preferences…**"
    if sys.platform == "darwin"
    else "the **Edit** menu → **Preferences…**"
)


def _copy_demo_file(_panel: Any) -> None:
    """Copy the bundled demo FCS file to the user's Downloads directory.

    Adopts Course 1's `tutorial_assets.py` robust provisioning technique:
    - Checks multiple candidate local paths for `demo_tutorial.fcs`.
    - If local file is missing, fetches `demo_tutorial.fcs` from GitHub as fallback.
    - Writes `demo_tutorial.fcs` to both `~/Downloads` and Qt's `QStandardPaths` location.
    - Logs explicit diagnostic messages on success or failure.
    """
    import ssl
    import urllib.request

    from karcytics_sdk.plugin import get_logger
    from PyQt6.QtCore import QStandardPaths

    logger = get_logger(__name__, "flow_cytometry")
    filename = "demo_tutorial.fcs"

    candidates = [
        Path(__file__).resolve().parent / "assets" / filename,
        Path.home()
        / ".karcytics"
        / "plugins"
        / "flow_cytometry"
        / "src"
        / "karcytics_plugins"
        / "flow_cytometry"
        / "tutorials"
        / "assets"
        / filename,
    ]

    src_content: bytes | None = None
    for cand in candidates:
        if cand.exists() and cand.stat().st_size > 0:
            try:
                src_content = cand.read_bytes()
                logger.info(f"Loaded demo FCS asset from local path: {cand}")
                break
            except Exception as e:
                logger.warning(f"Failed to read demo FCS from {cand}: {e}")

    if src_content is None:
        url = f"https://raw.githubusercontent.com/KalaimaranB/Karcytics-flow-cytometry/main/src/karcytics_plugins/flow_cytometry/tutorials/assets/{filename}"
        try:
            logger.info(f"Fetching demo FCS asset from {url}")
            ssl_context = ssl.create_default_context()
            try:
                import certifi

                ssl_context.load_verify_locations(certifi.where())
            except ImportError:
                pass
            req = urllib.request.Request(url, headers={"User-Agent": "Karcytics-Academy/1.0"})
            with urllib.request.urlopen(req, timeout=15, context=ssl_context) as resp:
                src_content = resp.read()
        except Exception as e:
            logger.warning(f"Failed to download demo FCS file from GitHub: {e}")

    if not src_content:
        logger.error(
            "Could not obtain demo_tutorial.fcs content from local assets or network fallback."
        )
        return

    target_dirs: list[Path] = [Path.home() / "Downloads"]
    download_loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    if download_loc:
        qt_path = Path(download_loc)
        if qt_path != target_dirs[0]:
            target_dirs.append(qt_path)

    for target_dir in target_dirs:
        try:
            target_dir.mkdir(exist_ok=True, parents=True)
            dest_file = target_dir / filename
            dest_file.write_bytes(src_content)
            logger.info(f"Successfully copied demo FCS file to {dest_file}")
        except Exception as e:
            logger.warning(f"Failed to write demo FCS file to {target_dir}: {e}")


core_intro_module = Course(
    id=CORE_INTRO_HANDOFF_COURSE_ID,
    title="Karcytics Onboarding Tour — Flow Cytometry",
    description="The in-module continuation of the Hub's onboarding tour.",
    estimated_minutes=3,
    badge_reward=None,
    badge_icon="",
    prerequisite_course_ids=[],
    steps=[
        InfoStep(
            id="handoff_welcome",
            text=(
                "🧬 Welcome to **Flow Cytometry**! Every module gets a workspace built just for what it does."  # noqa: E501
            ),
            cyto_emotion="surprised",
            next_step_id="handoff_data_integrity",
        ),
        InfoStep(
            id="handoff_data_integrity",
            text=(
                "One thing before you import anything: Karcytics never touches your raw files. On import, it hashes the file (SHA-256) and copies it into this project's `` `assets/` `` folder — your original stays exactly where it was."  # noqa: E501
            ),
            cyto_emotion="talking",
            next_step_id="handoff_consent",
        ),
        ConsentStep(
            id="handoff_consent",
            text="Can we download a demo FCS file into your Downloads folder to use for this tutorial? If you decline, you will need to provide your own valid FCS file.",
            accept_text="Yes, download it",
            decline_text="No, I'll use my own",
            on_accept_step_id="handoff_download_demo",
            on_decline_step_id="handoff_import_custom_action",
        ),
        ActionStep(
            id="handoff_download_demo",
            text="",
            action=_copy_demo_file,
            next_step_id="handoff_import_action",
        ),
        InteractionStep(
            id="handoff_import_custom_action",
            text="No problem! Please click **➕ Add Samples** (highlighted) and import any valid FCS file from your machine to continue.",
            target_widget_names=["ImportDataButton"],
            target_widget_name="WorkspaceRibbon",
            event_trigger="samples_loaded",
            cyto_emotion="pointing",
            next_step_id="handoff_workflow_intro",
        ),
        InteractionStep(
            id="handoff_import_action",
            text=(
                "I've dropped a demo file (`` `demo_tutorial.fcs` ``) in your Downloads folder.\n\n"  # noqa: E501
                "Click **➕ Add Samples** (highlighted) and pick it. When it asks whether to copy the file into your workspace, say yes."  # noqa: E501
            ),
            target_widget_names=["ImportDataButton"],
            target_widget_name="WorkspaceRibbon",
            event_trigger="samples_loaded",
            cyto_emotion="pointing",
            next_step_id="handoff_workflow_intro",
        ),
        InfoStep(
            id="handoff_workflow_intro",
            text=(
                "Loaded! A **Workflow** is a snapshot of everything right now — settings, gates, parameters — so you can pick this exact session back up later."  # noqa: E501
            ),
            cyto_emotion="talking",
            next_step_id="handoff_save_action",
        ),
        VerificationStep(
            id="handoff_save_action",
            text=("Let's lock this in. Click **Save Workspace** (highlighted)."),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["WorkspaceSaveButton"],
            validator=WorkflowSavedValidator(),
            on_success_step_id="handoff_prefs_open",
        ),
        VerificationStep(
            id="handoff_prefs_open",
            text=(
                "Saved! 🎉 Every module also has its own preferences. "
                f"Open them from {_PREFERENCES_MENU_PATH}"
            ),
            cyto_emotion="pointing",
            allow_interaction=True,
            validator=PreferencesPageValidator(),
            on_success_step_id="handoff_prefs_workspace",
        ),
        VerificationStep(
            id="handoff_prefs_workspace",
            text="These are Flow Cytometry's own preferences. Click **Workspace** in the list on the left.",
            cyto_emotion="pointing",
            allow_interaction=True,
            target_widget_names=["PreferencesNavList"],
            validator=PreferencesPageValidator("Workspace"),
            failure_hint=f"Closed Preferences? Reopen it from {_PREFERENCES_MENU_PATH}, then click **Workspace**.",
            on_success_step_id="handoff_prefs_autosave",
        ),
        VerificationStep(
            id="handoff_prefs_autosave",
            text=(
                "Tick **Autosave workflows every 15 minutes** and Karcytics will quietly re-save your workflow for you. "  # noqa: E501
                "It only kicks in once a workflow has been saved manually — which you just did. "
                "Leave it off and you'll get a gentle reminder every 15 minutes instead.\n\n"
                "Close **Preferences** whenever you're ready to continue."
            ),
            cyto_emotion="happy",
            allow_interaction=True,
            target_widget_names=["AutosaveWorkflowsCheckbox"],
            validator=PopupClosedValidator(_PREFERENCES_DIALOG),
            on_success_step_id="handoff_return_home",
        ),
        InfoStep(
            id="handoff_return_home",
            text=(
                "All set! Close this window (File → Close, or the OS close button) to head back to Karcytics — Cyto's waiting for you there."  # noqa: E501
            ),
            cyto_emotion="happy",
        ),
    ],
)
