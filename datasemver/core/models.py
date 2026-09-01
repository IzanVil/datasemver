"""Data models shared across the analysis pipeline."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """SemVer severity levels, ordered from lowest to highest impact."""

    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]

    def __lt__(self, other: object) -> bool:
        return self.rank < other.rank if isinstance(other, Severity) else NotImplemented

    def __le__(self, other: object) -> bool:
        return self.rank <= other.rank if isinstance(other, Severity) else NotImplemented

    def __gt__(self, other: object) -> bool:
        return self.rank > other.rank if isinstance(other, Severity) else NotImplemented

    def __ge__(self, other: object) -> bool:
        return self.rank >= other.rank if isinstance(other, Severity) else NotImplemented


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.PATCH: 0,
    Severity.MINOR: 1,
    Severity.MAJOR: 2,
}


class ChangeType(str, Enum):
    """Every difference the differ is able to report."""

    COLUMN_ADDED = "column_added"
    COLUMN_REMOVED = "column_removed"
    COLUMN_RENAMED = "column_renamed"
    TYPE_CHANGED_INCOMPATIBLE = "type_changed_incompatible"
    TYPE_CHANGED_COMPATIBLE = "type_changed_compatible"
    ROW_COUNT_INCREASED = "row_count_increased"
    ROW_COUNT_DECREASED = "row_count_decreased"
    NULLS_FIXED = "nulls_fixed"
    NULLS_INTRODUCED = "nulls_introduced"
    NEW_CATEGORY_ADDED = "new_category_added"
    CATEGORY_REMOVED = "category_removed"
    CARDINALITY_CHANGED = "cardinality_changed"
    DISTRIBUTION_SHIFT = "distribution_shift"
    MINOR_STAT_CHANGE = "minor_stat_change"


class ColumnStatus(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    RENAMED = "renamed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


class ColumnStats(BaseModel):
    """Profile of a single column."""

    name: str
    dtype: str
    row_count: int
    null_ratio: float
    cardinality: int
    mean: float | None = None
    std: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    mode: str | None = None
    categories: list[str] | None = None

    @property
    def is_numeric(self) -> bool:
        return self.dtype in {"int64", "float64"}

    @property
    def non_null_count(self) -> int:
        return round(self.row_count * (1 - self.null_ratio))

    @property
    def uniqueness(self) -> float:
        return self.cardinality / self.non_null_count if self.non_null_count else 0.0


class DatasetSchema(BaseModel):
    """Profile of a whole dataset."""

    source: str
    row_count: int
    columns: dict[str, ColumnStats] = Field(default_factory=dict)

    @property
    def column_names(self) -> list[str]:
        return list(self.columns)


class Change(BaseModel):
    """A single detected difference between two datasets."""

    type: ChangeType
    column: str | None = None
    description: str
    metrics: dict[str, float] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


class ColumnComparison(BaseModel):
    """Row of the side-by-side column comparison table."""

    name: str
    status: ColumnStatus
    renamed_from: str | None = None
    dtype_old: str | None = None
    dtype_new: str | None = None
    null_ratio_old: float | None = None
    null_ratio_new: float | None = None
    cardinality_old: int | None = None
    cardinality_new: int | None = None


class DiffResult(BaseModel):
    """Full comparison between an old and a new dataset."""

    old: DatasetSchema
    new: DatasetSchema
    changes: list[Change] = Field(default_factory=list)
    columns: list[ColumnComparison] = Field(default_factory=list)

    def of_type(self, change_type: ChangeType) -> list[Change]:
        return [change for change in self.changes if change.type is change_type]


class ClassifiedChange(BaseModel):
    """A change together with the severity the rule engine assigned to it."""

    change: Change
    severity: Severity | None = None
    rule: str | None = None


class AnalysisReport(BaseModel):
    """Final result of an analysis run."""

    generated_at: date
    old_source: str
    new_source: str
    current_version: str
    next_version: str
    bump: Severity | None
    diff: DiffResult
    classified: list[ClassifiedChange] = Field(default_factory=list)

    def by_severity(self, severity: Severity) -> list[ClassifiedChange]:
        return [item for item in self.classified if item.severity is severity]
