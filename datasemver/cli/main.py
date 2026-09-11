"""Command line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from datasemver import __version__
from datasemver.core.analyzer import DEFAULT_VERSION, analyze
from datasemver.core.changelog import render_entry, severity_label, write_changelog
from datasemver.core.models import AnalysisReport, ColumnStatus, Severity
from datasemver.core.profile import ProfileError, write_profile
from datasemver.formats.loader import default_profile_path, load_schema
from datasemver.integrations import dvc as dvc_integration
from datasemver.rules.engine import EVALUATION_ORDER, RuleError, load_rules
from datasemver.utils.version import InvalidVersionError

app = typer.Typer(
    name="datasemver",
    help="Semantic versioning for datasets.",
    add_completion=False,
    no_args_is_help=True,
)

_SOURCE_HELP = "{which} version of the dataset: a file, or a database URL with the table after '#'."

# `legacy_windows=False` rather than letting rich decide. Rich calls the pre-VT Windows
# console API when it cannot confirm the terminal understands escape sequences, and it cannot
# confirm that when stdout is a pipe: `GetConsoleMode` fails on a pipe handle, rich concludes
# the console is ancient, and then calls the console API on something that is not a console.
# `datasemver rules | findstr x` died there with `OSError: [Errno 22] Invalid argument`. Every
# Windows that VT support ever shipped in is Windows 10 or newer, so nothing supported loses
# anything, and the redirected output that CI and scripts actually use now works.
console = Console(legacy_windows=False)
error_console = Console(stderr=True, legacy_windows=False)

# Exit 2 already means "the command could not run", so the gate takes 1: a run that worked
# and found what it was told to refuse is not the same thing as a run that failed, and a
# caller that cannot tell them apart cannot tell a broken pipeline from a rejected dataset.
GATE_EXIT_CODE = 1

_FAIL_ON_HELP = "Exit with code 1 when the suggested bump reaches this severity or higher."
_PROFILE_OUTPUT_HELP = "Where to write it; defaults to <name>.profile.json beside the dataset."
_KEY_HELP = (
    "Column identifying a row, repeated for a composite key. Reports rows added, "
    "removed and changed, which no comparison of profiles can see."
)
_SCHEMA_ONLY_HELP = (
    "Profile Parquet from its footer instead of its rows: fast, but no distribution "
    "comparison, because no data is read."
)


SEVERITY_COLORS: dict[Severity, str] = {
    Severity.MAJOR: "bold red",
    Severity.MINOR: "bold yellow",
    Severity.PATCH: "bold green",
}

STATUS_COLORS: dict[ColumnStatus, str] = {
    ColumnStatus.ADDED: "green",
    ColumnStatus.REMOVED: "red",
    ColumnStatus.RENAMED: "magenta",
    ColumnStatus.MODIFIED: "yellow",
    ColumnStatus.UNCHANGED: "dim",
}


def _print_version(requested: bool) -> None:
    """Report the running version and stop.

    Worth having on any command line, and worth more here than most: a profile records the
    version that wrote it and is refused by an older reader, so someone meeting that message
    needs to be able to say which version they are holding.
    """
    if requested:
        console.print(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Print the installed version and exit.",
        ),
    ] = False,
) -> None:
    """Semantic versioning for datasets."""


@app.command()
def diff(
    old: Annotated[str, typer.Argument(help=_SOURCE_HELP.format(which="Previous"))],
    new: Annotated[str, typer.Argument(help=_SOURCE_HELP.format(which="New"))],
    rules: Annotated[
        Path | None,
        typer.Option("--rules", "-r", help="Custom rules file overriding the defaults."),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the report as JSON instead of a table.")
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the changelog entry to this file."),
    ] = None,
    current_version: Annotated[
        str,
        typer.Option("--current-version", "-c", help="Version the new dataset is bumped from."),
    ] = DEFAULT_VERSION,
    fail_on: Annotated[
        Severity | None,
        typer.Option("--fail-on", help=_FAIL_ON_HELP),
    ] = None,
    schema_only: Annotated[bool, typer.Option("--schema-only", help=_SCHEMA_ONLY_HELP)] = False,
    key: Annotated[list[str] | None, typer.Option("--key", "-k", help=_KEY_HELP)] = None,
) -> None:
    """Compare two dataset versions and suggest a semantic version bump."""
    try:
        report = analyze(
            old,
            new,
            rules=rules,
            current_version=current_version,
            schema_only=schema_only,
            key=list(key) if key else None,
        )
    except (FileNotFoundError, ValueError, RuleError, InvalidVersionError) as error:
        error_console.print(f"[bold red]error:[/] {escape(str(error))}")
        raise typer.Exit(code=2) from error

    if output is not None:
        write_changelog(report, output)

    if as_json:
        console.print_json(json.dumps(report.model_dump(mode="json")))
    else:
        _render_report(report, output)

    _apply_gate(report.bump, fail_on)


def _apply_gate(bump: Severity | None, fail_on: Severity | None) -> None:
    """Turn the suggested bump into an exit code, so a pipeline can refuse to continue.

    Without this the command is advisory whatever it finds: it prints a breaking change and
    exits 0, and the only way to act on it is to parse the JSON.
    """
    if fail_on is None or bump is None or bump < fail_on:
        return
    error_console.print(
        f"[bold red]refused:[/] suggested bump is {bump.value}, "
        f"which reaches the --fail-on threshold of {fail_on.value}"
    )
    raise typer.Exit(code=GATE_EXIT_CODE)


def _render_report(report: AnalysisReport, output: Path | None) -> None:
    bump = severity_label(report.bump)
    style = SEVERITY_COLORS.get(report.bump, "bold blue") if report.bump else "bold blue"

    console.print(
        Panel(
            f"[{style}]Suggested bump: {bump}[/]\n"
            f"{report.current_version} -> {report.next_version}\n\n"
            f"old: {report.old_source} ({report.diff.old.row_count} rows)\n"
            f"new: {report.new_source} ({report.diff.new.row_count} rows)",
            title="DataSemver",
            expand=False,
        )
    )

    console.print(_columns_table(report))
    console.print(_changes_table(report))

    if output is not None:
        console.print(f"[dim]changelog written to {output}[/]")
    else:
        console.print(Panel(render_entry(report).rstrip(), title="CHANGELOG", expand=False))


def _columns_table(report: AnalysisReport) -> Table:
    table = Table(title="Columns", header_style="bold")
    for header in ("column", "status", "type old", "type new", "nulls", "cardinality"):
        table.add_column(header)

    for column in report.diff.columns:
        name = column.name if not column.renamed_from else f"{column.renamed_from} -> {column.name}"
        table.add_row(
            name,
            f"[{STATUS_COLORS[column.status]}]{column.status.value}[/]",
            column.dtype_old or "-",
            column.dtype_new or "-",
            f"{_percent(column.null_ratio_old)} -> {_percent(column.null_ratio_new)}",
            f"{_number(column.cardinality_old)} -> {_number(column.cardinality_new)}",
        )
    return table


def _changes_table(report: AnalysisReport) -> Table:
    table = Table(title="Changes", header_style="bold")
    table.add_column("severity")
    table.add_column("rule")
    table.add_column("description")

    ordered = sorted(
        report.classified,
        key=lambda item: -item.severity.rank if item.severity else 1,
    )
    for item in ordered:
        severity = item.severity
        label = severity.value.upper() if severity else "unclassified"
        style = SEVERITY_COLORS.get(severity, "dim") if severity else "dim"
        table.add_row(f"[{style}]{label}[/]", item.rule or "-", item.change.description)

    if not ordered:
        table.add_row("[dim]none[/]", "-", "Datasets are identical")
    return table


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def _number(value: int | None) -> str:
    return "-" if value is None else str(value)


@app.command("dvc")
def dvc(
    paths: Annotated[
        list[str] | None,
        typer.Argument(help="Limit the run to these datasets; defaults to everything changed."),
    ] = None,
    rev: Annotated[
        str,
        typer.Option("--rev", help="Revision to compare from."),
    ] = "HEAD^",
    to_rev: Annotated[
        str | None,
        typer.Option("--to", help="Revision to compare to; defaults to the working tree."),
    ] = None,
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Path to the DVC repository."),
    ] = Path(),
    rules: Annotated[
        Path | None,
        typer.Option("--rules", "-r", help="Custom rules file overriding the defaults."),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the run as JSON instead of a table.")
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write a Markdown report to this file."),
    ] = None,
    current_version: Annotated[
        str,
        typer.Option(
            "--current-version",
            "-c",
            help="Version to bump from when a dataset records none beside it.",
        ),
    ] = DEFAULT_VERSION,
    fail_on: Annotated[
        Severity | None,
        typer.Option("--fail-on", help=_FAIL_ON_HELP),
    ] = None,
) -> None:
    """Analyse the datasets DVC reports as changed between two revisions."""
    try:
        reports, skipped = dvc_integration.analyse(
            repo=repo,
            rev=rev,
            to_rev=to_rev,
            paths=list(paths) if paths else None,
            current_version=current_version,
            rules=rules,
        )
    except (dvc_integration.DvcError, RuleError, InvalidVersionError) as error:
        error_console.print(f"[bold red]error:[/] {escape(str(error))}")
        raise typer.Exit(code=2) from error

    if output is not None:
        output.write_text(
            dvc_integration.render_markdown(reports, skipped, rev, to_rev), encoding="utf-8"
        )

    if as_json:
        console.print_json(json.dumps(dvc_integration.as_payload(reports, skipped, rev, to_rev)))
    else:
        _render_dvc_run(reports, skipped, rev, to_rev, output)

    # The run's severity is its worst dataset: one breaking change in one dataset is a
    # breaking change in the revision being proposed.
    worst = max((report.bump for report in reports if report.bump), default=None, key=_rank)
    _apply_gate(Severity(worst) if worst else None, fail_on)


def _rank(bump: str) -> int:
    return Severity(bump).rank


def _render_dvc_run(
    reports: list[dvc_integration.DatasetReport],
    skipped: list[tuple[str, str]],
    rev: str,
    to_rev: str | None,
    output: Path | None,
) -> None:
    target = to_rev or "working tree"
    if not reports:
        console.print(f"[dim]no versioned dataset changed between {rev} and {target}[/]")
    else:
        overall = max(reports, key=lambda report: report.rank).bump
        style = SEVERITY_COLORS.get(Severity(overall), "bold blue") if overall else "bold blue"
        console.print(
            Panel(
                f"[{style}]Suggested bump: {(overall or 'none').upper()}[/]\n{rev} -> {target}",
                title="DataSemver over DVC",
                expand=False,
            )
        )
        console.print(_dvc_table(reports))

    for path, reason in skipped:
        console.print(f"[dim]skipped {path}: {reason}[/]")

    if output is not None:
        console.print(f"[dim]report written to {output}[/]")


def _dvc_table(reports: list[dvc_integration.DatasetReport]) -> Table:
    table = Table(title="Datasets", header_style="bold")
    for header in ("dataset", "status", "current", "suggested", "bump", "changes"):
        table.add_column(header)
    for report in dvc_integration.ranked(reports):
        name = report.path
        if report.renamed_from:
            name += f"\n[dim]was {report.renamed_from}[/]"
        bump = report.bump or "none"
        style = SEVERITY_COLORS.get(Severity(report.bump), "dim") if report.bump else "dim"
        table.add_row(
            name,
            report.status,
            report.current_version,
            report.next_version,
            f"[{style}]{bump.upper()}[/]",
            str(len(report.changes)),
        )
    return table


@app.command("profile")
def profile(
    source: Annotated[str, typer.Argument(help=_SOURCE_HELP.format(which="The"))],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help=_PROFILE_OUTPUT_HELP),
    ] = None,
) -> None:
    """Write a dataset's profile to a file that can be compared against later.

    The profile is what a comparison reads, and it is a few hundred bytes where the dataset
    is megabytes. Store it beside the data and the next comparison needs only the new
    version: `datasemver diff customers.profile.json customers_v4.parquet`.
    """
    try:
        schema = load_schema(source)
    except (FileNotFoundError, ValueError, ProfileError) as error:
        error_console.print(f"[bold red]error:[/] {escape(str(error))}")
        raise typer.Exit(code=2) from error

    destination = write_profile(schema, output or default_profile_path(source))
    size = destination.stat().st_size
    console.print(
        f"[bold green]profile written[/] {destination} "
        f"[dim]({len(schema.columns)} columns, {schema.row_count} rows, {size} bytes)[/]"
    )


@app.command("rules")
def show_rules(
    path: Annotated[
        Path | None, typer.Argument(help="Rules file to inspect; defaults to the bundled rules.")
    ] = None,
) -> None:
    """Print the rules that will be applied, grouped by severity."""
    try:
        rule_set = load_rules(path)
    except (FileNotFoundError, RuleError) as error:
        error_console.print(f"[bold red]error:[/] {escape(str(error))}")
        raise typer.Exit(code=2) from error

    for severity in EVALUATION_ORDER:
        entries = rule_set.rules.get(severity, [])
        console.print(f"[{SEVERITY_COLORS[severity]}]{severity.value}[/]")
        for rule in entries or []:
            suffix = f" > {rule.threshold:g}" if rule.threshold is not None else ""
            console.print(f"  - {rule.name}{suffix}")
        if not entries:
            console.print("  [dim]- none[/]")


if __name__ == "__main__":
    app()
