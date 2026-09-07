"""Rule engine mapping detected changes to SemVer severities."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from datasemver.core.models import Change, ChangeType, ClassifiedChange, DiffResult, Severity

DEFAULT_RULES_PATH = Path(__file__).with_name("default_rules.yaml")

THRESHOLD_RULES: dict[str, tuple[ChangeType, str]] = {
    "row_count_decrease_greater_than": (ChangeType.ROW_COUNT_DECREASED, "decrease_pct"),
    "row_count_increase_greater_than": (ChangeType.ROW_COUNT_INCREASED, "increase_pct"),
    "null_ratio_increase_greater_than": (ChangeType.NULLS_INTRODUCED, "delta_pct"),
    "null_ratio_decrease_greater_than": (ChangeType.NULLS_FIXED, "delta_pct"),
    "mean_shift_greater_than": (ChangeType.DISTRIBUTION_SHIFT, "mean_shift_pct"),
    "ks_statistic_greater_than": (ChangeType.DISTRIBUTION_SHIFT, "ks_statistic"),
    "psi_greater_than": (ChangeType.CATEGORY_BALANCE_SHIFT, "psi"),
    "rows_modified_greater_than": (ChangeType.ROWS_MODIFIED, "modified_pct"),
    "rows_replaced_greater_than": (ChangeType.ROWS_REPLACED, "replaced_pct"),
    "cardinality_change_greater_than": (ChangeType.CARDINALITY_CHANGED, "change_pct"),
}

EVALUATION_ORDER = (Severity.MAJOR, Severity.MINOR, Severity.PATCH)

# Not a severity: a list of changes to detect, report and deliberately not count.
IGNORE_KEY = "ignore"


class RuleError(ValueError):
    """Raised when a rules file cannot be understood."""


@dataclass(frozen=True)
class Rule:
    """A change type, optionally gated by a numeric threshold and by which columns it covers.

    `columns` is what turns a rule set into a contract about particular data rather than a
    uniform sensitivity. Without it the only way to tolerate the column that drifts by design
    -- an `ingested_at`, a load counter -- is to raise the threshold for every column at once,
    which spends the signal everywhere to silence it in one place.
    """

    name: str
    change_type: ChangeType
    metric: str | None = None
    threshold: float | None = None
    columns: frozenset[str] | None = None

    def matches(self, change: Change) -> bool:
        if change.type is not self.change_type:
            return False
        if self.columns is not None and change.column not in self.columns:
            return False
        if self.metric is None or self.threshold is None:
            return True
        value = change.metrics.get(self.metric)
        return value is not None and value > self.threshold


@dataclass(frozen=True)
class RuleSet:
    """Rules grouped by the severity they assign, plus the ones that assign none."""

    rules: dict[Severity, list[Rule]] = field(default_factory=dict)
    ignored: list[Rule] = field(default_factory=list)

    @classmethod
    def default(cls) -> RuleSet:
        return cls.from_file(DEFAULT_RULES_PATH)

    @classmethod
    def from_file(cls, path: str | Path) -> RuleSet:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"rules file not found: {path}")
        return cls.from_mapping(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> RuleSet:
        if not isinstance(mapping, dict):
            raise RuleError("rules file must contain a mapping of severity to rule list")

        rules: dict[Severity, list[Rule]] = {severity: [] for severity in EVALUATION_ORDER}
        ignored: list[Rule] = []
        for raw_severity, entries in mapping.items():
            parsed = [_parse_rule(entry) for entry in entries or []]
            if str(raw_severity).lower() == IGNORE_KEY:
                ignored.extend(parsed)
                continue
            rules[_parse_severity(raw_severity)].extend(parsed)
        return cls(rules=rules, ignored=ignored)

    def classify(self, change: Change) -> ClassifiedChange:
        """Assign the highest severity whose rules match the change.

        The ignore list is consulted first and on purpose: a change it names is reported as
        detected and left unclassified, so it is visible in the diff and contributes nothing
        to the bump. Silence and "this was expected" are different answers.
        """
        for rule in self.ignored:
            if rule.matches(change):
                return ClassifiedChange(change=change, rule=rule.name)
        for severity in EVALUATION_ORDER:
            for rule in self.rules.get(severity, []):
                if rule.matches(change):
                    return ClassifiedChange(change=change, severity=severity, rule=rule.name)
        return ClassifiedChange(change=change)

    def evaluate(self, diff: DiffResult) -> list[ClassifiedChange]:
        return [self.classify(change) for change in diff.changes]


def load_rules(path: str | Path | None = None) -> RuleSet:
    """Load a rules file, falling back to the bundled defaults."""
    return RuleSet.default() if path is None else RuleSet.from_file(path)


def highest_severity(classified: list[ClassifiedChange]) -> Severity | None:
    """Return the strongest severity found, or None when nothing was classified."""
    severities = [item.severity for item in classified if item.severity is not None]
    return max(severities, default=None)


def _parse_severity(value: object) -> Severity:
    try:
        return Severity(str(value).lower())
    except ValueError as error:
        raise RuleError(
            f"unknown severity {value!r}, expected one of {[s.value for s in EVALUATION_ORDER]}"
        ) from error


def _parse_rule(entry: object) -> Rule:
    """Read one rule, in any of the three shapes a rules file may write it.

    `column_removed` is the whole rule; `row_count_decrease_greater_than: 20` is the
    shorthand a threshold rule has always had; and a mapping opens both settings at once,
    `nulls_introduced: {columns: [user_id]}` or `{threshold: 20, columns: [orders]}`.
    """
    if isinstance(entry, str):
        return Rule(name=entry, change_type=_parse_change_type(entry))

    if isinstance(entry, dict) and len(entry) == 1:
        name, options = next(iter(entry.items()))
        if isinstance(options, dict):
            return _rule_from_options(str(name), options)
        return _rule_with_threshold(str(name), options)

    raise RuleError(f"invalid rule entry: {entry!r}")


def _rule_with_threshold(name: str, threshold: object) -> Rule:
    if name not in THRESHOLD_RULES:
        raise RuleError(f"rule {name!r} does not accept a threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        raise RuleError(f"threshold for rule {name!r} must be numeric, got {threshold!r}")
    change_type, metric = THRESHOLD_RULES[name]
    return Rule(name=name, change_type=change_type, metric=metric, threshold=float(threshold))


def _rule_from_options(name: str, options: dict[str, object]) -> Rule:
    unknown = set(options) - {"threshold", "columns"}
    if unknown:
        raise RuleError(f"rule {name!r} does not take {sorted(unknown)!r}")

    columns = _parse_columns(name, options.get("columns"))
    if "threshold" not in options:
        return Rule(name=name, change_type=_parse_change_type(name), columns=columns)

    rule = _rule_with_threshold(name, options["threshold"])
    return replace(rule, columns=columns)


def _parse_columns(name: str, value: object) -> frozenset[str] | None:
    """A rule's columns, which must be a list: a bare string is a mistake worth naming.

    `columns: user_id` reads as one column to a person and as five columns to anything that
    iterates a string, and silently scoping a rule to `u`, `s`, `e`, `r` is the kind of
    wrong that never announces itself.
    """
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, list):
        raise RuleError(f"columns for rule {name!r} must be a list, got {value!r}")
    if not value:
        raise RuleError(f"columns for rule {name!r} is empty, which matches nothing")
    return frozenset(str(column) for column in value)


def _parse_change_type(name: str) -> ChangeType:
    try:
        return ChangeType(name)
    except ValueError as error:
        raise RuleError(f"unknown rule {name!r}") from error
