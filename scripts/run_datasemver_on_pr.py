#!/usr/bin/env python3
"""Analyse the datasets a branch touches and render a Markdown report.

Meant to run inside CI: it lists the dataset files that changed against a base ref,
compares each one against its version in that ref with `datasemver diff --json`, and
writes a summary that a workflow can post as a pull request comment.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, overload

MARKER = "<!-- datasemver-report -->"
DATASET_EXTENSIONS = (".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".parquet", ".pq")
VERSION_SUFFIX = ".version"
DEFAULT_VERSION = "0.0.0"
TOP_CHANGES = 5
MAX_COMMENT_CHARS = 60000
SEVERITY_RANK = {"patch": 0, "minor": 1, "major": 2}


class GitError(RuntimeError):
    """Raised when a git command fails."""


class SkippedDataset(Exception):
    """Raised when a dataset cannot be compared and should be reported as skipped."""


@dataclass
class DatasetReport:
    """Outcome of analysing a single dataset."""

    path: str
    current_version: str
    next_version: str
    bump: str | None
    changes: list[dict]
    sidecar: str | None = None

    @property
    def rank(self) -> int:
        return SEVERITY_RANK.get(self.bump or "", -1)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(git("rev-parse", "--show-toplevel", text=True).strip())

    if not ref_exists(args.base_ref):
        return finish(args, reports=[], note=f"base ref `{args.base_ref}` is not available")

    paths = args.paths or changed_datasets(args.base_ref, args.head_ref)
    if not paths:
        return finish(args, reports=[], note="no dataset files changed")

    reports: list[DatasetReport] = []
    skipped: list[tuple[str, str]] = []
    for path in paths:
        try:
            report = analyse(path, args, repo_root)
        except SkippedDataset as reason:
            skipped.append((path, str(reason)))
            continue
        reports.append(report)

    return finish(args, reports=reports, skipped=skipped)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        default=os.environ.get("DATASEMVER_BASE_REF", "origin/main"),
        help="Ref holding the previous version of each dataset (default: origin/main).",
    )
    parser.add_argument(
        "--head-ref",
        default="",
        help="Ref to compare against the base; defaults to the working tree.",
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help="Analyse these datasets instead of detecting the changed ones.",
    )
    parser.add_argument("--rules", default=None, help="Rules file passed to datasemver diff.")
    parser.add_argument(
        "--default-version",
        default=DEFAULT_VERSION,
        help=f"Version assumed when a dataset has no sidecar file (default: {DEFAULT_VERSION}).",
    )
    parser.add_argument(
        "--top-changes",
        type=int,
        default=TOP_CHANGES,
        help=f"Changes listed per dataset (default: {TOP_CHANGES}).",
    )
    parser.add_argument("--output", type=Path, default=None, help="Write the report to this file.")
    return parser.parse_args(argv)


@overload
def git(*args: str, text: Literal[True]) -> str: ...


@overload
def git(*args: str, text: Literal[False] = False) -> bytes: ...


def git(*args: str, text: bool = False) -> str | bytes:
    """Run a git command and return its output, raising GitError on failure.

    The overloads above tie the return type to `text`, so a caller that asks for text is
    not handed bytes by the type checker and left to find out at runtime.
    """
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=text,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise GitError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return result.stdout


def ref_exists(ref: str) -> bool:
    try:
        git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", text=True)
    except GitError:
        return False
    return True


def changed_datasets(base_ref: str, head_ref: str) -> list[str]:
    """List the dataset files that changed between the base ref and the head."""
    target = f"{base_ref}...{head_ref}" if head_ref else base_ref
    output = git("diff", "--name-only", "-z", "--diff-filter=ACMRT", target, text=True)

    paths = [path for path in output.split("\0") if path]
    return sorted(path for path in paths if path.lower().endswith(DATASET_EXTENSIONS))


def analyse(path: str, args: argparse.Namespace, repo_root: Path) -> DatasetReport:
    """Compare one dataset against its base version and return the parsed report."""
    new_file = repo_root / path
    if not new_file.exists():
        raise SkippedDataset("removed in this branch")

    previous = show_blob(args.base_ref, path)
    if previous is None:
        raise SkippedDataset("new dataset, nothing to compare against")

    recorded = recorded_version(args.base_ref, path)
    current_version = recorded or args.default_version

    with tempfile.TemporaryDirectory() as directory:
        old_file = Path(directory) / f"base{Path(path).suffix}"
        old_file.write_bytes(previous)
        payload = run_datasemver(old_file, new_file, current_version, args.rules)

    return DatasetReport(
        path=path,
        current_version=payload["current_version"],
        next_version=payload["next_version"],
        bump=payload["bump"],
        changes=[item for item in payload["classified"] if item["severity"]],
        sidecar=sidecar_note(repo_root, path, recorded, payload["next_version"]),
    )


def show_blob(ref: str, path: str) -> bytes | None:
    """Return the bytes of a file at a given ref, or None when it does not exist there."""
    try:
        return git("show", f"{ref}:{path}")
    except GitError:
        return None


def read_version(ref: str, path: str, default: str) -> str:
    """Read the version from the dataset's sidecar file in the base ref."""
    return recorded_version(ref, path) or default


def recorded_version(ref: str, path: str) -> str | None:
    """The version a ref records beside a dataset, or None when it records none.

    Distinct from `read_version`, which substitutes a default: the difference between "no
    version was written down" and "the version written down is 0.0.0" is what makes the
    check below able to say something useful.
    """
    blob = show_blob(ref, f"{path}{VERSION_SUFFIX}")
    if blob is None:
        return None
    return blob.decode("utf-8", "replace").strip() or None


def written_version(repo_root: Path, path: str) -> str | None:
    """The version recorded beside the dataset as this branch leaves it."""
    sidecar = repo_root / f"{path}{VERSION_SUFFIX}"
    if not sidecar.is_file():
        return None
    return sidecar.read_text(encoding="utf-8", errors="replace").strip() or None


def sidecar_note(
    repo_root: Path,
    path: str,
    recorded: str | None,
    suggested: str,
) -> str | None:
    """Say something when the version file and the dataset disagree, and nothing otherwise.

    A version that is never written down does not announce itself: the next branch reads the
    stale number, bumps from there, and the drift compounds quietly. Whether to write the
    number stays with the author, which is the point of the sidecar; noticing that it was not
    written is what the tool can do about it.
    """
    written = written_version(repo_root, path)
    name = f"`{path}{VERSION_SUFFIX}`"

    if recorded is None and written is None:
        return f"{name} does not exist, so the comparison started from the default"
    if written is None:
        return f"{name} was removed in this branch, and recorded {recorded}"
    if written == recorded:
        return f"{name} still reads {written}; {suggested} is not recorded yet"
    if written != suggested:
        return f"{name} reads {written}, but this branch suggests {suggested}"
    return None


def run_datasemver(old: Path, new: Path, current_version: str, rules: str | None) -> dict:
    """Run `datasemver diff --json` and return the parsed report."""
    command = [
        sys.executable,
        "-m",
        "datasemver",
        "diff",
        str(old),
        str(new),
        "--json",
        "--current-version",
        current_version,
    ]
    if rules:
        command += ["--rules", rules]

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SkippedDataset(f"datasemver failed: {result.stderr.strip() or 'unknown error'}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SkippedDataset(f"datasemver returned invalid JSON: {error}") from error


def render(
    reports: list[DatasetReport],
    skipped: list[tuple[str, str]],
    note: str | None,
    top_changes: int,
) -> str:
    """Render the Markdown posted as a pull request comment."""
    lines = [MARKER, "## DataSemver report", ""]

    if not reports:
        lines.append(f"No dataset was analysed: {note or 'nothing to do'}.")
        lines.append("")
        lines.extend(render_skipped(skipped))
        return "\n".join(lines).rstrip() + "\n"

    overall = max(reports, key=lambda report: report.rank).bump
    lines.append(f"Suggested bump for this branch: **{(overall or 'none').upper()}**")
    lines.append("")
    lines.append("| Dataset | Current | Suggested | Bump | Changes |")
    lines.append("| --- | --- | --- | --- | --- |")
    for report in sorted(reports, key=lambda item: (-item.rank, item.path)):
        bump = report.bump or "none"
        lines.append(
            f"| `{report.path}` | {report.current_version} | **{report.next_version}** | "
            f"{bump.upper()} | {len(report.changes)} |"
        )
    lines.append("")

    for report in sorted(reports, key=lambda item: (-item.rank, item.path)):
        lines.extend(render_details(report, top_changes))

    lines.extend(render_sidecars(reports))
    lines.extend(render_skipped(skipped))
    lines.append("### Reproduce locally")
    lines.append("")
    lines.append("```bash")
    lines.append("pip install datasemver")
    example = reports[0]
    suffix = Path(example.path).suffix
    lines.append(f"git show origin/main:{example.path} > /tmp/base{suffix}")
    lines.append(
        f"datasemver diff /tmp/base{suffix} '{example.path}' "
        f"--current-version {example.current_version} --output CHANGELOG.md"
    )
    lines.append("```")
    lines.append("")
    lines.append(
        "The full changelog entry, every unclassified change and the column-by-column "
        "comparison are printed by that command; this comment only lists the highlights."
    )
    return "\n".join(lines).rstrip() + "\n"


def render_details(report: DatasetReport, top_changes: int) -> list[str]:
    if not report.changes:
        return []

    ranked = sorted(
        report.changes,
        key=lambda item: -SEVERITY_RANK.get(item["severity"], -1),
    )
    lines = [
        f"<details><summary><code>{report.path}</code> — {len(report.changes)} classified "
        f"change(s)</summary>",
        "",
    ]
    for item in ranked[:top_changes]:
        severity = item["severity"].upper()
        lines.append(f"- **{severity}** (`{item['rule']}`): {item['change']['description']}")
    remaining = len(ranked) - top_changes
    if remaining > 0:
        lines.append(f"- … and {remaining} more")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    return lines


def render_sidecars(reports: list[DatasetReport]) -> list[str]:
    """List the datasets whose version file disagrees with the branch, and nothing else.

    Silent when every version file is in step, which is most of the time; the section only
    appears when there is something a reviewer would want to have been told.
    """
    notes = [report for report in reports if report.sidecar]
    if not notes:
        return []
    lines = ["### Version files", ""]
    lines += [f"- `{report.path}`: {report.sidecar}" for report in notes]
    lines.append("")
    return lines


def render_skipped(skipped: list[tuple[str, str]]) -> list[str]:
    if not skipped:
        return []
    lines = ["### Skipped", ""]
    lines += [f"- `{path}`: {reason}" for path, reason in skipped]
    lines.append("")
    return lines


def finish(
    args: argparse.Namespace,
    reports: list[DatasetReport],
    skipped: list[tuple[str, str]] | None = None,
    note: str | None = None,
) -> int:
    """Write the report, expose the workflow outputs and return the exit code."""
    skipped = skipped or []
    body = truncate(render(reports, skipped, note, args.top_changes))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    print(body)

    overall = max(reports, key=lambda report: report.rank).bump if reports else None
    write_github_output(
        has_report="true" if reports else "false",
        max_bump=overall or "none",
        dataset_count=str(len(reports)),
    )
    append_step_summary(body)
    return 0


def truncate(body: str) -> str:
    """Keep the report within the size a pull request comment accepts."""
    if len(body) <= MAX_COMMENT_CHARS:
        return body
    trimmed = body[:MAX_COMMENT_CHARS].rsplit("\n", 1)[0]
    return f"{trimmed}\n\n_Report truncated to fit a pull request comment._\n"


def write_github_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def append_step_summary(body: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(body)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GitError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
