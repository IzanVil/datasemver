"""Tests for the stored profile: the file that lets a comparison outlive its dataset.

The promise here is narrow and worth pinning exactly. A profile written today is read back
by a later version, and a comparison against one never touches the dataset behind it -- so
the tests that matter are the round trip, the comparison made with the old dataset deleted,
and every way a file that is not a readable profile is refused instead of half-understood.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from datasemver import analyze
from datasemver.core.models import Severity
from datasemver.core.profile import (
    PROFILE_SUFFIX,
    PROFILE_VERSION,
    ProfileError,
    default_profile_path,
    is_profile,
    read_profile,
    write_profile,
)
from datasemver.formats.loader import load_schema, schema_from_frame

# --- naming ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("customers.profile.json", True),
        ("customers.PROFILE.JSON", True),
        ("/data/a/b.profile.json", True),
        ("customers.json", False),
        ("customers.parquet", False),
        ("profile.json", False),
    ],
)
def test_only_the_double_suffix_names_a_profile(source, expected):
    """`.json` on its own is a dataset format, so the two must never be confused."""
    assert is_profile(source) is expected


def test_a_profile_defaults_to_sitting_beside_its_dataset(tmp_path):
    assert default_profile_path(tmp_path / "customers.parquet").name == f"customers{PROFILE_SUFFIX}"


def test_a_compound_extension_does_not_leak_into_the_profile_name(tmp_path):
    assert default_profile_path(tmp_path / "dump.csv.gz").name == f"dump{PROFILE_SUFFIX}"


# --- the round trip -------------------------------------------------------------------------


def test_a_profile_read_back_is_the_one_that_was_written(tmp_path, old_csv):
    original = load_schema(old_csv)

    restored = read_profile(write_profile(original, tmp_path / f"old{PROFILE_SUFFIX}"))

    assert restored == original


def test_a_profile_keeps_the_quantile_grid(tmp_path, old_csv):
    """The grid is what makes a stored profile enough to compare distributions against."""
    restored = read_profile(write_profile(load_schema(old_csv), tmp_path / f"o{PROFILE_SUFFIX}"))

    assert restored.columns["score"].quantiles


def test_a_profile_keeps_the_category_counts(tmp_path):
    """The fixtures have no categorical column -- every string in them is unique."""
    frame = pd.DataFrame({"plan": ["pro", "free", "pro", "free", "pro", "free"]})
    schema = schema_from_frame(frame, source="plans.csv")

    restored = read_profile(write_profile(schema, tmp_path / f"plans{PROFILE_SUFFIX}"))

    assert restored.columns["plan"].category_counts == {"pro": 3, "free": 3}


def test_a_profile_records_where_it_came_from(tmp_path, old_csv):
    """A report names the dataset, not the profile: the source is what the reader recognises."""
    restored = read_profile(write_profile(load_schema(old_csv), tmp_path / f"o{PROFILE_SUFFIX}"))

    assert restored.source == str(old_csv)


def test_writing_a_profile_creates_the_directory_it_goes_in(tmp_path, old_csv):
    destination = tmp_path / "nested" / "deeper" / f"old{PROFILE_SUFFIX}"

    assert write_profile(load_schema(old_csv), destination).exists()


def test_a_profile_says_which_format_it_is_in(tmp_path, old_csv):
    written = write_profile(load_schema(old_csv), tmp_path / f"old{PROFILE_SUFFIX}")
    payload = json.loads(written.read_text(encoding="utf-8"))

    assert payload["profile_version"] == PROFILE_VERSION
    assert payload["created_with"]


# --- comparing against one ---------------------------------------------------------------------


def test_a_comparison_against_a_profile_matches_the_one_against_the_dataset(
    tmp_path, old_csv, new_csv
):
    direct = analyze(old_csv, new_csv, current_version="1.0.0")
    stored = write_profile(load_schema(old_csv), tmp_path / f"old{PROFILE_SUFFIX}")

    from_profile = analyze(stored, new_csv, current_version="1.0.0")

    assert from_profile.bump is direct.bump
    assert from_profile.next_version == direct.next_version
    assert [item.rule for item in from_profile.classified] == [
        item.rule for item in direct.classified
    ]


def test_the_dataset_a_profile_describes_does_not_have_to_exist(tmp_path, old_csv, new_csv):
    """This is the point of the whole feature: the previous version is never fetched."""
    copied = tmp_path / "old.csv"
    copied.write_bytes(old_csv.read_bytes())
    stored = write_profile(load_schema(copied), tmp_path / f"old{PROFILE_SUFFIX}")
    copied.unlink()

    report = analyze(stored, new_csv, current_version="1.0.0")

    assert report.bump is Severity.MAJOR


def test_a_profile_works_on_either_side_of_a_comparison(tmp_path, old_csv, new_csv):
    old_stored = write_profile(load_schema(old_csv), tmp_path / f"old{PROFILE_SUFFIX}")
    new_stored = write_profile(load_schema(new_csv), tmp_path / f"new{PROFILE_SUFFIX}")

    report = analyze(old_stored, new_stored, current_version="1.0.0")

    assert report.bump is Severity.MAJOR


# --- refusing what is not a profile -------------------------------------------------------------


def test_a_missing_profile_is_reported_as_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="profile not found"):
        read_profile(tmp_path / f"absent{PROFILE_SUFFIX}")


def test_a_file_that_is_not_json_is_refused(tmp_path):
    broken = tmp_path / f"broken{PROFILE_SUFFIX}"
    broken.write_text("{not json", encoding="utf-8")

    with pytest.raises(ProfileError, match="not valid JSON"):
        read_profile(broken)


def test_json_that_is_not_an_object_is_refused(tmp_path):
    listed = tmp_path / f"listed{PROFILE_SUFFIX}"
    listed.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ProfileError, match="expected an object"):
        read_profile(listed)


def test_json_shaped_like_something_else_is_refused_by_name(tmp_path):
    wrong = tmp_path / f"wrong{PROFILE_SUFFIX}"
    wrong.write_text(json.dumps({"hello": "world"}), encoding="utf-8")

    with pytest.raises(ProfileError, match="not a readable profile"):
        read_profile(wrong)


def test_a_profile_from_a_later_version_is_refused_rather_than_guessed_at(tmp_path, old_csv):
    """Reading a newer format on a best-effort basis would silently compare the wrong thing."""
    written = write_profile(load_schema(old_csv), tmp_path / f"future{PROFILE_SUFFIX}")
    payload = json.loads(written.read_text(encoding="utf-8"))
    payload["profile_version"] = PROFILE_VERSION + 1
    written.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProfileError, match="Upgrade to read it"):
        read_profile(written)
