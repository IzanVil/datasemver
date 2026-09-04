"""Discovery of versioned datasets on disk."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from datasemver.formats.loader import SUPPORTED_EXTENSIONS

VERSION_PATTERN = re.compile(r"^(?P<name>.+?)[._-]v(?P<version>\d+(?:[._]\d+)*)$", re.IGNORECASE)


class DatasetVersion(BaseModel):
    """One file of a versioned dataset."""

    version: str
    filename: str
    extension: str
    size_bytes: int
    modified_at: datetime


class DatasetGroup(BaseModel):
    """Every version found for a single dataset name."""

    name: str
    versions: list[DatasetVersion]

    @property
    def latest(self) -> DatasetVersion:
        return self.versions[-1]


class History(BaseModel):
    """Result of scanning the datasets directory."""

    directory: str
    exists: bool
    datasets: list[DatasetGroup] = []
    ignored: list[str] = []


class DatasetNotFoundError(LookupError):
    """Raised when a dataset name or version is not present in the directory."""


def scan_datasets(directory: Path) -> History:
    """Group the files of a directory by dataset name and version.

    Files are expected to be named `<name>_v<version>.<ext>`, as in `customers_v1.csv` or
    `customers_v2.1.csv`. Anything else is reported as ignored instead of failing.
    """
    if not directory.is_dir():
        return History(directory=str(directory), exists=False)

    groups: dict[str, list[DatasetVersion]] = {}
    ignored: list[str] = []

    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            ignored.append(path.name)
            continue

        match = VERSION_PATTERN.match(path.stem)
        if match is None:
            ignored.append(path.name)
            continue

        stats = path.stat()
        groups.setdefault(match["name"], []).append(
            DatasetVersion(
                version=match["version"].replace("_", "."),
                filename=path.name,
                extension=path.suffix.lower(),
                size_bytes=stats.st_size,
                modified_at=datetime.fromtimestamp(stats.st_mtime, tz=timezone.utc),
            )
        )

    datasets = [
        DatasetGroup(name=name, versions=sorted(versions, key=_version_key))
        for name, versions in sorted(groups.items())
    ]
    return History(directory=str(directory), exists=True, datasets=datasets, ignored=ignored)


def resolve_file(directory: Path, dataset: str, version: str) -> Path:
    """Return the path of one version of a dataset, refusing anything outside the directory."""
    history = scan_datasets(directory)
    for group in history.datasets:
        if group.name != dataset:
            continue
        for candidate in group.versions:
            if candidate.version == version:
                return directory / candidate.filename
        raise DatasetNotFoundError(f"dataset '{dataset}' has no version '{version}'")
    raise DatasetNotFoundError(f"unknown dataset '{dataset}'")


def _version_key(version: DatasetVersion) -> tuple[int, ...]:
    return tuple(int(part) for part in version.version.split("."))
