"""A step's resume_step_id (where a paused course resumes when paused on it)
must name a step of the same course that comes before it on the main path —
resuming forward would skip work the learner hasn't done.
"""

from __future__ import annotations

import pytest

from karcytics_plugins.flow_cytometry.tutorials.courses import (
    course_1_fundamentals,
    course_2_compensation,
    course_3_gating,
    course_4_analysis,
    course_5_reporting,
)

COURSES = [
    course_1_fundamentals,
    course_2_compensation,
    course_3_gating,
    course_4_analysis,
    course_5_reporting,
]


@pytest.mark.parametrize("course", COURSES, ids=lambda c: c.id)
def test_resume_steps_point_back_within_the_course(course):
    main_path = course.get_main_path()
    for step in course.steps:
        if not step.resume_step_id:
            continue
        assert course.get_step(step.resume_step_id) is not None, step.id
        if step.id in main_path and step.resume_step_id in main_path:
            assert main_path.index(step.resume_step_id) < main_path.index(step.id), step.id
