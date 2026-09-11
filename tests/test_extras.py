"""Tests for the advice given when an installation cannot do what was asked.

The advice is different inside the standalone executable, and that difference is the whole
point of the module: `pip install "datasemver[duckdb]"` is the answer for someone holding a
Python installation and no answer at all for someone holding a single file, who has nothing
to install into and needs to be told that first.
"""

from __future__ import annotations

import sys

import pytest

from datasemver.formats import duck, excel, sql
from datasemver.utils.extras import install_hint, is_frozen


@pytest.fixture
def frozen(monkeypatch):
    """What PyInstaller sets on the interpreter it bundles."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)


def test_an_installation_is_told_which_extra_to_add():
    assert install_hint("duckdb", "the duckdb engine") == (
        'the duckdb engine needs the duckdb extra: pip install "datasemver[duckdb]"'
    )


def test_the_executable_is_told_it_needs_python_first(frozen):
    """Naming the pip command alone would send the reader to an environment they lack."""
    hint = install_hint("duckdb", "the duckdb engine")

    assert "not part of the standalone executable" in hint
    assert "needs a Python installation" in hint
    assert 'pip install "datasemver[duckdb]"' in hint


def test_frozen_is_read_when_asked_rather_than_at_import(frozen):
    """A value read at import time would be the wrong answer in the process that matters."""
    assert is_frozen() is True


def test_nothing_is_frozen_in_an_ordinary_run():
    assert is_frozen() is False


@pytest.mark.parametrize(
    ("module", "extra"),
    [(sql, "sql"), (excel, "excel"), (duck, "duckdb")],
)
def test_every_optional_reader_gives_advice_of_the_right_shape(module, extra, frozen):
    """Each of the three says the same two things, so no reader gets the worse version."""
    hint = module.install_hint()

    assert f"datasemver[{extra}]" in hint
    assert "not part of the standalone executable" in hint
