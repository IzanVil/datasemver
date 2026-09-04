"""Tests for the CI helper that analyses the datasets a branch touches.

The helper is driven by git, so most of these run against a real repository built in
`tmp_path` rather than against a mocked `git`: the parts worth covering are exactly the
ones a mock would paper over, such as which refs hold which blob and what `git diff`
reports for a file that no longer exists.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from scripts import run_datasemver_on_pr as pr

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


# --- detection -------------------------------------------------------------------------


def test_only_dataset_extensions_are_collected(repo):
    (repo / "data" / "notes.txt").write_text("x", encoding="utf-8")
    (repo / "data" / "events.parquet").write_bytes(b"not really parquet")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "mixed files")

    paths = pr.changed_datasets("base", "")

    assert "data/customers.csv" in paths
    assert "data/events.parquet" in paths
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
