import json
import subprocess
import sys

import pandas as pd

from datasemver.core.analyzer import analyze, analyze_schemas
from datasemver.core.changelog import render_entry, write_changelog
from datasemver.core.models import ChangeType, Severity
from datasemver.formats.loader import schema_from_frame
from datasemver.utils.version import bump_version


def test_analyze_csv_pair_suggests_major(old_csv, new_csv):
    report = analyze(old_csv, new_csv, current_version="1.4.2")

    assert report.bump is Severity.MAJOR
    assert report.next_version == "2.0.0"
    assert {item.change.type for item in report.by_severity(Severity.MAJOR)} == {
        ChangeType.COLUMN_REMOVED,
        ChangeType.TYPE_CHANGED_INCOMPATIBLE,
    }


def test_analyze_json_pair_suggests_minor(old_json, new_json):
    report = analyze(old_json, new_json, current_version="0.3.1")

    assert report.bump is Severity.MINOR
    assert report.next_version == "0.4.0"


def test_analyze_identical_datasets_keeps_the_version(old_csv):
    report = analyze(old_csv, old_csv, current_version="2.1.0")

    assert report.bump is None
    assert report.next_version == "2.1.0"
    assert report.classified == []


def test_custom_rules_change_the_bump(old_csv, new_csv, tmp_path):
    path = tmp_path / "lenient.yaml"
    path.write_text("minor:\n  - column_removed\npatch:\n  - nulls_fixed\n", encoding="utf-8")

    report = analyze(old_csv, new_csv, rules=path, current_version="1.0.0")

    assert report.bump is Severity.MINOR
    assert report.next_version == "1.1.0"


def test_analyze_schemas_accepts_dataframes():
    old = schema_from_frame(pd.DataFrame({"a": [1, 2], "b": [1, 2]}), "old")
    new = schema_from_frame(pd.DataFrame({"a": [1, 2]}), "new")

    report = analyze_schemas(old, new)

    assert report.bump is Severity.MAJOR


def test_changelog_entry_orders_sections(old_csv, new_csv):
    entry = render_entry(analyze(old_csv, new_csv))

    assert entry.index("### Major") < entry.index("### Minor") < entry.index("### Patch")
    assert "- Column 'legacy_code' was removed" in entry


def test_write_changelog_creates_and_prepends(old_csv, new_csv, tmp_path):
    path = tmp_path / "CHANGELOG.md"

    write_changelog(analyze(old_csv, new_csv, current_version="1.0.0"), path)
    first = path.read_text(encoding="utf-8")
    write_changelog(analyze(old_csv, new_csv, current_version="2.0.0"), path)
    second = path.read_text(encoding="utf-8")

    assert first.startswith("# Changelog")
    assert second.count("# Changelog") == 1
    assert second.index("## [3.0.0]") < second.index("## [2.0.0]")


def test_bump_version_arithmetic():
    assert bump_version("1.2.3", Severity.MAJOR) == "2.0.0"
    assert bump_version("1.2.3", Severity.MINOR) == "1.3.0"
    assert bump_version("1.2.3", Severity.PATCH) == "1.2.4"
    assert bump_version("1.2.3", None) == "1.2.3"


def test_changelog_is_prepended_to_a_file_without_a_title(old_csv, new_csv, tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text("## [0.1.0] - 2020-01-01\n\n### Minor\n- first release\n", encoding="utf-8")

    write_changelog(analyze(old_csv, new_csv, current_version="1.0.0"), path)
    content = path.read_text(encoding="utf-8")

    assert content.startswith("## [2.0.0]")
    assert "- first release" in content


def test_changelog_of_identical_datasets(old_csv):
    entry = render_entry(analyze(old_csv, old_csv))

    assert "No classified changes detected." in entry


def test_module_entry_point_runs(old_csv, new_csv):
    result = subprocess.run(
        [sys.executable, "-m", "datasemver", "diff", str(old_csv), str(new_csv), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["bump"] == "major"
