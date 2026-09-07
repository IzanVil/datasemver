"""SemVer-style versioning for datasets.

What this namespace exports is the supported interface. Everything reachable from here can be
relied on; the module paths underneath it are free to move, and a release that moves one is
not a breaking release, because the name it is reached by did not change.
"""

from datasemver.core.analyzer import analyze, analyze_schemas
from datasemver.core.models import (
    AnalysisReport,
    Change,
    ChangeType,
    ClassifiedChange,
    ColumnStats,
    DatasetSchema,
    DiffResult,
    Severity,
)
from datasemver.core.profile import ProfileError, read_profile, write_profile
from datasemver.core.rows import compare_rows
from datasemver.formats.loader import load_frame, load_schema, schema_from_frame
from datasemver.rules.engine import RuleError, RuleSet, load_rules

__version__ = "0.6.0"

__all__ = [
    "AnalysisReport",
    "Change",
    "ChangeType",
    "ClassifiedChange",
    "ColumnStats",
    "DatasetSchema",
    "DiffResult",
    "ProfileError",
    "RuleError",
    "RuleSet",
    "Severity",
    "__version__",
    "analyze",
    "analyze_schemas",
    "compare_rows",
    "load_frame",
    "load_rules",
    "load_schema",
    "read_profile",
    "schema_from_frame",
    "write_profile",
]
