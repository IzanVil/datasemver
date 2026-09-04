"""SemVer-style versioning for datasets."""

from datasemver.core.analyzer import analyze
from datasemver.core.models import AnalysisReport, ChangeType, DiffResult, Severity

__version__ = "0.2.4"

__all__ = ["AnalysisReport", "ChangeType", "DiffResult", "Severity", "__version__", "analyze"]
