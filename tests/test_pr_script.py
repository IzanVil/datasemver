"""Tests for the CI helper that analyses the datasets a branch touches.

The helper is driven by git, so most of these run against a real repository built in
`tmp_path` rather than against a mocked `git`: the parts worth covering are exactly the
ones a mock would paper over, such as which refs hold which blob and what `git diff`
reports for a file that no longer exists.
"""

from __future__ import annotations

import json
import pathlib
import re
import shlex
import subprocess

import pytest

pr = pytest.importorskip(
    "scripts.run_datasemver_on_pr",
    reason="the scripts directory is not shipped in the sdist",
)

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


def run_git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repository whose `base` branch holds the previous version of one dataset."""
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    run_git(root.parent, "init", "-q", "-b", "main", str(root))
    run_git(root, "config", "user.email", "test@example.invalid")
    run_git(root, "config", "user.name", "Test")

    (root / "data" / "customers.csv").write_text(OLD_CSV, encoding="utf-8")
    (root / "data" / "customers.csv.version").write_text("1.4.2\n", encoding="utf-8")
    (root / "README.md").write_text("not a dataset\n", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-qm", "base")
    run_git(root, "branch", "base")

    (root / "data" / "customers.csv").write_text(NEW_CSV, encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-qm", "change")

    monkeypatch.chdir(root)
    return root


def report_of(repo, tmp_path, *extra):
    """Run the script against the repository and return what it wrote."""
    output = tmp_path / "out" / "report.md"
    code = pr.main(["--base-ref", "base", "--output", str(output), *extra])
    return code, output.read_text(encoding="utf-8")


def tolerant_rules(tmp_path):
    """A rule set that calls everything in the fixture's change a patch."""
    rules = tmp_path / "tolerant.yaml"
    rules.write_text(
        "patch:\n"
        "  - column_removed\n"
        "  - type_changed_incompatible\n"
        "  - column_added\n"
        "  - row_count_increased\n"
        "  - nulls_fixed\n"
        "  - minor_stat_change\n",
        encoding="utf-8",
    )
    return rules


# --- end to end ------------------------------------------------------------------------


def test_a_changed_dataset_is_reported_with_its_bump(repo, tmp_path):
    code, body = report_of(repo, tmp_path)

    assert code == 0
    assert pr.MARKER in body
    # legacy_code was dropped and phone stopped being an int64
    assert "Suggested bump for this branch: **MAJOR**" in body
    assert "`data/customers.csv`" in body
    assert "1.4.2" in body and "2.0.0" in body


def test_the_sidecar_supplies_the_current_version(repo, tmp_path):
    _, body = report_of(repo, tmp_path)

    assert "| 1.4.2 |" in body


def test_without_a_sidecar_the_default_version_is_used(repo, tmp_path):
    """The sidecar is read from the base ref, so the dataset needs one that never had it."""
    run_git(repo, "checkout", "-q", "base")
    (repo / "data" / "events.csv").write_text(OLD_CSV, encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "events, no sidecar")
    run_git(repo, "branch", "-f", "events-base")
    (repo / "data" / "events.csv").write_text(NEW_CSV, encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "events changed")

    output = tmp_path / "report.md"
    pr.main(["--base-ref", "events-base", "--output", str(output), "--default-version", "3.1.0"])

    assert "| 3.1.0 |" in output.read_text(encoding="utf-8")


def test_a_dataset_absent_from_the_base_is_skipped(repo, tmp_path):
    (repo / "data" / "events.csv").write_text(NEW_CSV, encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "add a dataset")

    _, body = report_of(repo, tmp_path)

    assert "### Skipped" in body
    assert "new dataset, nothing to compare against" in body


def test_a_dataset_removed_in_the_branch_is_skipped(repo, tmp_path):
    """Reachable through --paths: detection filters deletions out before this point."""
    run_git(repo, "rm", "-q", "data/customers.csv")
    run_git(repo, "commit", "-qm", "remove the dataset")

    _, body = report_of(repo, tmp_path, "--paths", "data/customers.csv")

    assert "removed in this branch" in body


def test_a_deletion_is_not_picked_up_by_detection(repo, tmp_path):
    """`--diff-filter=ACMRT` excludes deletions, so dropping a dataset reports nothing."""
    run_git(repo, "rm", "-q", "data/customers.csv")
    run_git(repo, "commit", "-qm", "remove the dataset")

    assert pr.changed_datasets("base", "") == []


def test_a_branch_touching_no_dataset_says_so(repo, tmp_path):
    run_git(repo, "checkout", "-q", "base")

    _, body = report_of(repo, tmp_path)

    assert "no dataset files changed" in body


def test_an_unavailable_base_ref_is_reported_not_raised(repo, tmp_path):
    output = tmp_path / "report.md"

    code = pr.main(["--base-ref", "origin/nope", "--output", str(output)])

    assert code == 0
    assert "is not available" in output.read_text(encoding="utf-8")


def test_explicit_paths_bypass_the_diff(repo, tmp_path):
    run_git(repo, "checkout", "-q", "base")  # nothing changed, so detection finds nothing

    _, body = report_of(repo, tmp_path, "--paths", "data/customers.csv")

    assert "no dataset files changed" not in body
    assert "`data/customers.csv`" in body


def test_the_workflow_outputs_are_written(repo, tmp_path, monkeypatch):
    outputs = tmp_path / "gh-output"
    summary = tmp_path / "gh-summary"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    report_of(repo, tmp_path)

    written = outputs.read_text(encoding="utf-8")
    assert "has_report=true" in written
    assert "max_bump=major" in written
    assert "dataset_count=1" in written
    assert pr.MARKER in summary.read_text(encoding="utf-8")


def test_outputs_report_an_empty_run(repo, tmp_path, monkeypatch):
    run_git(repo, "checkout", "-q", "base")
    outputs = tmp_path / "gh-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))

    report_of(repo, tmp_path)

    written = outputs.read_text(encoding="utf-8")
    assert "has_report=false" in written
    assert "max_bump=none" in written


def test_nothing_is_written_without_the_github_environment(repo, tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    code, _ = report_of(repo, tmp_path)

    assert code == 0


# --- the version file ---------------------------------------------------------------------


def write_sidecar(repo, value):
    (repo / "data" / "customers.csv.version").write_text(value, encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", f"record {value}")


def test_a_version_file_left_behind_is_reported(repo, tmp_path):
    """The failure this guards against is silence, not a wrong number.

    Nothing forces the author to record the bump. When they do not, the next branch reads
    the stale version, bumps from there, and the drift compounds without anyone seeing it.
    """
    _, body = report_of(repo, tmp_path)

    assert "### Version files" in body
    assert "still reads 1.4.2" in body
    assert "2.0.0 is not recorded yet" in body


def test_a_recorded_bump_says_nothing(repo, tmp_path):
    write_sidecar(repo, "2.0.0\n")

    _, body = report_of(repo, tmp_path)

    assert "### Version files" not in body


def test_a_version_that_disagrees_with_the_branch_is_reported(repo, tmp_path):
    """Recording 1.5.0 for a branch that removed a column is worth saying out loud."""
    write_sidecar(repo, "1.5.0\n")

    _, body = report_of(repo, tmp_path)

    assert "reads 1.5.0, but this branch suggests 2.0.0" in body


def test_a_dataset_with_no_version_file_says_so(repo, tmp_path):
    run_git(repo, "rm", "-q", "data/customers.csv.version")
    run_git(repo, "commit", "-qm", "drop the sidecar")
    run_git(repo, "branch", "-f", "no-sidecar")
    run_git(repo, "checkout", "-q", "no-sidecar")
    (repo / "data" / "customers.csv").write_text(OLD_CSV, encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "change it again")

    output = tmp_path / "report.md"
    pr.main(["--base-ref", "base", "--output", str(output), "--paths", "data/customers.csv"])
    body = output.read_text(encoding="utf-8")

    assert "was removed in this branch" in body


def test_a_removed_version_file_is_reported(repo, tmp_path):
    run_git(repo, "rm", "-q", "data/customers.csv.version")
    run_git(repo, "commit", "-qm", "drop the sidecar")

    _, body = report_of(repo, tmp_path)

    assert "was removed in this branch, and recorded 1.4.2" in body


def test_a_blank_version_file_counts_as_absent(repo, tmp_path):
    write_sidecar(repo, "   \n")

    _, body = report_of(repo, tmp_path)

    assert "was removed in this branch" in body


def test_recorded_version_separates_absent_from_zero(repo):
    """`read_version` substitutes a default, which hides the difference this check needs."""
    assert pr.recorded_version("base", "data/customers.csv") == "1.4.2"
    assert pr.recorded_version("base", "data/nope.csv") is None
    assert pr.read_version("base", "data/nope.csv", "0.0.0") == "0.0.0"


# --- detection -------------------------------------------------------------------------


def test_only_dataset_extensions_are_collected(repo):
    (repo / "data" / "notes.txt").write_text("x", encoding="utf-8")
    (repo / "data" / "events.parquet").write_bytes(b"not really parquet")
    (repo / "data" / "compressed.csv.gz").write_bytes(b"gzip fixture")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "mixed files")

    paths = pr.changed_datasets("base", "")

    assert "data/customers.csv" in paths
    assert "data/events.parquet" in paths
    assert "data/compressed.csv.gz" in paths
    assert not any(path.endswith((".txt", ".md")) for path in paths)


def test_a_head_ref_compares_two_refs(repo):
    assert pr.changed_datasets("base", "main") == ["data/customers.csv"]


def test_a_failing_git_command_raises(repo):
    with pytest.raises(pr.GitError, match="git rev-parse"):
        pr.git("rev-parse", "--verify", "refs/heads/missing", text=True)


def test_a_missing_ref_is_not_an_existing_ref(repo):
    assert pr.ref_exists("base")
    assert not pr.ref_exists("origin/nope")


def test_a_blob_missing_from_a_ref_reads_as_none(repo):
    assert pr.show_blob("base", "data/customers.csv") is not None
    assert pr.show_blob("base", "data/nope.csv") is None


def test_a_blank_sidecar_falls_back_to_the_default(repo):
    (repo / "data" / "customers.csv.version").write_text("   \n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "blank sidecar")
    run_git(repo, "branch", "-f", "blank")

    assert pr.read_version("blank", "data/customers.csv", "0.0.0") == "0.0.0"


# --- the datasemver call ---------------------------------------------------------------


def test_a_failing_datasemver_run_skips_the_dataset(tmp_path):
    unreadable = tmp_path / "broken.csv"
    unreadable.write_text("id,name\n1\n", encoding="utf-8")

    with pytest.raises(pr.SkippedDataset, match="datasemver failed"):
        pr.run_datasemver(tmp_path / "missing.csv", unreadable, "0.0.0", None)


def test_output_that_is_not_json_skips_the_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pr.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="not json", stderr=""),
    )

    with pytest.raises(pr.SkippedDataset, match="invalid JSON"):
        pr.run_datasemver(tmp_path / "a.csv", tmp_path / "b.csv", "0.0.0", None)


def test_a_rules_file_is_passed_through(tmp_path, monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({}), stderr="")

    monkeypatch.setattr(pr.subprocess, "run", fake_run)
    pr.run_datasemver(tmp_path / "a.csv", tmp_path / "b.csv", "1.0.0", "rules.yaml")

    assert "--rules" in seen["command"]
    assert "rules.yaml" in seen["command"]


# --- rendering -------------------------------------------------------------------------


def make_report(path="a.csv", bump="minor", changes=0):
    return pr.DatasetReport(
        path=path,
        current_version="1.0.0",
        next_version="1.1.0",
        bump=bump,
        changes=[
            {"severity": "minor", "rule": f"rule_{i}", "change": {"description": f"change {i}"}}
            for i in range(changes)
        ],
    )


def test_the_strongest_bump_across_datasets_wins():
    body = pr.render(
        [make_report("a.csv", "patch"), make_report("b.csv", "major")],
        skipped=[],
        note=None,
        top_changes=5,
    )

    assert "Suggested bump for this branch: **MAJOR**" in body


def test_an_unranked_bump_sorts_below_the_known_ones():
    assert make_report(bump=None).rank == -1
    assert make_report(bump="patch").rank < make_report(bump="major").rank


def test_details_are_capped_and_the_remainder_counted():
    body = pr.render([make_report(changes=9)], skipped=[], note=None, top_changes=3)

    assert body.count("- **MINOR**") == 3
    assert "… and 6 more" in body


def test_a_dataset_without_classified_changes_has_no_details_block():
    body = pr.render([make_report(changes=0)], skipped=[], note=None, top_changes=5)

    assert "<details>" not in body


def test_the_report_explains_how_to_reproduce_it():
    body = pr.render([make_report("data/x.csv", changes=1)], skipped=[], note=None, top_changes=5)

    assert "pip install datasemver" in body
    assert "git show origin/main:data/x.csv" in body


def test_the_reproduce_snippet_reads_the_base_the_comparison_used():
    report = make_report("data/x.csv", changes=1)
    body = pr.render([report], skipped=[], note=None, top_changes=5, base_ref="origin/release")

    assert "git show origin/release:data/x.csv" in body
    assert "origin/main" not in body


def test_a_run_reproduces_against_the_base_it_was_given(repo, tmp_path):
    _, body = report_of(repo, tmp_path)

    assert "git show base:data/customers.csv" in body


def test_the_notes_of_a_run_reach_the_comment(repo, tmp_path, monkeypatch):
    """The real payload carries `diff.notes`, and what is in it is what the comment lists."""
    real = pr.run_datasemver

    def noted(*args):
        payload = real(*args)
        payload["diff"]["notes"].append("nothing was paired")
        return payload

    monkeypatch.setattr(pr, "run_datasemver", noted)
    _, body = report_of(repo, tmp_path)

    assert "- `data/customers.csv`: nothing was paired" in body


def test_what_a_comparison_left_undone_is_noted():
    report = make_report("data/x.csv")
    report.notes = ["40 columns were removed and 40 added, too many to pair up as renames"]
    body = pr.render([report], skipped=[], note=None, top_changes=5)

    assert "### Notes" in body
    assert "- `data/x.csv`: 40 columns were removed and 40 added, too many" in body


def test_a_note_with_markup_in_it_is_only_text():
    report = make_report("data/x.csv")
    report.notes = ["see [this](https://example.com) @someone"]
    body = pr.render([report], skipped=[], note=None, top_changes=5)

    assert "- `data/x.csv`: `see [this](https://example.com) @someone`" in body


def test_without_notes_there_is_no_notes_section():
    body = pr.render([make_report("data/x.csv")], skipped=[], note=None, top_changes=5)

    assert "### Notes" not in body


def test_skipped_datasets_are_listed_even_with_no_reports():
    body = pr.render([], skipped=[("a.csv", "why")], note="nothing", top_changes=5)

    assert "### Skipped" in body
    assert "- `a.csv`: why" in body


def test_an_oversized_report_is_truncated_to_fit_a_comment():
    body = pr.truncate("line\n" * (pr.MAX_COMMENT_CHARS // 2))

    assert len(body) <= pr.MAX_COMMENT_CHARS + 100
    assert body.endswith("_Report truncated to fit a pull request comment._\n")


def test_a_report_within_the_limit_is_left_alone():
    assert pr.truncate("short\n") == "short\n"


# --- arguments -------------------------------------------------------------------------


def test_the_base_ref_defaults_to_the_environment(monkeypatch):
    monkeypatch.setenv("DATASEMVER_BASE_REF", "origin/release")

    assert pr.parse_args([]).base_ref == "origin/release"


def test_the_defaults_are_the_documented_ones(monkeypatch):
    monkeypatch.delenv("DATASEMVER_BASE_REF", raising=False)
    args = pr.parse_args([])

    assert args.base_ref == "origin/main"
    assert args.top_changes == pr.TOP_CHANGES
    assert args.default_version == pr.DEFAULT_VERSION
    assert args.output is None


# --- refusing a change -----------------------------------------------------------------------


def test_without_a_threshold_the_run_only_describes(repo, tmp_path):
    """The default has to stay advisory: every repository already running this expects 0."""
    code, _ = report_of(repo, tmp_path)

    assert code == 0


def test_a_bump_that_reaches_the_threshold_fails_the_run(repo, tmp_path):
    code, body = report_of(repo, tmp_path, "--fail-on", "major")

    assert code == 1
    assert "customers.csv" in body


def test_the_report_is_written_before_the_run_is_refused(repo, tmp_path):
    """A refusal that suppressed its own explanation would say no and never say why."""
    output = tmp_path / "out" / "report.md"

    code = pr.main(["--base-ref", "base", "--output", str(output), "--fail-on", "major"])

    assert code == 1
    assert output.exists()
    assert output.read_text(encoding="utf-8").strip()


def test_a_bump_below_the_threshold_is_let_through(repo, tmp_path):
    """The same change, under a rule set that does not call any of it breaking."""
    rules = tolerant_rules(tmp_path)

    code, _ = report_of(repo, tmp_path, "--fail-on", "major", "--rules", str(rules))

    assert code == 0


def test_a_run_with_nothing_to_compare_is_not_refused(repo, tmp_path):
    output = tmp_path / "out" / "report.md"

    code = pr.main(
        ["--base-ref", "base", "--output", str(output), "--fail-on", "patch", "--paths", "none.csv"]
    )

    assert code == 0


# --- recording the version -------------------------------------------------------------------


def sidecar(repo, name="customers.csv"):
    return repo / "data" / f"{name}.version"


def test_the_version_is_recorded_beside_the_dataset(repo, tmp_path):
    """The branch left 1.4.2 where the run suggests 2.0.0, and this is what closes that gap."""
    code, _ = report_of(repo, tmp_path, "--write-version")

    assert code == 0
    assert sidecar(repo).read_text(encoding="utf-8").strip() == "2.0.0"


def test_the_version_is_not_recorded_unless_it_is_asked_for(repo, tmp_path):
    report_of(repo, tmp_path)

    assert sidecar(repo).read_text(encoding="utf-8").strip() == "1.4.2"


def test_recording_stages_and_commits_nothing(repo, tmp_path):
    """Where the file goes next, and with whose token, is the workflow's call."""
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout

    report_of(repo, tmp_path, "--write-version")

    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True
    ).stdout
    assert status.strip() == "M data/customers.csv.version", "modified, and not staged"
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout
        == head
    )


def test_a_dataset_that_never_had_a_version_file_is_given_one(repo, tmp_path):
    run_git(repo, "checkout", "-q", "base")
    (repo / "data" / "events.csv").write_text(OLD_CSV, encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "events, no sidecar")
    run_git(repo, "branch", "-f", "events-base")
    (repo / "data" / "events.csv").write_text(NEW_CSV, encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "events changed")

    pr.main(
        [
            "--base-ref",
            "events-base",
            "--output",
            str(tmp_path / "report.md"),
            "--default-version",
            "3.1.0",
            "--write-version",
        ]
    )

    assert sidecar(repo, "events.csv").read_text(encoding="utf-8").strip() == "4.0.0"


def test_a_refused_run_records_nothing(repo, tmp_path):
    """The sidecar is what the next run bumps from, so a rejected number must not land in it."""
    code, _ = report_of(repo, tmp_path, "--write-version", "--fail-on", "major")

    assert code == 1
    assert sidecar(repo).read_text(encoding="utf-8").strip() == "1.4.2"


def test_a_run_below_the_gate_still_records(repo, tmp_path):
    """The gate has to refuse the run, not merely be present on the command line."""
    rules = tolerant_rules(tmp_path)

    code, _ = report_of(
        repo, tmp_path, "--write-version", "--fail-on", "major", "--rules", str(rules)
    )

    assert code == 0
    assert sidecar(repo).read_text(encoding="utf-8").strip() == "1.4.3"


def test_a_dataset_that_was_skipped_gets_no_version_file(repo, tmp_path):
    (repo / "data" / "events.csv").write_text(NEW_CSV, encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "events is new")

    report_of(repo, tmp_path, "--write-version")

    assert not sidecar(repo, "events.csv").exists()


def test_the_report_says_the_version_was_set_in_the_checkout(repo, tmp_path):
    """Not "written": nothing is recorded in the branch until something commits it."""
    _, body = report_of(repo, tmp_path, "--write-version")

    assert "### Version files" in body
    assert "`data/customers.csv.version` was set to 2.0.0" in body
    assert "recorded once a step commits it" in body


def test_a_version_file_already_in_step_is_left_alone_and_not_mentioned(repo, tmp_path):
    write_sidecar(repo, "2.0.0\n")

    _, body = report_of(repo, tmp_path, "--write-version")

    assert "### Version files" not in body
    assert sidecar(repo).read_text(encoding="utf-8").strip() == "2.0.0"


def test_the_files_that_changed_are_an_output(repo, tmp_path, monkeypatch):
    outputs = tmp_path / "gh-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))

    report_of(repo, tmp_path, "--write-version")

    assert "version_files=data/customers.csv.version\n" in outputs.read_text(encoding="utf-8")


def test_the_output_is_empty_when_nothing_changed(repo, tmp_path, monkeypatch):
    """Empty is the answer a step deciding whether to commit reads as 'nothing to commit'."""
    write_sidecar(repo, "2.0.0\n")
    outputs = tmp_path / "gh-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))

    report_of(repo, tmp_path, "--write-version")

    assert "version_files=\n" in outputs.read_text(encoding="utf-8")


def test_the_output_is_empty_when_the_flag_is_off(repo, tmp_path, monkeypatch):
    outputs = tmp_path / "gh-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))

    report_of(repo, tmp_path)

    assert "version_files=\n" in outputs.read_text(encoding="utf-8")


def test_a_value_with_several_lines_uses_the_delimiter_form(tmp_path, monkeypatch):
    """`key=a\\nb` would end at the newline and read `b` as a key of its own."""
    outputs = tmp_path / "gh-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))

    pr.write_github_output(version_files="a.csv.version\nb.csv.version", max_bump="minor")

    first, *rest, last = outputs.read_text(encoding="utf-8").splitlines()
    key, _, delimiter = first.partition("<<")
    assert key == "version_files"
    assert rest[:2] == ["a.csv.version", "b.csv.version"]
    assert rest[2] == delimiter, "closed by the same delimiter that opened it"
    assert last == "max_bump=minor"


# --- what a branch gets to put in the comment ------------------------------------------
#
# The report is posted under the repository's own bot, and its paths, column headings and
# version files are chosen by whoever opened the pull request.


HOSTILE = (
    "`](http://evil.example)<img src=x onerror=alert(1)> @everyone [claim](http://evil.example)"
)


def outside_code(markdown: str) -> str:
    """What is left of a comment once every place Markdown does not look inside is removed."""
    text = re.sub(r"(`{3,}).*?\1", "", markdown, flags=re.DOTALL)
    text = re.sub(r"<code>.*?</code>", "", text, flags=re.DOTALL)
    return re.sub(r"(`+).+?\1", "", text, flags=re.DOTALL)


def test_a_backtick_cannot_end_the_span_it_sits_in():
    assert pr.code("a`b") == "``a`b``"
    assert pr.code("`x") == "`` `x ``"
    assert pr.code("a``b`c") == "```a``b`c```"


def test_a_newline_cannot_start_a_new_line_of_the_comment():
    assert "\n" not in pr.code("a\n- injected\nb")
    assert "\r" not in pr.code("a\rb")


def test_a_pipe_does_not_end_a_table_cell():
    assert pr.code("a|b", table=True) == "`a\\|b`"
    assert pr.code("a|b") == "`a|b`"


def test_what_a_branch_chose_is_never_read_as_markup():
    report = make_report(f"data/{HOSTILE}.csv", "major", changes=0)
    report.changes = [
        {"severity": "major", "rule": "column_removed", "change": {"description": HOSTILE}}
    ]
    report.sidecar = pr.sidecar_note(
        pathlib.Path("/nonexistent"), f"data/{HOSTILE}.csv", HOSTILE, "2.0.0"
    )

    body = pr.render([report], skipped=[(f"b/{HOSTILE}.csv", HOSTILE)], note=None, top_changes=5)
    markdown = outside_code(body)

    for dangerous in ("<img", "http://evil.example", "@everyone", "](", "onerror"):
        assert dangerous not in markdown, dangerous


def test_the_reproduce_snippet_hands_a_hostile_path_to_the_shell_as_one_word():
    path = "data/x.csv; touch pwned #.csv"
    body = pr.render([make_report(path)], skipped=[], note=None, top_changes=5)

    commands = [line for line in body.splitlines() if line.startswith(("git show", "datasemver"))]
    show, diff = (shlex.split(command) for command in commands)

    assert show == ["git", "show", f"origin/main:{path}", ">", "/tmp/base.csv"]
    assert diff[:3] == ["datasemver", "diff", "/tmp/base.csv"]
    assert diff[3] == path
    assert "touch" not in diff and "touch" not in show


def test_the_reproduce_block_cannot_be_closed_early_by_a_path():
    path = "data/a\n```\n[claim](http://evil.example)\n```\n.csv"
    body = pr.render([make_report(path)], skipped=[], note=None, top_changes=5)
    lines = body.splitlines()

    opening = next(line for line in lines if line.endswith("bash") and set(line[:-4]) == {"`"})
    fence = opening[:-4]

    assert len(fence) > 3
    # the block opens once and closes once, with the whole path inside it
    assert lines.count(fence) == 1
    assert sum(1 for line in lines if line == fence) == 1
    assert "http://evil.example" not in outside_code(body)


def test_a_ref_cannot_be_an_option_to_git(monkeypatch):
    with pytest.raises(SystemExit):
        pr.parse_args(["--base-ref=--output=/tmp/written-by-git"])
    with pytest.raises(SystemExit):
        pr.parse_args(["--head-ref=--output=/tmp/written-by-git"])

    monkeypatch.setenv("DATASEMVER_BASE_REF", "--output=/tmp/written-by-git")
    with pytest.raises(SystemExit):
        pr.parse_args([])


def _link(target, link):
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):  # pragma: no cover - a platform without symlinks
        pytest.skip("this platform cannot create symbolic links")


def test_a_dataset_that_is_a_link_out_of_the_checkout_is_not_read(repo, tmp_path):
    secret = tmp_path / "secret.csv"
    secret.write_text("token\nsk-live-0123456789\n", encoding="utf-8")
    _link(secret, repo / "data" / "stolen.csv")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "a link")

    _, body = report_of(repo, tmp_path, "--paths", "data/stolen.csv")

    assert "sk-live-0123456789" not in body
    assert "a link to somewhere else" in body


def test_a_version_file_that_is_a_link_out_of_the_checkout_is_not_written_through(repo, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me\n", encoding="utf-8")
    sidecar = repo / "data" / "customers.csv.version"
    sidecar.unlink()
    _link(victim, sidecar)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "a link where the version file was")

    report_of(repo, tmp_path, "--write-version")

    assert victim.read_text(encoding="utf-8") == "keep me\n"
