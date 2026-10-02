"""Every Academy question stays short, answerable and uniquely identified.

The SDK's QuestionStep already rejects unanswerable questions (no correct
choice, wrong choices without feedback) at import time; this adds the
course-writing rules from docs/developer/plans/ACADEMY_ACTIVE_LEARNING_PLAN.md.
"""

from __future__ import annotations

import re

import pytest
from karcytics_sdk.plugin.tutorial_models import QuestionStep

from karcytics_plugins.flow_cytometry.tutorials.courses import (
    course_1_fundamentals,
    course_2_gating,
    course_3_analysis,
    course_4_reporting,
)

COURSES = [course_1_fundamentals, course_2_gating, course_3_analysis, course_4_reporting]
MAX_QUESTION_WORDS = 50
MAX_CHOICE_WORDS = 15
MAX_FEEDBACK_WORDS = 40
MAX_EXPLANATION_WORDS = 50

QUESTIONS = [(c.id, s) for c in COURSES for s in c.steps if isinstance(s, QuestionStep)]


def _words(text: str) -> int:
    return len(re.sub(r"<[^>]+>|\*\*", " ", text).split())


def test_course4_has_questions():
    assert any(cid == course_4_reporting.id for cid, _ in QUESTIONS)


@pytest.mark.parametrize(("course_id", "step"), QUESTIONS, ids=[s.id for _, s in QUESTIONS])
def test_question_is_concise(course_id, step):
    assert _words(step.text) <= MAX_QUESTION_WORDS
    assert _words(step.explanation) <= MAX_EXPLANATION_WORDS
    for choice in step.choices:
        assert _words(choice.text) <= MAX_CHOICE_WORDS, choice.text
        assert _words(choice.feedback) <= MAX_FEEDBACK_WORDS, choice.feedback


def test_question_ids_are_unique_across_courses():
    """Answers are recorded by question_id across courses, so a clash would
    let one question's answer reveal as another's."""
    ids = [s.question_id for _, s in QUESTIONS if s.question_id]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(("course_id", "step"), QUESTIONS, ids=[s.id for _, s in QUESTIONS])
def test_answers_are_recorded(course_id, step):
    assert step.question_id, "give every question a question_id so attempts are saved"
