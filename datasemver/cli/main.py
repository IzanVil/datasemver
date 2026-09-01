"""Command line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from datasemver.core.analyzer import DEFAULT_VERSION, analyze
from datasemver.core.changelog import render_entry, severity_label, write_changelog
from datasemver.core.models import AnalysisReport, ColumnStatus, Severity
from datasemver.rules.engine import EVALUATION_ORDER, RuleError, load_rules
from datasemver.utils.version import InvalidVersionError

app = typer.Typer(
    name="datasemver",
    help="Semantic versioning for datasets.",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()
error_console = Console(stderr=True)

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


@app.command()
def diff(
    old: Annotated[Path, typer.Argument(help="Previous version of the dataset (CSV or JSON).")],
    new: Annotated[Path, typer.Argument(help="New version of the dataset (CSV or JSON).")],
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
) -> None:
    """Compare two dataset versions and suggest a semantic version bump."""
    try:
        report = analyze(old, new, rules=rules, current_version=current_version)
    except (FileNotFoundError, ValueError, RuleError, InvalidVersionError) as error:
        error_console.print(f"[bold red]error:[/] {error}")
        raise typer.Exit(code=2) from error

    if output is not None:
        write_changelog(report, output)

    if as_json:
        console.print_json(json.dumps(report.model_dump(mode="json")))
        return

    _render_report(report, output)


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
        error_console.print(f"[bold red]error:[/] {error}")
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
