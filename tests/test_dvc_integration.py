"""Tests for running DataSemver over the datasets DVC versions.

DVC is not a dependency, so almost everything here drives a stand-in that answers `diff`
with canned JSON and serves `get` from a dictionary. That covers the parsing, the skip
rules and both report formats without installing anything.

What a stand-in cannot prove is that DVC still answers the way this module reads it, so one
test at the end builds a real DVC repository and is skipped when DVC is absent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from datasemver.cli.main import app
from datasemver.integrations import dvc

OLD_CSV = """id,name,phone,score,legacy_code
1,ana,600111222,10.5,a
2,bruno,600333444,11.0,b
3,carla,600555666,9.5,c
4,diego,600777888,12.0,d
"""

NEW_CSV = """id,name,phone,score,country
1,ana,+34 600 111 222,10.5,ES
2,bruno,+34 600 333 444,11.0,IT
3,carla,+34 600 555 666,9.5,PT
4,diego,+34 600 777 888,12.0,ES
5,elena,+34 600 999 000,10.0,FR
"""

MODIFIED = {"added": [], "deleted": [], "modified": [{"path": "data/customers.csv"}], "renamed": []}

runner = CliRunner()


class FakeDvc:
    """A stand-in for `run_dvc` that answers `diff` and serves `get` from memory."""

    def __init__(self, payload: dict, contents: dict[tuple[str, str], str] | None = None):
        self.payload = payload
        self.contents = contents or {}
        self.calls: list[list[str]] = []

    def __call__(self, arguments: list[str], repo) -> str:
        self.calls.append(arguments)
        if arguments[0] == "diff":
            return json.dumps(self.payload)
        if arguments[0] == "get":
            return self.serve(arguments)
        raise AssertionError(f"unexpected dvc command: {arguments}")

    def serve(self, arguments: list[str]) -> str:
        path = arguments[2]
        rev = arguments[arguments.index("--rev") + 1]
        destination = arguments[arguments.index("--out") + 1]
        try:
            body = self.contents[(rev, path)]
        except KeyError:
            raise dvc.DvcError(f"no cached copy of '{path}' at {rev}") from None
        Path(destination).write_text(body, encoding="utf-8")
        return ""


@pytest.fixture
def workspace(tmp_path):
    """A directory holding the newer dataset, standing in for a checked-out working tree."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "customers.csv").write_text(NEW_CSV, encoding="utf-8")
    return tmp_path


@pytest.fixture
def fake(monkeypatch):
    """Install a stand-in for `run_dvc` and hand it back for inspection."""

    def install(payload, contents=None):
        stub = FakeDvc(payload, contents)
        monkeypatch.setattr(dvc, "run_dvc", stub)
        return stub

    return install


# --- reading what dvc diff says ------------------------------------------------------------


def test_a_modified_dataset_is_found():
    changes = dvc.parse_diff(json.dumps(MODIFIED))

    assert [change.path for change in changes] == ["data/customers.csv"]
    assert changes[0].status == "modified"


def test_a_rename_carries_both_names():
    """DVC nests `{"old", "new"}` under `path` for a rename rather than giving a string.

    Reading every entry as a string is the mistake this asserts against: it would put a
    dict where a path belongs and only fail much later, at the file read.
    """
    output = json.dumps(
        {
            "added": [],
            "deleted": [],
            "modified": [],
            "renamed": [{"path": {"old": "data/old.csv", "new": "data/new.csv"}}],
        }
    )

    (change,) = dvc.parse_diff(output)

    assert change.old_path == "data/old.csv"
    assert change.new_path == "data/new.csv"
    assert change.path == "data/new.csv", "a rename is reported under where it ended up"


def test_an_added_dataset_has_no_previous_side():
    (change,) = dvc.parse_diff(json.dumps({"added": [{"path": "data/new.csv"}]}))

    assert change.old_path is None
    assert change.new_path == "data/new.csv"


def test_a_deleted_dataset_has_no_new_side():
    (change,) = dvc.parse_diff(json.dumps({"deleted": [{"path": "data/gone.csv"}]}))

    assert change.old_path == "data/gone.csv"
    assert change.new_path is None


@pytest.mark.parametrize("name", ["model.pkl", "weights.h5", "notes.txt", "data"])
def test_files_that_are_not_datasets_are_left_out(name):
    """A DVC repository versions models and images too, and none of those are comparable."""
    assert dvc.parse_diff(json.dumps({"modified": [{"path": name}]})) == []


@pytest.mark.parametrize(
    "name", ["a.csv", "a.csv.gz", "a.tsv.gz", "a.tsv", "a.json", "a.parquet", "a.CSV"]
)
def test_every_supported_format_is_picked_up(name):
    assert len(dvc.parse_diff(json.dumps({"modified": [{"path": name}]}))) == 1


def test_an_empty_diff_is_not_an_error():
    assert dvc.parse_diff(json.dumps({"added": [], "modified": []})) == []
    assert dvc.parse_diff("") == []


def test_output_that_is_not_json_is_reported_as_such():
    with pytest.raises(dvc.DvcError, match="not JSON"):
        dvc.parse_diff("ERROR: something went wrong")


def test_json_that_is_not_an_object_is_rejected():
    with pytest.raises(dvc.DvcError, match="not an object"):
        dvc.parse_diff("[1, 2, 3]")


@pytest.mark.parametrize("entry", ["a string", {"path": 42}, {"path": {"old": "a.csv"}}, {}])
def test_an_entry_of_an_unexpected_shape_is_ignored(entry):
    """A shape this module does not recognise is skipped, not crashed on."""
    assert dvc.parse_diff(json.dumps({"modified": [entry]})) == []


# --- what failure looks like ---------------------------------------------------------------


def test_a_missing_dvc_says_how_to_install_it(monkeypatch):
    def absent(*args, **kwargs):
        raise FileNotFoundError("dvc")

    monkeypatch.setattr(subprocess, "run", absent)

    with pytest.raises(dvc.DvcError, match="pip install dvc"):
        dvc.run_dvc(["diff"], repo=".")


def test_a_directory_that_is_not_a_dvc_repository_is_named(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 253, "", "ERROR: you are not inside of a DVC repository (checked up to '/tmp')"
        ),
    )

    with pytest.raises(dvc.DvcError, match="not a DVC repository"):
        dvc.run_dvc(["diff"], repo=".")


def test_data_that_was_never_pulled_points_at_dvc_pull(monkeypatch):
    """DVC calls this "unexpected error", which reads like a bug rather than a missing pull."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 1, "", "ERROR: unexpected error - [Errno 2] No storage files available: 'a.csv'"
        ),
    )

    with pytest.raises(dvc.DvcError, match="dvc pull"):
        dvc.run_dvc(["get"], repo=".")


def test_dvcs_support_footer_is_not_part_of_the_error():
    stderr = (
        "ERROR: failed to get diff - unknown Git revision 'nope'\n\n"
        "Having any troubles? Hit us up at https://dvc.org/support\n"
    )

    message = dvc.explain_failure(stderr, ["diff", "nope"])

    assert "unknown Git revision" in message
    assert "dvc.org/support" not in message


def test_a_silent_failure_still_says_something():
    assert dvc.explain_failure("", ["diff"]) == "dvc diff failed: dvc failed with no output"


def test_a_successful_command_returns_its_output(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "{}", "")
    )

    assert dvc.run_dvc(["diff"], repo=".") == "{}"


# --- the analysis --------------------------------------------------------------------------


def test_a_modified_dataset_is_compared_against_its_previous_revision(workspace, fake):
    fake(MODIFIED, {("HEAD^", "data/customers.csv"): OLD_CSV})

    reports, skipped = dvc.analyse(repo=workspace, rev="HEAD^")

    assert skipped == []
    (report,) = reports
    assert report.bump == "major"
    assert report.next_version == "1.0.0"
    assert {item["rule"] for item in report.changes} >= {"column_removed"}


def test_the_previous_version_comes_from_dvc_and_not_from_git(workspace, fake):
    """The point of the integration: git holds a pointer, so DVC has to serve the bytes."""
    stub = fake(MODIFIED, {("HEAD^", "data/customers.csv"): OLD_CSV})

    dvc.analyse(repo=workspace, rev="HEAD^")

    fetches = [call for call in stub.calls if call[0] == "get"]
    assert len(fetches) == 1
    assert "data/customers.csv" in fetches[0]
    assert "HEAD^" in fetches[0]


def test_the_working_tree_is_read_from_disk_rather_than_fetched(workspace, fake):
    """With no target revision the newer side is already checked out; fetching it would
    compare a revision against itself and report nothing."""
    stub = fake(MODIFIED, {("HEAD^", "data/customers.csv"): OLD_CSV})

    dvc.analyse(repo=workspace, rev="HEAD^")

    assert [
        call
        for call in stub.calls
        if call[0] == "get" and "--rev" in call and call[call.index("--rev") + 1] != "HEAD^"
    ] == []


def test_both_sides_are_fetched_when_two_revisions_are_named(workspace, fake):
    stub = fake(
        MODIFIED,
        {
            ("v1", "data/customers.csv"): OLD_CSV,
            ("v2", "data/customers.csv"): NEW_CSV,
        },
    )

    reports, skipped = dvc.analyse(repo=workspace, rev="v1", to_rev="v2")

    assert skipped == []
    assert reports[0].bump == "major"
    assert len([call for call in stub.calls if call[0] == "get"]) == 2


def test_a_rename_reads_each_side_by_its_own_name(workspace, fake):
    payload = {"renamed": [{"path": {"old": "data/old.csv", "new": "data/customers.csv"}}]}
    stub = fake(payload, {("HEAD^", "data/old.csv"): OLD_CSV})

    reports, skipped = dvc.analyse(repo=workspace, rev="HEAD^")

    assert skipped == []
    (report,) = reports
    assert report.renamed_from == "data/old.csv"
    assert report.path == "data/customers.csv"
    assert stub.calls[1][2] == "data/old.csv", "the old side was fetched under its old name"


def test_an_added_dataset_is_skipped_with_a_reason(workspace, fake):
    fake({"added": [{"path": "data/customers.csv"}]})

    reports, skipped = dvc.analyse(repo=workspace, rev="HEAD^")

    assert reports == []
    assert skipped == [("data/customers.csv", dvc.SKIP_REASONS["added"])]


def test_a_deleted_dataset_is_skipped_with_a_reason(workspace, fake):
    fake({"deleted": [{"path": "data/customers.csv"}]})

    _, skipped = dvc.analyse(repo=workspace, rev="HEAD^")

    assert skipped == [("data/customers.csv", dvc.SKIP_REASONS["deleted"])]


def test_a_dataset_missing_from_the_working_tree_points_at_dvc_checkout(tmp_path, fake):
    fake(MODIFIED, {("HEAD^", "data/customers.csv"): OLD_CSV})

    _, skipped = dvc.analyse(repo=tmp_path, rev="HEAD^")

    assert "dvc checkout" in skipped[0][1]


def test_data_that_cannot_be_fetched_is_skipped_rather_than_fatal(workspace, fake):
    """One dataset missing from the cache must not lose the report on the others."""
    payload = {"modified": [{"path": "data/customers.csv"}, {"path": "data/other.csv"}]}
    fake(payload, {("HEAD^", "data/customers.csv"): OLD_CSV})

    reports, skipped = dvc.analyse(repo=workspace, rev="HEAD^")

    assert [report.path for report in reports] == ["data/customers.csv"]
    assert skipped[0][0] == "data/other.csv"


def test_a_dataset_that_cannot_be_read_is_skipped(workspace, fake):
    """A corrupt file is a skip with a reason, not a traceback that loses the whole run."""
    (workspace / "data" / "customers.json").write_text("{ not json", encoding="utf-8")
    payload = {"modified": [{"path": "data/customers.json"}]}
    fake(payload, {("HEAD^", "data/customers.json"): "{ also not json"})

    reports, skipped = dvc.analyse(repo=workspace, rev="HEAD^")

    assert reports == []
    assert "could not be analysed" in skipped[0][1]


def test_naming_a_dataset_limits_the_run(workspace, fake):
    payload = {"modified": [{"path": "data/customers.csv"}, {"path": "data/other.csv"}]}
    fake(payload, {("HEAD^", "data/customers.csv"): OLD_CSV})

    reports, skipped = dvc.analyse(repo=workspace, rev="HEAD^", paths=["data/customers.csv"])

    assert [report.path for report in reports] == ["data/customers.csv"]
    assert skipped == [], "the dataset that was not asked for is not reported as skipped"


def test_a_rename_can_be_named_by_either_of_its_paths(workspace, fake):
    payload = {"renamed": [{"path": {"old": "data/old.csv", "new": "data/customers.csv"}}]}
    fake(payload, {("HEAD^", "data/old.csv"): OLD_CSV})

    reports, _ = dvc.analyse(repo=workspace, rev="HEAD^", paths=["data/old.csv"])

    assert len(reports) == 1


# --- the version each comparison starts from ------------------------------------------------


def test_the_version_recorded_beside_a_dataset_is_where_the_bump_starts(workspace, fake):
    """The sidecar is text, so git tracks it and it can be read straight out of the revision."""
    subprocess.run(["git", "init", "-q", str(workspace)], check=True, capture_output=True)
    for setting in (("user.email", "t@e.invalid"), ("user.name", "T")):
        subprocess.run(["git", "-C", str(workspace), "config", *setting], check=True)
    (workspace / "data" / "customers.csv.version").write_text("2.3.0\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(workspace), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-qm", "base"], check=True, capture_output=True
    )
    fake(MODIFIED, {("HEAD", "data/customers.csv"): OLD_CSV})

    reports, _ = dvc.analyse(repo=workspace, rev="HEAD")

    assert reports[0].current_version == "2.3.0"
    assert reports[0].next_version == "3.0.0"


def test_a_dataset_with_no_recorded_version_falls_back_to_the_default(workspace, fake):
    fake(MODIFIED, {("HEAD^", "data/customers.csv"): OLD_CSV})

    reports, _ = dvc.analyse(repo=workspace, rev="HEAD^", current_version="0.5.0")

    assert reports[0].current_version == "0.5.0"


def test_reading_a_version_outside_a_git_repository_is_not_an_error(tmp_path):
    assert dvc.recorded_version(tmp_path, "data/customers.csv", "HEAD") is None


# --- the two output formats ----------------------------------------------------------------


def test_the_json_payload_names_the_range_and_the_overall_bump(workspace, fake):
    fake(MODIFIED, {("HEAD^", "data/customers.csv"): OLD_CSV})
    reports, skipped = dvc.analyse(repo=workspace, rev="HEAD^")

    payload = dvc.as_payload(reports, skipped, "HEAD^", None)

    assert payload["rev"] == "HEAD^"
    assert payload["to_rev"] == "workspace"
    assert payload["bump"] == "major"
    assert payload["datasets"][0]["path"] == "data/customers.csv"
    assert json.loads(json.dumps(payload)), "the payload has to survive a round trip"


def test_the_json_payload_reports_nothing_changed_without_inventing_a_bump():
    payload = dvc.as_payload([], [("a.csv", "added")], "HEAD^", "HEAD")

    assert payload["bump"] is None
    assert payload["skipped"] == [{"path": "a.csv", "reason": "added"}]


def test_the_markdown_report_leads_with_the_bump_and_lists_the_dataset(workspace, fake):
    fake(MODIFIED, {("HEAD^", "data/customers.csv"): OLD_CSV})
    reports, skipped = dvc.analyse(repo=workspace, rev="HEAD^")

    body = dvc.render_markdown(reports, skipped, "HEAD^", None)

    assert "Suggested bump: **MAJOR**" in body
    assert "`data/customers.csv`" in body
    assert "the working tree" in body


def test_the_markdown_report_says_so_when_nothing_changed():
    body = dvc.render_markdown([], [], "HEAD^", "HEAD")

    assert "No versioned dataset changed." in body


def test_the_markdown_report_names_what_it_skipped():
    body = dvc.render_markdown([], [("data/a.csv", "added in this revision")], "HEAD^", None)

    assert "### Skipped" in body
    assert "data/a.csv" in body


def test_the_markdown_report_shows_where_a_rename_came_from(workspace, fake):
    payload = {"renamed": [{"path": {"old": "data/old.csv", "new": "data/customers.csv"}}]}
    fake(payload, {("HEAD^", "data/old.csv"): OLD_CSV})
    reports, skipped = dvc.analyse(repo=workspace, rev="HEAD^")

    body = dvc.render_markdown(reports, skipped, "HEAD^", None)

    assert "was `data/old.csv`" in body


def test_a_long_list_of_changes_is_trimmed_with_a_count():
    report = dvc.DatasetReport(
        path="a.csv",
        status="modified",
        current_version="1.0.0",
        next_version="2.0.0",
        bump="major",
        changes=[
            {"severity": "major", "rule": f"rule_{index}", "change": {"description": "d"}}
            for index in range(8)
        ],
    )

    body = "\n".join(dvc.render_details(report))

    assert "… and 3 more" in body
    assert body.count("- **MAJOR**") == 5, "only the top five are listed"


def test_the_most_severe_dataset_is_reported_first():
    def report(path, bump):
        return dvc.DatasetReport(path, "modified", "1.0.0", "2.0.0", bump)

    order = dvc.ranked([report("a.csv", "patch"), report("b.csv", "major")])

    assert [item.path for item in order] == ["b.csv", "a.csv"]


# --- the command ---------------------------------------------------------------------------


def test_the_command_prints_a_table(workspace, fake):
    fake(MODIFIED, {("HEAD^", "data/customers.csv"): OLD_CSV})

    result = runner.invoke(app, ["dvc", "--repo", str(workspace)])

    assert result.exit_code == 0
    assert "MAJOR" in result.stdout
    assert "customers.csv" in result.stdout


def test_the_command_writes_a_markdown_report(workspace, fake, tmp_path):
    fake(MODIFIED, {("HEAD^", "data/customers.csv"): OLD_CSV})
    target = tmp_path / "report.md"

    result = runner.invoke(app, ["dvc", "--repo", str(workspace), "--output", str(target)])

    assert result.exit_code == 0
    assert "Suggested bump: **MAJOR**" in target.read_text(encoding="utf-8")


def test_the_command_prints_json(workspace, fake):
    fake(MODIFIED, {("HEAD^", "data/customers.csv"): OLD_CSV})

    result = runner.invoke(app, ["dvc", "--repo", str(workspace), "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["bump"] == "major"


def test_the_command_reports_a_missing_dvc_rather_than_tracing(workspace, monkeypatch):
    def absent(*args, **kwargs):
        raise FileNotFoundError("dvc")

    monkeypatch.setattr(subprocess, "run", absent)

    result = runner.invoke(app, ["dvc", "--repo", str(workspace)])

    assert result.exit_code == 2
    assert "pip install dvc" in result.output


def test_the_command_says_when_nothing_changed(workspace, fake):
    fake({"added": [], "modified": []})

    result = runner.invoke(app, ["dvc", "--repo", str(workspace)])

    assert result.exit_code == 0
    assert "no versioned dataset changed" in result.stdout


def test_the_command_reports_what_it_skipped(workspace, fake):
    fake({"added": [{"path": "data/customers.csv"}]})

    result = runner.invoke(app, ["dvc", "--repo", str(workspace)])

    assert result.exit_code == 0
    assert "skipped" in result.stdout


# --- against DVC itself ---------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("dvc") is None, reason="dvc is not installed")
def test_a_real_dvc_repository_is_analysed_end_to_end(tmp_path):
    """The one test that proves DVC still answers the way the stand-in pretends it does.

    Everything above would keep passing if `dvc diff --json` changed shape tomorrow. This
    builds a repository, commits two versions of a dataset through DVC, and asks the command
    for the bump between them.
    """
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)

    def run(*args: str) -> None:
        subprocess.run(args, cwd=root, check=True, capture_output=True)

    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, capture_output=True)
    run("git", "config", "user.email", "t@e.invalid")
    run("git", "config", "user.name", "T")
    run("dvc", "init", "-q")

    (root / "data" / "customers.csv").write_text(OLD_CSV, encoding="utf-8")
    run("dvc", "add", "data/customers.csv", "-q")
    (root / "data" / "customers.csv.version").write_text("1.4.2\n", encoding="utf-8")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "first version")

    (root / "data" / "customers.csv").write_text(NEW_CSV, encoding="utf-8")
    run("dvc", "add", "data/customers.csv", "-q")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "second version")

    result = runner.invoke(app, ["dvc", "--repo", str(root), "--rev", "HEAD^", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["bump"] == "major"
    (dataset,) = payload["datasets"]
    assert dataset["path"] == "data/customers.csv"
    assert dataset["current_version"] == "1.4.2", "the sidecar in the base revision was read"
    assert dataset["next_version"] == "2.0.0"


def test_the_run_is_refused_when_a_dataset_reaches_the_gate(workspace, fake):
    """A run's severity is its worst dataset: one breaking change breaks the revision."""
    fake(MODIFIED, {("HEAD^", "data/customers.csv"): OLD_CSV})

    result = runner.invoke(app, ["dvc", "--repo", str(workspace), "--fail-on", "major"])

    assert result.exit_code == 1
    assert "refused" in result.output


def test_a_run_below_the_gate_is_let_through(workspace, fake):
    fake(MODIFIED, {("HEAD^", "data/customers.csv"): OLD_CSV})

    result = runner.invoke(app, ["dvc", "--repo", str(workspace)])

    assert result.exit_code == 0
