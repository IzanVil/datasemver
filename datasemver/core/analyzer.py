"""Analysis pipeline: load, diff, classify and version."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from datasemver.core.differ import DiffConfig, diff_schemas
from datasemver.core.models import AnalysisReport, Change, DatasetSchema
from datasemver.core.rows import compare_rows
from datasemver.formats.loader import describe_source, load_frame, load_schema, schema_from_frame
from datasemver.rules.engine import RuleSet, highest_severity, load_rules
from datasemver.utils.version import bump_version

DEFAULT_VERSION = "0.0.0"


def analyze(
    old_path: str | Path,
    new_path: str | Path,
    rules: RuleSet | str | Path | None = None,
    current_version: str = DEFAULT_VERSION,
    diff_config: DiffConfig | None = None,
    schema_only: bool = False,
    key: list[str] | None = None,
) -> AnalysisReport:
    """Compare two dataset files and return the suggested version bump.

    `schema_only` profiles a Parquet source from its footer instead of its rows, which is a
    seek rather than a decode. It answers the schema-level questions only: with no data read
    there is no distribution to compare, so a shift in one is not reported as absent, it is
    simply not looked for.
    """
    if key:
        # Both frames are needed at once to match rows, so they are loaded once and the
        # profiles taken from them rather than read a second time.
        old_frame, new_frame = load_frame(old_path), load_frame(new_path)
        old_schema = schema_from_frame(old_frame, source=describe_source(old_path))
        new_schema = schema_from_frame(new_frame, source=describe_source(new_path))
        extra = compare_rows(old_frame, new_frame, key, old_schema.source, new_schema.source)
    else:
        old_schema = load_schema(old_path, schema_only=schema_only)
        new_schema = load_schema(new_path, schema_only=schema_only)
        extra = []

    return analyze_schemas(
        old_schema,
        new_schema,
        rules=rules,
        current_version=current_version,
        diff_config=diff_config,
        extra_changes=extra,
    )


def analyze_schemas(
    old: DatasetSchema,
    new: DatasetSchema,
    rules: RuleSet | str | Path | None = None,
    current_version: str = DEFAULT_VERSION,
    diff_config: DiffConfig | None = None,
    extra_changes: list[Change] | None = None,
) -> AnalysisReport:
    """Compare two already loaded dataset profiles.

    `extra_changes` carries findings that did not come from the profiles -- the row-level
    comparison, which needs the data itself -- so they are classified and versioned by the
    same rules as everything else instead of arriving as a separate kind of result.
    """
    rule_set = rules if isinstance(rules, RuleSet) else load_rules(rules)
    diff = diff_schemas(old, new, config=diff_config)
    if extra_changes:
        diff.changes.extend(extra_changes)
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
