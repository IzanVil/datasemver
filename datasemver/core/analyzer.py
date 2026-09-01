"""Analysis pipeline: load, diff, classify and version."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from datasemver.core.differ import DiffConfig, diff_schemas
from datasemver.core.models import AnalysisReport, DatasetSchema
from datasemver.formats.loader import load_schema
from datasemver.rules.engine import RuleSet, highest_severity, load_rules
from datasemver.utils.version import bump_version

DEFAULT_VERSION = "0.0.0"


def analyze(
    old_path: str | Path,
    new_path: str | Path,
    rules: RuleSet | str | Path | None = None,
    current_version: str = DEFAULT_VERSION,
    diff_config: DiffConfig | None = None,
) -> AnalysisReport:
    """Compare two dataset files and return the suggested version bump."""
    old_schema = load_schema(old_path)
    new_schema = load_schema(new_path)
    return analyze_schemas(
        old_schema,
        new_schema,
        rules=rules,
        current_version=current_version,
        diff_config=diff_config,
    )


def analyze_schemas(
    old: DatasetSchema,
    new: DatasetSchema,
    rules: RuleSet | str | Path | None = None,
    current_version: str = DEFAULT_VERSION,
    diff_config: DiffConfig | None = None,
) -> AnalysisReport:
    """Compare two already loaded dataset profiles."""
    rule_set = rules if isinstance(rules, RuleSet) else load_rules(rules)
    diff = diff_schemas(old, new, config=diff_config)
    classified = rule_set.evaluate(diff)
    bump = highest_severity(classified)

    return AnalysisReport(
        generated_at=date.today(),
        old_source=old.source,
        new_source=new.source,
        current_version=current_version,
        next_version=bump_version(current_version, bump),
        bump=bump,
        diff=diff,
        classified=classified,
    )
