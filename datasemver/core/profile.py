"""Reading and writing a dataset profile as a file of its own.

A profile is everything a comparison actually consults: the columns, their types, their null
ratios, the quantile grid and the category counts. It is a few hundred bytes where the
dataset is megabytes, which changes what a comparison can be. Keep the profile beside the
data -- in git, next to the DVC pointer -- and the previous version never has to be fetched
to be compared against, because the part of it that mattered was kept.

That also makes a bump auditable. Six months later the datasets may be gone or rewritten;
the profile still says exactly what the suggestion was computed from.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from datasemver.core.models import DatasetSchema

# A profile is written to be read back by a later version, so it says which shape it is in.
# Bumped only when a change would make an older reader misinterpret a newer file; adding an
# optional field does not qualify, because a reader that ignores it still reads it correctly.
PROFILE_VERSION = 1

# Two suffixes rather than one, so a profile is never mistaken for a JSON dataset. `.json`
# alone is a format this library reads as data, and guessing between the two from the
# contents would be a coin flip on a file that happens to hold objects with the right keys.
PROFILE_SUFFIX = ".profile.json"


def _library_version() -> str:
    """The running version, read late.

    `datasemver/__init__.py` imports the analyser, which imports the loader, which imports
    this module: importing the package root here at module level would close that circle
    before `__version__` is bound. A default factory runs when a profile is built instead,
    by which point the package is fully imported.
    """
    from datasemver import __version__

    return __version__


class ProfileError(ValueError):
    """Raised when a file cannot be read as a profile."""


# What wrote a profile that does not say. Every profile written before the field existed came
# from the dataframe path, so reading one as `pandas` is a fact rather than an assumption.
DEFAULT_ENGINE = "pandas"


class Profile(BaseModel):
    """A stored dataset profile, with what is needed to read it back safely."""

    profile_version: int = PROFILE_VERSION
    created_with: str = Field(default_factory=_library_version)
    created_at: date = Field(default_factory=date.today)
    # Which engine computed it, recorded for the reason the version is: a profile outlives the
    # dataset it describes, and "what was this computed with" is the question someone reading
    # it months later has. The engines agree today; a profile that says which one it was is
    # what makes that checkable rather than assumed.
    engine: str = DEFAULT_ENGINE
    dataset: DatasetSchema


def is_profile(source: str | Path) -> bool:
    """Whether a source names a stored profile rather than a dataset."""
    return str(source).lower().endswith(PROFILE_SUFFIX)


def write_profile(schema: DatasetSchema, path: str | Path, engine: str | None = None) -> Path:
    """Write a profile, creating the directory it goes in."""
    destination = Path(path)
    if destination.parent != Path():
        destination.parent.mkdir(parents=True, exist_ok=True)
    profile = Profile(dataset=schema, engine=engine or DEFAULT_ENGINE)
    destination.write_text(
        json.dumps(profile.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def read_profile(path: str | Path) -> DatasetSchema:
    """Read a profile back, refusing one this version cannot be trusted to understand."""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"profile not found: {source}")

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ProfileError(f"{source} is not valid JSON: {error}") from error

    if not isinstance(payload, dict):
        raise ProfileError(f"{source} does not hold a profile: expected an object")

    version = payload.get("profile_version")
    if version is not None and isinstance(version, int) and version > PROFILE_VERSION:
        raise ProfileError(
            f"{source} was written in profile format {version}, and this DataSemver "
            f"({_library_version()}) reads up to {PROFILE_VERSION}. Upgrade to read it."
        )

    try:
        return Profile.model_validate(payload).dataset
    except ValidationError as error:
        problem = _first_problem(error)
        raise ProfileError(f"{source} is not a readable profile: {problem}") from error


def _first_problem(error: ValidationError) -> str:
    """One line from a pydantic error, which otherwise arrives as a paragraph per field."""
    problems = error.errors()
    if not problems:  # pragma: no cover - pydantic always reports at least one
        return "no detail"
    first = problems[0]
    location = ".".join(str(part) for part in first["loc"]) or "profile"
    return f"{location}: {first['msg']}"
