"""Karcytics Flow Cytometry — Academy Courses.

Step conventions:
  InfoStep           — teaches a concept; user clicks Next → to continue.
  InteractionStep    — user must click/interact with a named widget to auto-advance.
  VerificationStep   — auto-polls a validator every ~2 s and advances automatically.
                       Set allow_interaction=True only if the user also needs to freely
                       interact with the UI before clicking the manual 'Check ✓' button.

Spotlight convention:
  target_widget_name  — single objectName for InteractionStep highlight.
  target_widget_names — list of objectNames for multi-target InfoStep spotlights.
"""

from karcytics_sdk.plugin.tutorial_models import (
    BranchingStep,  # noqa: F401
    ForcedInteractionStep,  # noqa: F401
    SubTask,  # noqa: F401
)

from .course1 import course_1_fundamentals
from .course2 import course_2_gating
from .course3 import course_3_analysis
from .course4 import course_4_reporting

__all__ = [
    "course_1_fundamentals",
    "course_2_gating",
    "course_3_analysis",
    "course_4_reporting",
]
