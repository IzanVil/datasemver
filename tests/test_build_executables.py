"""Tests for the script that freezes the CLI into a standalone executable.

Running PyInstaller takes over a minute, so nothing here does. What is worth testing without
it is the part that is easy to get wrong and silent when it is: the platform guard, the data
files handed to the bundle, the separator between a data file's source and its destination,
and whether the archive keeps the executable bit. The build itself is exercised on all four
runners by the Executables workflow, which then runs the binary it produced.
"""

from __future__ import annotations

import os
import platform
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

build = pytest.importorskip(
    "scripts.build_executables",
    reason="the scripts directory is not shipped in the sdist",
)

# --- the platform guard ---------------------------------------------------------------------


def test_the_platform_defaults_to_the_one_being_used():
    assert build.resolve_platform(None) == build.detect_platform()


def test_asking_for_the_platform_you_are_on_is_allowed():
    running = build.detect_platform()

    assert build.resolve_platform(running) == running


def test_asking_for_another_platform_explains_why_it_cannot_be_done(monkeypatch):
    """PyInstaller freezes the interpreter it runs under, so there is no cross-compiling.

    The flag exists to fail here rather than at the end of a two-minute build that produced
    a binary for the wrong operating system.
    """
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    with pytest.raises(build.BuildError, match="cannot cross-compile"):
        build.resolve_platform("windows")


@pytest.mark.parametrize(
    ("system", "expected"),
    [("Linux", "linux"), ("Darwin", "macos"), ("Windows", "windows")],
)
def test_each_supported_system_has_a_name(monkeypatch, system, expected):
    monkeypatch.setattr(platform, "system", lambda: system)

    assert build.detect_platform() == expected


def test_a_system_with_no_name_is_refused(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Plan9")

    with pytest.raises(build.BuildError, match="unsupported platform"):
        build.detect_platform()


def test_only_windows_gets_an_extension():
    assert build.executable_name("windows") == "datasemver.exe"
    assert build.executable_name("linux") == "datasemver"
    assert build.executable_name("macos") == "datasemver"


def test_a_missing_pyinstaller_says_how_to_get_it(monkeypatch):
    monkeypatch.setattr(build.shutil, "which", lambda name: None)
    monkeypatch.setattr(build, "_importable", lambda name: False)

    with pytest.raises(build.BuildError, match="pip install"):
        build.require_pyinstaller()


# --- what goes into the bundle ----------------------------------------------------------------


def test_the_rules_file_is_carried_into_the_bundle():
    sources = [source.name for source, _ in build.data_files()]

    assert "default_rules.yaml" in sources


def test_data_sources_are_absolute():
    """PyInstaller resolves a relative --add-data source against --specpath, not the working
    directory, so a relative path here quietly matches nothing and the bundle ships without
    its rules."""
    assert all(source.is_absolute() for source, _ in build.data_files())


def test_data_lands_under_the_path_the_package_reads_it_from():
    """The rules are found with `Path(__file__).with_name(...)`, which under PyInstaller
    resolves inside the unpacked bundle. The layout has to match for that to find anything."""
    destinations = {destination for _, destination in build.data_files()}

    assert "datasemver/rules" in destinations


def test_a_data_pattern_that_matches_nothing_is_an_error(monkeypatch):
    monkeypatch.setattr(build, "DATA_FILES", ("rules/*.nothing",))

    with pytest.raises(build.BuildError, match="no package data matched"):
        build.data_files()


def test_the_entry_script_imports_the_app(tmp_path):
    entry = build.write_entry_script(tmp_path)

    body = entry.read_text(encoding="utf-8")
    assert "from datasemver.cli.main import app" in body
    assert entry.parent == tmp_path


# --- the command handed to PyInstaller --------------------------------------------------------


@pytest.fixture
def recorded(monkeypatch, tmp_path):
    """Capture the PyInstaller command without running it, and fake the binary it makes."""
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def record(command, **kwargs):
        calls.append(command)
        (tmp_path / build.executable_name(build.detect_platform())).write_text("x")
        return Result()

    monkeypatch.setattr(build.subprocess, "run", record)
    return calls, tmp_path


def test_the_source_tree_is_on_the_path(recorded):
    """An editable install resolves through a finder rather than a directory, and PyInstaller
    does not follow it: without this the package is silently left out of its own binary."""
    calls, output = recorded

    build.build(build.detect_platform(), output)

    command = calls[0]
    assert "--paths" in command
    assert command[command.index("--paths") + 1] == str(build.REPO_ROOT)


def test_data_files_use_the_separator_this_platform_expects(recorded):
    """PyInstaller splits --add-data on `:` everywhere but Windows, where it splits on `;`.
    A hard-coded colon puts a drive letter on the wrong side of the split."""
    calls, output = recorded

    build.build(build.detect_platform(), output)

    command = calls[0]
    added = command[command.index("--add-data") + 1]
    assert added.count(os.pathsep) >= 1
    source, destination = added.rsplit(os.pathsep, 1)
    assert Path(source).is_file()
    assert destination == "datasemver/rules"


def test_the_build_is_a_single_file(recorded):
    calls, output = recorded

    build.build(build.detect_platform(), output)

    assert "--onefile" in calls[0]


def test_pyinstaller_runs_under_the_interpreter_that_started_the_script(recorded):
    """`pip install pyinstaller` into one environment and running another's `pyinstaller`
    would freeze the wrong set of libraries."""
    calls, output = recorded

    build.build(build.detect_platform(), output)

    assert calls[0][:3] == [sys.executable, "-m", "PyInstaller"]


def test_a_failed_build_is_reported(monkeypatch, tmp_path):
    class Failed:
        returncode = 1

    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: Failed())

    with pytest.raises(build.BuildError, match="exited with 1"):
        build.build(build.detect_platform(), tmp_path)


def test_a_build_that_produces_nothing_is_reported(monkeypatch, tmp_path):
    class Result:
        returncode = 0

    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: Result())

    with pytest.raises(build.BuildError, match="is not there"):
        build.build(build.detect_platform(), tmp_path)


# --- the archive ------------------------------------------------------------------------------


@pytest.fixture
def fake_binary(tmp_path):
    binary = tmp_path / "datasemver"
    binary.write_text("not really a binary", encoding="utf-8")
    binary.chmod(0o755)
    return binary


def test_a_unix_archive_keeps_the_executable_bit(fake_binary, tmp_path):
    """Without the bit, the download answers "Permission denied" and looks broken."""
    archive = build.package(fake_binary, "linux", tmp_path)

    with tarfile.open(archive) as bundle:
        entry = bundle.getmember("datasemver")
    assert entry.mode & 0o111, "the executable bit did not survive the archive"


def test_a_unix_archive_is_a_tarball(fake_binary, tmp_path):
    archive = build.package(fake_binary, "macos", tmp_path)

    assert archive.suffixes[-2:] == [".tar", ".gz"]
    assert tarfile.is_tarfile(archive)


def test_a_windows_archive_is_a_zip(tmp_path):
    binary = tmp_path / "datasemver.exe"
    binary.write_text("not really a binary", encoding="utf-8")

    archive = build.package(binary, "windows", tmp_path)

    assert archive.suffix == ".zip"
    with zipfile.ZipFile(archive) as bundle:
        assert "datasemver.exe" in bundle.namelist()


def test_the_licence_travels_with_the_binary(fake_binary, tmp_path):
    archive = build.package(fake_binary, "linux", tmp_path)

    with tarfile.open(archive) as bundle:
        assert "LICENSE" in bundle.getnames()


def test_the_archive_name_carries_the_version_and_the_architecture():
    import datasemver

    name = build.archive_name("linux")

    assert name.startswith(f"datasemver-{datasemver.__version__}-linux-")
    assert name.rsplit("-", 1)[-1] == platform.machine().lower()


def test_two_platforms_do_not_produce_the_same_archive_name():
    """A release page holds every platform's archive side by side."""
    assert build.archive_name("linux") != build.archive_name("windows")


# --- the tool itself ---------------------------------------------------------------------------


@pytest.mark.skipif(not build._importable("PyInstaller"), reason="pyinstaller is not installed")
def test_pyinstaller_is_usable_when_it_is_installed():
    """The build dependency is satisfiable in this environment; the build itself runs in CI."""
    build.require_pyinstaller()


# --- the command line ---------------------------------------------------------------------------


def test_the_defaults_build_for_this_platform_into_dist_and_archive_it():
    args = build.parse_args([])

    assert args.platform is None
    assert args.output_dir == build.REPO_ROOT / "dist"
    assert args.archive is True
    assert args.clean is True


def test_the_archive_and_the_cache_can_each_be_turned_off():
    args = build.parse_args(["--no-archive", "--no-clean"])

    assert args.archive is False
    assert args.clean is False


def test_only_the_three_supported_platforms_are_accepted(capsys):
    with pytest.raises(SystemExit):
        build.parse_args(["--platform", "solaris"])


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    """Stand in for the two slow steps so `main` can be driven end to end."""
    binary = tmp_path / "datasemver"
    binary.write_text("x", encoding="utf-8")
    packaged: list[Path] = []

    monkeypatch.setattr(build, "require_pyinstaller", lambda: None)
    monkeypatch.setattr(build, "build", lambda *a, **k: binary)
    monkeypatch.setattr(
        build, "package", lambda *a, **k: packaged.append(binary) or tmp_path / "a.tar.gz"
    )
    return packaged


def test_a_finished_build_reports_success(stubbed, tmp_path, capsys):
    code = build.main(["--output-dir", str(tmp_path)])

    assert code == 0
    assert "built" in capsys.readouterr().out


def test_the_archive_is_skipped_when_it_is_not_wanted(stubbed, tmp_path):
    build.main(["--output-dir", str(tmp_path), "--no-archive"])

    assert stubbed == [], "an archive was written despite --no-archive"


def test_a_build_error_becomes_an_exit_code_and_a_message(monkeypatch, capsys, tmp_path):
    """A traceback here would bury the one line saying what to do about it."""
    monkeypatch.setattr(build, "require_pyinstaller", lambda: None)

    def refuse(*args, **kwargs):
        raise build.BuildError("pyinstaller exited with 1")

    monkeypatch.setattr(build, "build", refuse)

    code = build.main(["--output-dir", str(tmp_path)])

    assert code == 2
    assert "error: pyinstaller exited with 1" in capsys.readouterr().err
