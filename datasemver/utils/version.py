"""Semantic version arithmetic."""

from __future__ import annotations

import re
from pathlib import Path

from datasemver.core.models import Severity

VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class InvalidVersionError(ValueError):
    """Raised when a version string is not a plain MAJOR.MINOR.PATCH triplet."""


def parse_version(version: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.match(version.strip().lstrip("v"))
    if match is None:
        raise InvalidVersionError(f"invalid semantic version: {version!r}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def bump_version(current: str, severity: Severity | None) -> str:
    """Apply a severity bump to a version string."""
    major, minor, patch = parse_version(current)
    if severity is Severity.MAJOR:
        return f"{major + 1}.0.0"
    if severity is Severity.MINOR:
        return f"{major}.{minor + 1}.0"
    if severity is Severity.PATCH:
        return f"{major}.{minor}.{patch + 1}"
    return f"{major}.{minor}.{patch}"


# The sidecar is the number itself and nothing else, so its name is the whole of its format.
# Appended to the dataset's full name rather than replacing the format suffix the way a
# profile is: `sales.csv.version` says which file it belongs to, where `sales.version` beside
# a `sales.csv` and a `sales.parquet` would not.
VERSION_SUFFIX = ".version"


def write_version(path: Path, version: str) -> None:
    """Record a version beside its dataset, creating the sidecar when there is none.

    Validated before it is written: the sidecar is read back as the starting point of the
    next comparison, so a file holding something that is not a version turns into an error
    one run later, in a place that does not explain it.
    """
    parse_version(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{version}\n", encoding="utf-8")
