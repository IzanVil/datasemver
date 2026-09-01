import pandas as pd
import pytest

from datasemver.core.differ import diff_schemas
from datasemver.core.models import Change, ChangeType, Severity
from datasemver.formats.loader import load_schema, schema_from_frame
from datasemver.rules.engine import (
    DEFAULT_RULES_PATH,
    RuleError,
    RuleSet,
    highest_severity,
    load_rules,
)


def change(change_type: ChangeType, **metrics: float) -> Change:
    return Change(type=change_type, description=change_type.value, metrics=metrics)


def test_default_rules_load_from_disk():
    rules = load_rules()

    assert DEFAULT_RULES_PATH.exists()
    assert {rule.name for rule in rules.rules[Severity.MAJOR]} >= {
        "column_removed",
        "type_changed_incompatible",
    }


def test_severity_assignment_per_change_type():
    rules = RuleSet.default()

    assert rules.classify(change(ChangeType.COLUMN_REMOVED)).severity is Severity.MAJOR
    assert rules.classify(change(ChangeType.COLUMN_ADDED)).severity is Severity.MINOR
    assert rules.classify(change(ChangeType.NULLS_FIXED)).severity is Severity.PATCH


def test_threshold_rule_only_fires_above_the_limit():
    rules = RuleSet.default()

    small = rules.classify(change(ChangeType.ROW_COUNT_DECREASED, decrease_pct=5.0))
    large = rules.classify(change(ChangeType.ROW_COUNT_DECREASED, decrease_pct=45.0))

    assert small.severity is Severity.MINOR
    assert small.rule == "row_count_decreased"
    assert large.severity is Severity.MAJOR
    assert large.rule == "row_count_decrease_greater_than"


def test_highest_severity_wins_over_evaluation_order():
    rules = RuleSet.from_mapping(
        {
            "major": ["column_added"],
            "minor": ["column_added", "nulls_fixed"],
        }
    )

    assert rules.classify(change(ChangeType.COLUMN_ADDED)).severity is Severity.MAJOR


def test_unclassified_change_has_no_severity():
    rules = RuleSet.from_mapping({"major": ["column_removed"]})

    classified = rules.classify(change(ChangeType.COLUMN_ADDED))

    assert classified.severity is None
    assert classified.rule is None


def test_custom_rules_downgrade_a_removal(tmp_path):
    path = tmp_path / "custom.yaml"
    path.write_text("minor:\n  - column_removed\n", encoding="utf-8")

    rules = load_rules(path)

    assert rules.classify(change(ChangeType.COLUMN_REMOVED)).severity is Severity.MINOR


def test_highest_severity_of_a_diff(old_csv, new_csv):
    diff = diff_schemas(load_schema(old_csv), load_schema(new_csv))

    assert highest_severity(RuleSet.default().evaluate(diff)) is Severity.MAJOR


def test_highest_severity_of_empty_evaluation():
    old = schema_from_frame(pd.DataFrame({"a": [1, 2]}), "old")

    assert highest_severity(RuleSet.default().evaluate(diff_schemas(old, old))) is None


def test_unknown_rule_name_is_rejected():
    with pytest.raises(RuleError):
        RuleSet.from_mapping({"major": ["column_exploded"]})


def test_unknown_severity_is_rejected():
    with pytest.raises(RuleError):
        RuleSet.from_mapping({"critical": ["column_removed"]})


def test_threshold_on_a_non_threshold_rule_is_rejected():
    with pytest.raises(RuleError):
        RuleSet.from_mapping({"major": [{"column_removed": 10}]})


def test_non_numeric_threshold_is_rejected():
    with pytest.raises(RuleError):
        RuleSet.from_mapping({"major": [{"row_count_decrease_greater_than": "twenty"}]})


def test_missing_rules_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_rules(tmp_path / "absent.yaml")


def test_severity_ordering():
    assert Severity.MAJOR > Severity.MINOR > Severity.PATCH
    assert max([Severity.PATCH, Severity.MAJOR, Severity.MINOR]) is Severity.MAJOR
