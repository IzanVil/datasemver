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


def test_threshold_is_strict_at_the_boundary():
    rules = RuleSet.default()

    exact = rules.classify(change(ChangeType.ROW_COUNT_DECREASED, decrease_pct=20.0))
    above = rules.classify(change(ChangeType.ROW_COUNT_DECREASED, decrease_pct=20.0001))

    assert exact.severity is Severity.MINOR
    assert above.severity is Severity.MAJOR


def test_threshold_rule_without_its_metric_does_not_match():
    rules = RuleSet.from_mapping({"major": [{"row_count_decrease_greater_than": 20}]})

    assert rules.classify(change(ChangeType.ROW_COUNT_DECREASED)).severity is None


def test_empty_rules_file_classifies_nothing(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")

    rules = load_rules(path)

    assert rules.classify(change(ChangeType.COLUMN_REMOVED)).severity is None


def test_severity_with_no_rules_is_accepted():
    rules = RuleSet.from_mapping({"major": None, "minor": ["column_added"]})

    assert rules.rules[Severity.MAJOR] == []
    assert rules.classify(change(ChangeType.COLUMN_ADDED)).severity is Severity.MINOR


def test_severity_names_are_case_insensitive():
    rules = RuleSet.from_mapping({"MAJOR": ["column_removed"]})

    assert rules.classify(change(ChangeType.COLUMN_REMOVED)).severity is Severity.MAJOR


def test_rules_file_that_is_not_a_mapping_is_rejected(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("- column_removed\n", encoding="utf-8")

    with pytest.raises(RuleError):
        load_rules(path)


def test_invalid_rule_entry_is_rejected():
    with pytest.raises(RuleError):
        RuleSet.from_mapping({"major": [{"a": 1, "b": 2}]})


def test_the_strongest_severity_wins_across_several_matches():
    rules = RuleSet.default()
    classified = [
        rules.classify(change(ChangeType.NULLS_FIXED, delta_pct=5.0)),
        rules.classify(change(ChangeType.COLUMN_ADDED)),
        rules.classify(change(ChangeType.COLUMN_REMOVED)),
    ]

    assert highest_severity(classified) is Severity.MAJOR
    assert highest_severity(classified[:2]) is Severity.MINOR
    assert highest_severity(classified[:1]) is Severity.PATCH


def test_unclassified_changes_do_not_raise_the_bump():
    rules = RuleSet.from_mapping({"patch": ["nulls_fixed"]})
    classified = [
        rules.classify(change(ChangeType.COLUMN_REMOVED)),
        rules.classify(change(ChangeType.NULLS_FIXED)),
    ]

    assert highest_severity(classified) is Severity.PATCH


def test_bundled_rules_cover_every_change_type():
    rules = RuleSet.default()
    covered = {rule.change_type for entries in rules.rules.values() for rule in entries}

    assert covered == set(ChangeType)


def test_severity_compares_by_impact_not_by_name():
    assert Severity.MAJOR > "minor"
    assert Severity.PATCH <= "patch"
    assert not Severity.MINOR >= "major"


def test_severity_cannot_be_compared_to_other_types():
    with pytest.raises(TypeError):
        _ = Severity.MAJOR < 3
    with pytest.raises(TypeError):
        _ = Severity.MAJOR >= "not-a-severity"


# --- rules scoped to columns ------------------------------------------------------------------


def rules_from(text: str, tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(text, encoding="utf-8")
    return load_rules(path)


CONTRACT = """
major:
  - nulls_introduced: {columns: [user_id, email]}
minor:
  - nulls_introduced
ignore:
  - distribution_shift: {columns: [ingested_at]}
"""


def nulls_in(column: str) -> Change:
    return Change(type=ChangeType.NULLS_INTRODUCED, column=column, description="nulls")


def test_a_scoped_rule_covers_the_columns_it_names(tmp_path):
    rule_set = rules_from(CONTRACT, tmp_path)

    assert rule_set.classify(nulls_in("email")).severity is Severity.MAJOR


def test_a_scoped_rule_leaves_every_other_column_to_the_general_one(tmp_path):
    """The point of scoping: one column is protected without raising the bar everywhere."""
    rule_set = rules_from(CONTRACT, tmp_path)

    assert rule_set.classify(nulls_in("notes")).severity is Severity.MINOR


def test_an_ignored_change_is_reported_but_left_unclassified(tmp_path):
    """Detected and expected are different answers from silence, and it stays visible."""
    rule_set = rules_from(CONTRACT, tmp_path)
    drift = Change(type=ChangeType.DISTRIBUTION_SHIFT, column="ingested_at", description="drift")

    classified = rule_set.classify(drift)

    assert classified.severity is None
    assert classified.rule == "distribution_shift"


def test_ignoring_one_column_does_not_ignore_the_others(tmp_path):
    rule_set = rules_from(CONTRACT + "\nmajor:\n  - distribution_shift\n", tmp_path)
    elsewhere = Change(type=ChangeType.DISTRIBUTION_SHIFT, column="amount", description="drift")

    assert rule_set.classify(elsewhere).severity is Severity.MAJOR


def test_a_threshold_and_columns_can_be_given_together(tmp_path):
    rule_set = rules_from(
        "major:\n  - row_count_decrease_greater_than: {threshold: 20, columns: [orders]}\n",
        tmp_path,
    )
    rule = rule_set.rules[Severity.MAJOR][0]

    assert rule.threshold == 20
    assert rule.columns == frozenset({"orders"})


def test_the_shorthand_for_a_threshold_still_works(tmp_path):
    """Every rules file written before columns existed has to keep parsing unchanged."""
    rule_set = rules_from("major:\n  - row_count_decrease_greater_than: 20\n", tmp_path)

    assert rule_set.rules[Severity.MAJOR][0].threshold == 20


def test_columns_written_as_a_bare_string_is_an_error(tmp_path):
    """It reads as one column to a person and as five to anything that iterates a string."""
    with pytest.raises(RuleError, match="must be a list"):
        rules_from("major:\n  - column_removed: {columns: user_id}\n", tmp_path)


def test_an_empty_column_list_is_an_error(tmp_path):
    with pytest.raises(RuleError, match="matches nothing"):
        rules_from("major:\n  - column_removed: {columns: []}\n", tmp_path)


def test_an_unknown_option_on_a_rule_is_an_error(tmp_path):
    with pytest.raises(RuleError, match=r"does not take \['umbral'\]"):
        rules_from("major:\n  - column_removed: {umbral: 3}\n", tmp_path)


def test_a_threshold_on_a_rule_that_takes_none_is_still_an_error(tmp_path):
    with pytest.raises(RuleError, match="does not accept a threshold"):
        rules_from("major:\n  - column_removed: {threshold: 3}\n", tmp_path)


def test_a_boolean_is_not_a_threshold(tmp_path):
    """YAML reads `true` as a boolean, and a boolean is an integer in Python."""
    with pytest.raises(RuleError, match="must be numeric"):
        rules_from("major:\n  - row_count_decrease_greater_than: true\n", tmp_path)
