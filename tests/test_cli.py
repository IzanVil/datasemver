import json
import re
from pathlib import Path

from typer.testing import CliRunner

import datasemver
from datasemver.cli.main import app

runner = CliRunner()


def run(*args):
    return runner.invoke(app, list(args))


def test_reports_the_suggested_bump(old_csv, new_csv):
    result = run("diff", str(old_csv), str(new_csv))

    assert result.exit_code == 0
    assert "MAJOR" in result.stdout
    assert "legacy_code" in result.stdout


def test_json_output_is_parseable(old_csv, new_csv):
    result = run("diff", str(old_csv), str(new_csv), "--json")
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["bump"] == "major"
    assert payload["next_version"] == "1.0.0"
    assert payload["diff"]["new"]["row_count"] == 10
    assert any(column["status"] == "removed" for column in payload["diff"]["columns"])


def test_json_output_carries_every_classified_change(old_csv, new_csv):
    payload = json.loads(run("diff", str(old_csv), str(new_csv), "--json").stdout)
    rules = {item["rule"] for item in payload["classified"]}

    assert {"column_removed", "type_changed_incompatible", "nulls_fixed"} <= rules


def test_writes_the_changelog(old_csv, new_csv, tmp_path):
    output = tmp_path / "CHANGELOG.md"

    result = run(
        "diff", str(old_csv), str(new_csv), "--output", str(output), "--current-version", "0.9.0"
    )

    assert result.exit_code == 0
    assert "## [1.0.0]" in output.read_text(encoding="utf-8")
    assert str(output) in result.stdout.replace("\n", "")


def test_custom_rules_change_the_bump(old_csv, new_csv, tmp_path):
    rules = tmp_path / "lenient.yaml"
    rules.write_text("minor:\n  - column_removed\n", encoding="utf-8")

    payload = json.loads(
        run("diff", str(old_csv), str(new_csv), "--rules", str(rules), "--json").stdout
    )

    assert payload["bump"] == "minor"


def test_identical_datasets_keep_the_version(old_csv):
    result = run("diff", str(old_csv), str(old_csv), "--current-version", "2.1.0")

    assert result.exit_code == 0
    assert "NONE" in result.stdout
    assert "2.1.0 -> 2.1.0" in result.stdout.replace("\n", "")


def test_missing_file_exits_with_two(tmp_path, new_csv):
    result = run("diff", str(tmp_path / "absent.csv"), str(new_csv))

    assert result.exit_code == 2


def test_unsupported_extension_exits_with_two(tmp_path, new_csv):
    other = tmp_path / "data.avro"
    other.write_text("noop", encoding="utf-8")

    result = run("diff", str(other), str(new_csv))

    assert result.exit_code == 2


def test_invalid_current_version_exits_with_two(old_csv, new_csv):
    assert run("diff", str(old_csv), str(new_csv), "--current-version", "one").exit_code == 2


def test_unknown_rule_exits_with_two(old_csv, new_csv, tmp_path):
    rules = tmp_path / "broken.yaml"
    rules.write_text("major:\n  - column_exploded\n", encoding="utf-8")

    assert run("diff", str(old_csv), str(new_csv), "--rules", str(rules)).exit_code == 2


def test_missing_rules_file_exits_with_two(old_csv, new_csv, tmp_path):
    result = run("diff", str(old_csv), str(new_csv), "--rules", str(tmp_path / "absent.yaml"))

    assert result.exit_code == 2


def test_rules_command_prints_the_defaults():
    result = run("rules")

    assert result.exit_code == 0
    for severity in ("major", "minor", "patch"):
        assert severity in result.stdout
    assert "row_count_decrease_greater_than > 20" in result.stdout


def test_rules_command_reads_a_custom_file(tmp_path):
    rules = tmp_path / "custom.yaml"
    rules.write_text("major:\n  - column_removed\n", encoding="utf-8")

    result = run("rules", str(rules))

    assert result.exit_code == 0
    assert "column_removed" in result.stdout


def test_rules_command_with_a_missing_file_exits_with_two(tmp_path):
    assert run("rules", str(tmp_path / "absent.yaml")).exit_code == 2


def test_json_and_output_can_be_combined(old_csv, new_csv, tmp_path):
    output = tmp_path / "CHANGELOG.md"

    result = run("diff", str(old_csv), str(new_csv), "--json", "--output", str(output))

    assert json.loads(result.stdout)["bump"] == "major"
    assert output.exists()


def test_without_arguments_the_help_is_shown():
    result = run()

    assert "Usage" in result.stdout
    assert "diff" in result.stdout


def test_the_declared_version_matches_the_packaging_metadata():
    """`__version__` and `pyproject.toml` drift apart silently; the release flow needs both.

    Parsed with a regex rather than `tomllib`, which the supported 3.10 does not ship.
    """
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'(?m)^version = "([^"]+)"', pyproject)

    assert declared is not None
    assert datasemver.__version__ == declared.group(1)
