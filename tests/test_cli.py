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


def test_square_brackets_in_an_error_reach_the_terminal(old_csv, new_csv, monkeypatch):
    """Rich reads `[sql]` as a style tag and prints nothing for it.

    The message that says how to install the database support is
    `pip install "datasemver[sql]"`, and it arrived as `pip install "datasemver"` -- advice
    that installs the wrong thing. Every error the CLI prints goes through the same line, so
    any bracket in any message was being eaten the same way.
    """
    import datasemver.cli.main as main
    from datasemver.formats.sql import INSTALL_HINT

    def refuse(*args, **kwargs):
        raise ValueError(INSTALL_HINT)

    monkeypatch.setattr(main, "analyze", refuse)

    result = run("diff", str(old_csv), str(new_csv))

    assert result.exit_code == 2
    assert "datasemver[sql]" in result.output


def test_the_console_does_not_use_the_pre_vt_windows_api():
    """Rich falls back to the Win32 console API when it cannot confirm VT support, which it
    cannot do when stdout is a pipe. It then calls that API on the pipe, and
    `datasemver rules | findstr x` dies with `OSError: [Errno 22]`. Nothing here is
    Windows-only, so the setting is asserted rather than the platform."""
    from datasemver.cli.main import console, error_console

    assert console.legacy_windows is False
    assert error_console.legacy_windows is False


# --- the gate -------------------------------------------------------------------------------


def test_a_breaking_change_exits_zero_when_nothing_was_asked_of_it(old_csv, new_csv):
    """The gate is opt-in: without --fail-on the command reports and says nothing about it."""
    assert run("diff", str(old_csv), str(new_csv)).exit_code == 0


def test_a_breaking_change_is_refused_when_the_gate_is_set(old_csv, new_csv):
    result = run("diff", str(old_csv), str(new_csv), "--fail-on", "major")

    assert result.exit_code == 1
    assert "refused" in result.output


def test_the_gate_lets_through_what_it_was_not_asked_to_stop(old_csv):
    """Identical datasets suggest no bump at all, so even the lowest threshold passes."""
    assert run("diff", str(old_csv), str(old_csv), "--fail-on", "patch").exit_code == 0


def test_a_run_that_could_not_happen_is_not_the_same_as_one_that_was_refused(new_csv):
    """Exit 2 means the command failed; a caller that cannot tell them apart is stuck."""
    assert run("diff", "no-such-file.csv", str(new_csv), "--fail-on", "major").exit_code == 2


def test_the_gate_still_prints_the_report_it_is_refusing(old_csv, new_csv):
    result = run("diff", str(old_csv), str(new_csv), "--fail-on", "major")

    assert "MAJOR" in result.output


def test_the_gate_leaves_json_output_parseable(old_csv, new_csv):
    """The refusal goes to stderr so a caller can gate on the code and still read the JSON."""
    result = runner.invoke(
        app, ["diff", str(old_csv), str(new_csv), "--json", "--fail-on", "major"]
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["bump"] == "major"


def test_an_unknown_severity_is_rejected_by_the_parser(old_csv, new_csv):
    assert run("diff", str(old_csv), str(new_csv), "--fail-on", "enormous").exit_code == 2


# --- the profile command --------------------------------------------------------------------


def test_writing_a_profile_reports_where_it_went(tmp_path, old_csv):
    destination = tmp_path / "old.profile.json"

    result = run("profile", str(old_csv), "-o", str(destination))

    assert result.exit_code == 0
    assert destination.exists()
    assert "profile written" in result.output


def test_a_profile_can_be_compared_against_without_the_dataset(tmp_path, old_csv, new_csv):
    copied = tmp_path / "old.csv"
    copied.write_bytes(old_csv.read_bytes())
    destination = tmp_path / "old.profile.json"
    run("profile", str(copied), "-o", str(destination))
    copied.unlink()

    payload = json.loads(run("diff", str(destination), str(new_csv), "--json").stdout)

    assert payload["bump"] == "major"


def test_profiling_something_that_is_not_there_fails_cleanly(tmp_path):
    result = run("profile", str(tmp_path / "absent.csv"))

    assert result.exit_code == 2
    assert "error" in result.output


# --- the version flag -------------------------------------------------------------------------


def test_the_version_flag_prints_the_running_version():
    """A profile records the version that wrote it, so a reader needs to name its own."""
    result = run("--version")

    assert result.exit_code == 0
    assert datasemver.__version__ in result.output


# --- keying on a column -----------------------------------------------------------------------


def test_a_key_reports_the_rows_that_changed(tmp_path):
    old, new = tmp_path / "old.csv", tmp_path / "new.csv"
    old.write_text("id,v\n1,a\n2,b\n3,c\n", encoding="utf-8")
    new.write_text("id,v\n1,a\n2,B\n3,C\n", encoding="utf-8")

    payload = json.loads(run("diff", str(old), str(new), "--key", "id", "--json").stdout)

    modified = next(c for c in payload["diff"]["changes"] if c["type"] == "rows_modified")
    assert modified["metrics"]["rows_modified"] == 2


def test_a_composite_key_is_given_one_flag_per_column(tmp_path):
    old, new = tmp_path / "old.csv", tmp_path / "new.csv"
    old.write_text("a,b,v\n1,1,x\n1,2,y\n", encoding="utf-8")
    new.write_text("a,b,v\n1,1,x\n1,2,Y\n", encoding="utf-8")

    payload = json.loads(run("diff", str(old), str(new), "-k", "a", "-k", "b", "--json").stdout)

    assert any(c["type"] == "rows_modified" for c in payload["diff"]["changes"])


def test_a_key_that_cannot_identify_a_row_fails_cleanly(tmp_path):
    old, new = tmp_path / "old.csv", tmp_path / "new.csv"
    old.write_text("id,v\n1,a\n1,b\n", encoding="utf-8")
    new.write_text("id,v\n1,a\n2,b\n", encoding="utf-8")

    result = run("diff", str(old), str(new), "--key", "id")

    assert result.exit_code == 2
    assert "repeat a key" in result.output


# --- the schema-only shortcut -------------------------------------------------------------------


def test_schema_only_answers_the_breaking_question(tmp_path):
    import pandas as pd

    old, new = tmp_path / "old.parquet", tmp_path / "new.parquet"
    pd.DataFrame({"id": range(20), "legacy": ["x"] * 20}).to_parquet(old)
    pd.DataFrame({"id": range(20)}).to_parquet(new)

    result = run("diff", str(old), str(new), "--schema-only", "--json")
    payload = json.loads(result.stdout)

    assert payload["bump"] == "major"
    assert any(c["type"] == "column_removed" for c in payload["diff"]["changes"])
