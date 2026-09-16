"""The `.version` sidecar: where it goes, and what is allowed into it.

Read in two places before anything wrote it -- `datasemver dvc` and the pull request script
-- which is why its name is fixed by the library rather than by whoever writes it next.
"""

from pathlib import Path

import pytest

from datasemver.formats.loader import default_version_path
from datasemver.utils.version import VERSION_SUFFIX, InvalidVersionError, write_version

# --- where it goes --------------------------------------------------------------------------


def test_the_sidecar_sits_beside_its_dataset(tmp_path):
    assert default_version_path(tmp_path / "customers.parquet") == (
        tmp_path / f"customers.parquet{VERSION_SUFFIX}"
    )


def test_the_format_suffix_is_kept_rather_than_replaced(tmp_path):
    """The one way this differs from how a profile is named, and it is deliberate.

    A profile describes a dataset whichever format it arrived in, so `sales.csv` and
    `sales.parquet` share `sales.profile.json`. A version belongs to the file it was computed
    for, and two formats of one dataset are not obliged to be at the same version.
    """
    csv = default_version_path(tmp_path / "sales.csv")
    parquet = default_version_path(tmp_path / "sales.parquet")

    assert csv.name == f"sales.csv{VERSION_SUFFIX}"
    assert csv != parquet


def test_a_compound_extension_is_kept_whole(tmp_path):
    assert default_version_path(tmp_path / "dump.csv.gz").name == f"dump.csv.gz{VERSION_SUFFIX}"


def test_the_name_matches_what_the_readers_already_look_for(tmp_path):
    """`dvc.py` and the PR script both read `f"{path}{VERSION_SUFFIX}"`, and predate this."""
    dataset = tmp_path / "data" / "sales.csv"

    assert default_version_path(dataset) == Path(f"{dataset}{VERSION_SUFFIX}")


def test_a_connection_password_never_reaches_the_sidecar_name():
    """The same hazard the profile name had: a file name outlives the command that made it."""
    path = default_version_path("postgresql://reader:s3cret@warehouse:5432/analytics#customers")

    assert path == Path(f"customers{VERSION_SUFFIX}")
    assert "s3cret" not in str(path)


def test_a_table_name_cannot_name_a_directory():
    path = default_version_path("sqlite:///data.db#sales/2024")

    assert path.name == f"sales-2024{VERSION_SUFFIX}"
    assert path.parent == Path()


def test_two_sheets_of_one_workbook_get_two_sidecars(tmp_path):
    third = default_version_path(tmp_path / "quarterly.xlsx#Q3")
    fourth = default_version_path(tmp_path / "quarterly.xlsx#Q4")

    assert third.name == f"quarterly.xlsx-Q3{VERSION_SUFFIX}"
    assert third.parent == tmp_path
    assert third != fourth


def test_a_workbook_without_a_sheet_is_named_after_the_workbook(tmp_path):
    assert (
        default_version_path(tmp_path / "quarterly.xlsx").name == f"quarterly.xlsx{VERSION_SUFFIX}"
    )


# --- what gets written ----------------------------------------------------------------------


def test_the_version_is_written_with_a_trailing_newline(tmp_path):
    """It is a text file in git, and a file without one shows up as a diff artefact."""
    sidecar = tmp_path / "sales.csv.version"

    write_version(sidecar, "1.5.0")

    assert sidecar.read_text(encoding="utf-8") == "1.5.0\n"


def test_writing_creates_the_directory_when_it_is_missing(tmp_path):
    sidecar = tmp_path / "nested" / "sales.csv.version"

    write_version(sidecar, "1.5.0")

    assert sidecar.is_file()


def test_something_that_is_not_a_version_is_refused_before_it_is_written(tmp_path):
    """Refused here, or the next run reads it back and fails somewhere that cannot explain it."""
    sidecar = tmp_path / "sales.csv.version"

    with pytest.raises(InvalidVersionError):
        write_version(sidecar, "yesterday")

    assert not sidecar.exists()


def test_a_bad_version_does_not_destroy_the_good_one_already_there(tmp_path):
    """Validation before the open matters: `write_text` would have truncated it first."""
    sidecar = tmp_path / "sales.csv.version"
    sidecar.write_text("1.4.2\n", encoding="utf-8")

    with pytest.raises(InvalidVersionError):
        write_version(sidecar, "not-a-version")

    assert sidecar.read_text(encoding="utf-8") == "1.4.2\n"


def test_the_sidecar_is_read_back_by_the_readers_that_predate_it(tmp_path):
    """The round trip the flag exists for: what is written is what `dvc` reads as recorded."""
    sidecar = tmp_path / "sales.csv.version"
    write_version(sidecar, "2.0.0")

    assert sidecar.read_text(encoding="utf-8").strip() == "2.0.0"
