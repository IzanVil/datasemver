"""Rule engine mapping detected changes to SemVer severities."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    "cardinality_change_greater_than": (ChangeType.CARDINALITY_CHANGED, "change_pct"),
}

EVALUATION_ORDER = (Severity.MAJOR, Severity.MINOR, Severity.PATCH)


class RuleError(ValueError):
    """Raised when a rules file cannot be understood."""


@dataclass(frozen=True)
class Rule:
    """A single rule: a change type, optionally gated by a numeric threshold."""

    name: str
    change_type: ChangeType
    metric: str | None = None
    threshold: float | None = None

    def matches(self, change: Change) -> bool:
        if change.type is not self.change_type:
            return False
        if self.metric is None or self.threshold is None:
            return True
        value = change.metrics.get(self.metric)
        return value is not None and value > self.threshold


@dataclass(frozen=True)
class RuleSet:
    """Rules grouped by the severity they assign."""

    rules: dict[Severity, list[Rule]] = field(default_factory=dict)

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
        for raw_severity, entries in mapping.items():
            severity = _parse_severity(raw_severity)
            for entry in entries or []:
                rules[severity].append(_parse_rule(entry))
        return cls(rules=rules)

    def classify(self, change: Change) -> ClassifiedChange:
        """Assign the highest severity whose rules match the change."""
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
    if isinstance(entry, str):
        return Rule(name=entry, change_type=_parse_change_type(entry))

    if isinstance(entry, dict) and len(entry) == 1:
        name, threshold = next(iter(entry.items()))
        if name not in THRESHOLD_RULES:
            raise RuleError(f"rule {name!r} does not accept a threshold")
        if not isinstance(threshold, (int, float)):
            raise RuleError(f"threshold for rule {name!r} must be numeric, got {threshold!r}")
        change_type, metric = THRESHOLD_RULES[name]
        return Rule(name=name, change_type=change_type, metric=metric, threshold=float(threshold))

    raise RuleError(f"invalid rule entry: {entry!r}")


def _parse_change_type(name: str) -> ChangeType:
    try:
        return ChangeType(name)
    except ValueError as error:
        raise RuleError(f"unknown rule {name!r}") from error
