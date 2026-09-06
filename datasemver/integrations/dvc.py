"""Running DataSemver over the datasets DVC versions.

DVC deliberately keeps data out of git: a commit records a `.dvc` pointer holding a hash,
and the bytes live in a local cache or a remote. So the move the pull request script makes,
`git show <ref>:<path>`, returns nothing for a DVC-tracked dataset, and the previous version
has to be asked of DVC itself. That is the reason this is a module rather than a flag on the
other one.

DVC is never imported. It is run as a command, so it can live in a different environment --
a pipx or brew install is the usual case -- and DataSemver keeps working without it.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from datasemver.core.analyzer import DEFAULT_VERSION, analyze
from datasemver.formats.loader import SUPPORTED_EXTENSIONS
from datasemver.rules.engine import RuleError

INSTALL_HINT = "install it with: pip install dvc"
VERSION_SUFFIX = ".version"
SEVERITY_RANK = {"patch": 0, "minor": 1, "major": 2}

# The four keys `dvc diff --json` returns. Only two of them name a dataset that exists on
# both sides of the revision range, and only those two can be compared at all.
COMPARABLE_STATUSES = ("modified", "renamed")
ALL_STATUSES = ("added", "deleted", "modified", "renamed")

SKIP_REASONS = {
    "added": "added in this revision, so there is no previous version to compare against",
    "deleted": "deleted in this revision",
}


class DvcError(RuntimeError):
    """Raised when DVC is absent, or refuses to answer."""


class SkippedDataset(Exception):
    """Raised when a dataset cannot be compared and should be reported as skipped."""


@dataclass(frozen=True)
class Change:
    """One entry of `dvc diff`, with the paths on each side named separately.

    A rename is the reason both fields exist: it is the one status where the dataset is not
    at the same path in both revisions, and comparing it means reading each side by its own
    name.
    """

    status: str
    old_path: str | None
    new_path: str | None

    @property
    def path(self) -> str:
        """The name to report the dataset under, which is where it ended up."""
        return self.new_path or self.old_path or ""


@dataclass
class DatasetReport:
    """The outcome of analysing one dataset across a revision range."""

    path: str
    status: str
    current_version: str
    next_version: str
    bump: str | None
    changes: list[dict] = field(default_factory=list)
    renamed_from: str | None = None

    @property
    def rank(self) -> int:
        return SEVERITY_RANK.get(self.bump or "", -1)


# --- talking to DVC ------------------------------------------------------------------------


def run_dvc(arguments: list[str], repo: Path) -> str:
    """Run a DVC command in `repo` and return its stdout.

    Every way this fails is turned into one sentence that names what to do about it. DVC
    prints a support link under its errors, which is friendly on a terminal and noise inside
    another tool's error message.
    """
    try:
        result = subprocess.run(
            ["dvc", *arguments],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise DvcError(f"dvc is not installed or not on PATH. {INSTALL_HINT}") from error
    except OSError as error:  # pragma: no cover - depends on the platform's exec failures
        raise DvcError(f"could not run dvc: {error}") from error

    if result.returncode != 0:
        raise DvcError(explain_failure(result.stderr, arguments))
    return result.stdout


def explain_failure(stderr: str, arguments: list[str]) -> str:
    """Turn DVC's stderr into a sentence that says what to do next.

    The two failures worth recognising are the ones a first-time user hits: running outside a
    DVC repository, and asking for data that was never pulled. DVC reports the second as
    "unexpected error - No storage files available", which reads like a bug rather than a
    missing `dvc pull`.
    """
    message = first_line(stderr) or "dvc failed with no output"
    lowered = stderr.lower()

    if "not inside of a dvc repository" in lowered:
        return "this is not a DVC repository: run `dvc init`, or point --repo at one"
    if "no storage files available" in lowered:
        return (
            f"{message}. That version of the data is not in the local cache; "
            "run `dvc pull` first, or configure the remote holding it"
        )
    return f"dvc {' '.join(arguments)} failed: {message}"


def first_line(stderr: str) -> str:
    """The first meaningful line of DVC's output, without its support footer."""
    for line in stderr.strip().splitlines():
        cleaned = line.strip()
        if cleaned and not cleaned.startswith("Having any troubles?"):
            return cleaned.removeprefix("ERROR: ").removeprefix("unexpected error - ")
    return ""


def changed_datasets(repo: Path, rev: str, to_rev: str | None) -> list[Change]:
    """List the datasets DVC reports as changed between two revisions.

    `to_rev` is None for the working tree, which is what `dvc diff <rev>` compares against
    and the case that matters day to day: what have I changed since the last commit.
    """
    arguments = ["diff", rev, *([to_rev] if to_rev else []), "--json"]
    return parse_diff(run_dvc(arguments, repo))


def parse_diff(output: str) -> list[Change]:
    """Read `dvc diff --json` into changes, keeping only the supported dataset formats.

    A renamed entry does not carry a path string like the others: DVC nests `{"old": ...,
    "new": ...}` under the same `path` key. Reading every entry the same way is the mistake
    this function exists to not make.
    """
    try:
        payload = json.loads(output or "{}")
    except json.JSONDecodeError as error:
        raise DvcError(f"dvc diff returned output that is not JSON: {error}") from error
    if not isinstance(payload, dict):
        raise DvcError("dvc diff returned JSON that is not an object")

    changes: list[Change] = []
    for status in ALL_STATUSES:
        for entry in payload.get(status) or []:
            change = read_entry(status, entry)
            if change is not None and is_dataset(change.path):
                changes.append(change)
    return sorted(changes, key=lambda change: change.path)


def read_entry(status: str, entry: object) -> Change | None:
    """One `dvc diff` entry as a Change, or None when it is not shaped like one."""
    if not isinstance(entry, dict):
        return None
    path = entry.get("path")

    if isinstance(path, dict):
        old, new = path.get("old"), path.get("new")
        if not isinstance(old, str) or not isinstance(new, str):
            return None
        return Change(status=status, old_path=old, new_path=new)

    if not isinstance(path, str):
        return None
    if status == "added":
        return Change(status=status, old_path=None, new_path=path)
    if status == "deleted":
        return Change(status=status, old_path=path, new_path=None)
    return Change(status=status, old_path=path, new_path=path)


def is_dataset(path: str) -> bool:
    """Whether a path is one of the formats DataSemver reads."""
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def fetch(repo: Path, path: str, rev: str, destination: Path) -> Path:
    """Copy one revision of a DVC-tracked dataset into a scratch file.

    `dvc get` reads the pointer at that revision and pulls the matching bytes from the cache
    or the remote, which is the step `git show` cannot stand in for.
    """
    run_dvc(
        ["get", str(repo), path, "--rev", rev, "--out", str(destination), "--force"],
        repo=repo,
    )
    if not destination.exists():
        raise DvcError(f"dvc get produced no file for '{path}' at {rev}")
    return destination


def recorded_version(repo: Path, path: str, rev: str) -> str | None:
    """The version written beside a dataset at a given revision, or None.

    The sidecar is a few bytes of text, so it is tracked by git rather than DVC and can be
    read straight out of the revision. This is the one piece of the comparison that does not
    go through DVC, and the reason a bump suggested here continues from the last one instead
    of restarting at the default every time.
    """
    result = subprocess.run(
        ["git", "show", f"{rev}:{path}{VERSION_SUFFIX}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


# --- the analysis --------------------------------------------------------------------------


def analyse(
    repo: Path,
    rev: str,
    to_rev: str | None = None,
    paths: list[str] | None = None,
    current_version: str = DEFAULT_VERSION,
    rules: Path | None = None,
) -> tuple[list[DatasetReport], list[tuple[str, str]]]:
    """Compare every dataset DVC reports as changed, and say why the rest were skipped."""
    changes = changed_datasets(repo, rev, to_rev)
    if paths:
        wanted = set(paths)
        changes = [change for change in changes if wanted & {change.old_path, change.new_path}]

    reports: list[DatasetReport] = []
    skipped: list[tuple[str, str]] = []
    for change in changes:
        try:
            reports.append(analyse_change(repo, change, rev, to_rev, current_version, rules))
        except SkippedDataset as reason:
            skipped.append((change.path, str(reason)))
    return reports, skipped


def analyse_change(
    repo: Path,
    change: Change,
    rev: str,
    to_rev: str | None,
    current_version: str,
    rules: Path | None,
) -> DatasetReport:
    """Compare one dataset across the revision range."""
    if change.status not in COMPARABLE_STATUSES:
        raise SkippedDataset(SKIP_REASONS.get(change.status, "cannot be compared"))

    old_path = change.old_path
    new_path = change.new_path
    if old_path is None or new_path is None:  # pragma: no cover - guarded by the status check
        raise SkippedDataset("cannot be compared")

    started_from = recorded_version(repo, old_path, rev) or current_version

    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        try:
            old_file = fetch(repo, old_path, rev, scratch / f"old{Path(old_path).suffix}")
            new_file = resolve_new_side(repo, new_path, to_rev, scratch)
        except DvcError as error:
            raise SkippedDataset(str(error)) from error

        try:
            report = analyze(old_file, new_file, rules=rules, current_version=started_from)
        except (ValueError, RuleError) as error:
            raise SkippedDataset(f"could not be analysed: {error}") from error

    return DatasetReport(
        path=change.path,
        status=change.status,
        current_version=report.current_version,
        next_version=report.next_version,
        bump=report.bump.value if report.bump else None,
        changes=[item for item in report.model_dump(mode="json")["classified"] if item["severity"]],
        renamed_from=old_path if change.status == "renamed" else None,
    )


def resolve_new_side(repo: Path, path: str, to_rev: str | None, scratch: Path) -> Path:
    """Where to read the newer version from.

    With no target revision the comparison runs against the working tree, and the file is
    already on disk -- pulling a copy of it out of DVC would compare the commit against
    itself and report nothing, which is exactly the case the user is asking about.
    """
    if to_rev is None:
        working = repo / path
        if not working.is_file():
            raise SkippedDataset(f"'{path}' is not in the working tree; run `dvc checkout`")
        return working
    return fetch(repo, path, to_rev, scratch / f"new{Path(path).suffix}")


# --- output --------------------------------------------------------------------------------


def as_payload(
    reports: list[DatasetReport],
    skipped: list[tuple[str, str]],
    rev: str,
    to_rev: str | None,
) -> dict:
    """The whole run as JSON, for a pipeline step that has to decide something with it."""
    overall = max(reports, key=lambda report: report.rank).bump if reports else None
    return {
        "rev": rev,
        "to_rev": to_rev or "workspace",
        "bump": overall,
        "datasets": [
            {
                "path": report.path,
                "status": report.status,
                "renamed_from": report.renamed_from,
                "current_version": report.current_version,
                "next_version": report.next_version,
                "bump": report.bump,
                "changes": report.changes,
            }
            for report in ranked(reports)
        ],
        "skipped": [{"path": path, "reason": reason} for path, reason in skipped],
    }


def ranked(reports: list[DatasetReport]) -> list[DatasetReport]:
    """Most severe first, then alphabetical, so the thing to look at is at the top."""
    return sorted(reports, key=lambda report: (-report.rank, report.path))


def render_markdown(
    reports: list[DatasetReport],
    skipped: list[tuple[str, str]],
    rev: str,
    to_rev: str | None,
) -> str:
    """A report to drop in a pipeline log, a pull request, or a file."""
    target = to_rev or "the working tree"
    lines = ["## DataSemver over DVC", "", f"Comparing `{rev}` against {target}.", ""]

    if not reports:
        lines.append("No versioned dataset changed.")
        lines.append("")
        lines.extend(render_skipped(skipped))
        return "\n".join(lines).rstrip() + "\n"

    overall = max(reports, key=lambda report: report.rank).bump
    lines.append(f"Suggested bump: **{(overall or 'none').upper()}**")
    lines.append("")
    lines.append("| Dataset | Current | Suggested | Bump | Changes |")
    lines.append("| --- | --- | --- | --- | --- |")
    for report in ranked(reports):
        name = f"`{report.path}`"
        if report.renamed_from:
            name += f" (was `{report.renamed_from}`)"
        lines.append(
            f"| {name} | {report.current_version} | **{report.next_version}** | "
            f"{(report.bump or 'none').upper()} | {len(report.changes)} |"
        )
    lines.append("")

    for report in ranked(reports):
        lines.extend(render_details(report))
    lines.extend(render_skipped(skipped))
    return "\n".join(lines).rstrip() + "\n"


def render_details(report: DatasetReport, top: int = 5) -> list[str]:
    if not report.changes:
        return []
    order = sorted(report.changes, key=lambda item: -SEVERITY_RANK.get(item["severity"], -1))
    lines = [
        f"<details><summary><code>{report.path}</code> — {len(report.changes)} classified "
        f"change(s)</summary>",
        "",
    ]
    for item in order[:top]:
        lines.append(
            f"- **{item['severity'].upper()}** (`{item['rule']}`): {item['change']['description']}"
        )
    remaining = len(order) - top
    if remaining > 0:
        lines.append(f"- … and {remaining} more")
    lines.extend(["", "</details>", ""])
    return lines


def render_skipped(skipped: list[tuple[str, str]]) -> list[str]:
    if not skipped:
        return []
    lines = ["### Skipped", ""]
    lines.extend(f"- `{path}`: {reason}" for path, reason in skipped)
    lines.append("")
    return lines
