"""Semantic version arithmetic."""

from __future__ import annotations

import re

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
