"""Changelog rendering."""

from __future__ import annotations

from pathlib import Path

from datasemver.core.models import AnalysisReport, Severity
from datasemver.rules.engine import EVALUATION_ORDER

CHANGELOG_TITLE = "# Changelog"


def render_entry(report: AnalysisReport) -> str:
    """Render a single changelog entry for an analysis report."""
    lines = [f"## [{report.next_version}] - {report.generated_at.isoformat()}", ""]

    for severity in EVALUATION_ORDER:
        items = report.by_severity(severity)
        if not items:
            continue
        lines.append(f"### {severity.value.capitalize()}")
        lines.extend(f"- {item.change.description}" for item in items)
        lines.append("")

    if len(lines) == 2:
        lines.append("No classified changes detected.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_changelog(report: AnalysisReport) -> str:
    """Render a full changelog document containing a single entry."""
    return f"{CHANGELOG_TITLE}\n\n{render_entry(report)}"


def write_changelog(report: AnalysisReport, path: str | Path) -> Path:
    """Write the entry to a changelog file, prepending it when the file already exists."""
    path = Path(path)
    entry = render_entry(report)

    if not path.exists():
        path.write_text(render_changelog(report), encoding="utf-8")
        return path

    existing = path.read_text(encoding="utf-8").lstrip()
    if existing.startswith(CHANGELOG_TITLE):
        body = existing[len(CHANGELOG_TITLE) :].lstrip("\n")
        path.write_text(f"{CHANGELOG_TITLE}\n\n{entry}\n{body}", encoding="utf-8")
    else:
        path.write_text(f"{entry}\n{existing}", encoding="utf-8")
    return path


def severity_label(severity: Severity | None) -> str:
    return severity.value.upper() if severity else "NONE"
