"""Course text never runs two sentences or words together.

Step text is written as adjacent Python strings, which join with no space:
"intended for" "other dyes" became "intended forother dyes", and
"or more." "Detectors" became "or more.Detectors". Missing spaces after
punctuation are caught here; a missing space between two words can't be told
from a real word, so keep a trailing space on each line of step text.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest
from karcytics_sdk.plugin.tutorial_models import QuestionStep

from karcytics_plugins.flow_cytometry.tutorials.courses import COURSES

# Punctuation glued to the next word: "more.Detectors", "tissues:spleen".
_GLUED = re.compile(r"[a-z)][.,:;!?](?=[A-Za-z])")
# Things that legitimately contain glued punctuation.
_ALLOWED = re.compile(
    r"<[^>]+>|\*\*|https?://\S+|\{answer:[^}]+\}|\be\.g\b|\bi\.e\b|"
    r"\b[\w-]+\.(?:fcs|csv|png|org|com|json)\b"
)


def _texts(step) -> list[str]:
    texts = [getattr(step, "text", "") or "", getattr(step, "failure_hint", "") or ""]
    if isinstance(step, QuestionStep):
        texts.append(step.explanation or "")
        texts += [c.text for c in step.choices] + [c.feedback or "" for c in step.choices]
    return texts


def glued(text: str) -> list[str]:
    """Every place in ``text`` where punctuation runs straight into a word."""
    plain = _ALLOWED.sub(" ", text)
    return [plain[max(0, m.start() - 10) : m.end() + 10] for m in _GLUED.finditer(plain)]


STEPS = [(course.id, step) for course in COURSES for step in course.steps]


@pytest.mark.parametrize(("course_id", "step"), STEPS, ids=[s.id for _, s in STEPS])
def test_no_sentences_run_together(course_id, step):
    for text in _texts(step):
        assert not glued(text), glued(text)


@pytest.mark.parametrize(
    "bad", ["or more.Detectors", "tissues:spleen", "dismay,you", "background,defining"]
)
def test_the_check_catches_the_typos_it_was_written_for(bad):
    assert glued(bad)


@pytest.mark.parametrize(
    "fine", ["e.g. the 488 nm laser", "Specimen_001_PI.fcs", "fpbase.org", "0.30"]
)
def test_the_check_leaves_real_text_alone(fine):
    assert not glued(fine)


def _joined_word_pairs(source: str) -> list[str]:
    """Adjacent string literals that would join two words: 'for' 'other' -> 'forother'."""
    found: list[str] = []
    previous: str | None = None
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT):
            continue
        if token.type == tokenize.STRING:
            try:
                value = ast.literal_eval(token.string)
            except (ValueError, SyntaxError):  # an f-string: check its literal ends
                value = re.sub(r"^[a-zA-Z]*['\"]{1,3}|['\"]{1,3}$", "", token.string)
            if (
                isinstance(value, str)
                and previous
                and value
                and re.search(r"[A-Za-z]$", previous)
                and re.match(r"[A-Za-z]", value)
            ):
                found.append(f"{previous[-15:]!r} + {value[:15]!r}")
            previous = value if isinstance(value, str) else None
        else:
            previous = None
    return found


TUTORIAL_SOURCES = sorted(
    (Path(__file__).parents[3] / "src/karcytics_plugins/flow_cytometry/tutorials").glob("*.py")
)


@pytest.mark.parametrize("path", TUTORIAL_SOURCES, ids=[p.name for p in TUTORIAL_SOURCES])
def test_no_words_run_together_across_string_lines(path):
    assert not _joined_word_pairs(path.read_text(encoding="utf-8"))


def test_the_source_check_catches_a_joined_word():
    assert _joined_word_pairs('x = ("intended for"\n     "other dyes")\n')
    assert not _joined_word_pairs('x = ("intended for "\n     "other dyes")\n')
