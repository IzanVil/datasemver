#!/usr/bin/env python3
"""Build a standalone `datasemver` executable with PyInstaller.

The result is one file that carries its own Python, so it runs on a machine with no Python
and no pip:

    python scripts/build_executables.py

PyInstaller cannot cross-compile. It freezes the interpreter it is running under, together
with the libraries installed beside it, so a Windows executable can only be built on Windows
and a macOS one on macOS. `--platform` therefore names the platform you expect to be on and
fails when you are not, which is the only useful thing it can do; the release workflow gets
its three binaries from three runners rather than from three flags.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "datasemver"

# The names this script uses for platforms, and what `platform.system()` calls each of them.
PLATFORMS = {"linux": "Linux", "macos": "Darwin", "windows": "Windows"}

# Files the package needs at runtime that are not Python. The rules are read through
# `Path(__file__).with_name(...)`, which under PyInstaller resolves inside the unpacked
# bundle, so laying them out under the same relative path is all that is needed.
DATA_FILES = ("rules/*.yaml",)

# The extras the binary carries, and the import that proves each one is there. Declared here
# rather than left to whatever the build machine happens to have installed: PyInstaller
# freezes the environment it runs in, so without this the same script produces a different
# binary on two machines, both called `datasemver`, and only one of them reads a workbook.
#
# Someone running the binary cannot add an extra later -- there is no environment to add it
# to -- so what goes in is what they will ever have. `sql` and `excel` are in because they
# are small and there is no other way to get them.
BUNDLED_EXTRAS = {"sql": ("sqlalchemy",), "excel": ("openpyxl",)}

# Kept out, and kept out by name so that a machine with them installed still produces the
# published binary rather than a larger private one. `duckdb` costs 22 MB of the download --
# 110 MB against 132 -- for an engine that returns the answers the default one already
# returns, only cheaper; and the dashboard is a server rather than a command.
EXCLUDED_MODULES = ("duckdb", "fastapi", "uvicorn", "starlette", "pytest")

EXECUTABLE_MODE = 0o755


class BuildError(RuntimeError):
    """Raised when the build cannot start or does not finish."""


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        require_pyinstaller()
        require_extras()
        target = resolve_platform(args.platform)
        binary = build(target, args.output_dir, clean=args.clean)
        print(f"\nbuilt {binary} ({binary.stat().st_size / 1_000_000:.0f} MB)")
        verify(binary)
        if args.archive:
            print(f"packaged {package(binary, target, args.output_dir)}")
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform",
        choices=sorted(PLATFORMS),
        help="Platform to build for. PyInstaller cannot cross-compile, so this checks that "
        "you are on that platform rather than targeting it. Defaults to the one you are on.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "dist",
        help="Where to write the executable and the archive (default: dist/).",
    )
    parser.add_argument(
        "--no-archive",
        dest="archive",
        action="store_false",
        help="Leave the bare executable without wrapping it in a tar.gz or zip.",
    )
    parser.add_argument(
        "--no-clean",
        dest="clean",
        action="store_false",
        help="Reuse PyInstaller's cache instead of starting from scratch.",
    )
    return parser.parse_args(argv)


def require_pyinstaller() -> None:
    """Fail before doing any work when the one build dependency is absent."""
    if shutil.which("pyinstaller") is None and not _importable("PyInstaller"):
        raise BuildError(
            'pyinstaller is not installed: pip install "pyinstaller>=6.0", '
            'or install the build extra with pip install -e ".[exe]"'
        )


def require_extras() -> None:
    """Refuse to build without the extras the binary is supposed to carry.

    Missing, they do not fail the build -- they fail a reader months later, holding a file
    that answers "reading a workbook is not part of the standalone executable" when it was
    supposed to be.
    """
    missing = sorted(
        extra
        for extra, imports in BUNDLED_EXTRAS.items()
        if not all(_importable(module) for module in imports)
    )
    if missing:
        wanted = ",".join(sorted(BUNDLED_EXTRAS))
        raise BuildError(
            f"the binary is declared to carry {wanted}, and {', '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} not installed here. "
            f'Install them first: pip install ".[{wanted},exe]"'
        )


def verify(binary: Path) -> None:
    """Run the binary that was just built, over one file of every kind it claims to read.

    A build that succeeds and a binary that works are different things, and the gap between
    them is where a missing extra or an unbundled data file hides. Everything here is written
    to a temporary directory and read straight back.
    """
    import tempfile

    print("verifying the binary")
    with tempfile.TemporaryDirectory() as directory:
        fixtures = _write_fixtures(Path(directory))
        checks: list[tuple[str, list[str]]] = [
            ("--help", ["--help"]),
            ("bundled rules", ["rules"]),
            ("csv", ["diff", fixtures["old.csv"], fixtures["new.csv"], "--json"]),
            ("parquet", ["diff", fixtures["old.parquet"], fixtures["new.parquet"], "--json"]),
            ("sqlite", ["diff", fixtures["sqlite_old"], fixtures["sqlite_new"], "--json"]),
            ("workbook", ["diff", fixtures["xlsx_q1"], fixtures["xlsx_q2"], "--json"]),
        ]
        for label, arguments in checks:
            result = subprocess.run(
                [str(binary), *arguments], capture_output=True, text=True, check=False
            )
            if result.returncode != 0:
                raise BuildError(
                    f"the binary cannot do {label}: exited {result.returncode}\n"
                    f"{result.stdout[-400:]}{result.stderr[-400:]}"
                )
            print(f"  {label} ok")

        # The engines that were deliberately left out have to refuse rather than crash, and
        # say where the reader can get them.
        refused = subprocess.run(
            [str(binary), "diff", fixtures["old.csv"], fixtures["new.csv"], "--engine", "duckdb"],
            capture_output=True,
            text=True,
            check=False,
        )
        if refused.returncode == 0 or "standalone executable" not in (
            refused.stdout + refused.stderr
        ):
            raise BuildError(
                "the binary was expected to refuse --engine duckdb and explain why; "
                f"it exited {refused.returncode}"
            )
        print("  duckdb refused with the frozen message, as declared")


def _write_fixtures(directory: Path) -> dict[str, str]:
    """One small dataset per format the binary is checked against."""
    import sqlite3

    import pandas as pd

    old = pd.DataFrame({"id": [1, 2, 3], "city": ["a", "b", "c"], "n": [1.0, 2.0, 3.0]})
    new = pd.DataFrame(
        {"id": [1, 2, 3, 4], "city": ["a", "b", "c", "d"], "n": [1.0, 2.0, 3.0, 9.0]}
    )

    paths = {}
    for label, frame in (("old", old), ("new", new)):
        csv = directory / f"{label}.csv"
        parquet = directory / f"{label}.parquet"
        frame.to_csv(csv, index=False)
        frame.to_parquet(parquet, index=False)
        paths[f"{label}.csv"] = str(csv)
        paths[f"{label}.parquet"] = str(parquet)

    database = directory / "check.db"
    with sqlite3.connect(database) as connection:
        old.to_sql("v1", connection, index=False)
        new.to_sql("v2", connection, index=False)
    paths["sqlite_old"] = f"sqlite:///{database}#v1"
    paths["sqlite_new"] = f"sqlite:///{database}#v2"

    workbook = directory / "check.xlsx"
    with pd.ExcelWriter(workbook) as writer:
        old.to_excel(writer, sheet_name="Q1", index=False)
        new.to_excel(writer, sheet_name="Q2", index=False)
    paths["xlsx_q1"] = f"{workbook}#Q1"
    paths["xlsx_q2"] = f"{workbook}#Q2"
    return paths


def _importable(name: str) -> bool:
    from importlib.util import find_spec

    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):  # pragma: no cover - a broken install, not a missing one
        return False


def resolve_platform(requested: str | None) -> str:
    """The platform being built for, refusing a request that the host cannot satisfy."""
    running = detect_platform()
    if requested is None:
        return running
    if requested != running:
        raise BuildError(
            f"cannot build for {requested} on {running}: PyInstaller freezes the interpreter "
            f"it runs under and cannot cross-compile. Build on a {requested} machine, or let "
            f"the release workflow do it on a {requested} runner."
        )
    return requested


def detect_platform() -> str:
    system = platform.system()
    for name, expected in PLATFORMS.items():
        if system == expected:
            return name
    raise BuildError(f"unsupported platform: {system or 'unknown'}")


def build(target: str, output_dir: Path, clean: bool = True) -> Path:
    """Run PyInstaller and return the executable it produced."""
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / ".pyinstaller"
    entry = write_entry_script(work_dir)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "datasemver",
        "--noconfirm",
        "--distpath",
        str(output_dir),
        "--workpath",
        str(work_dir / "build"),
        "--specpath",
        str(work_dir),
        # An editable install is invisible to PyInstaller's import graph: it resolves imports
        # through a finder rather than a directory, and the package silently does not make it
        # into the bundle. Naming the source tree makes a checkout build like an install does.
        "--paths",
        str(REPO_ROOT),
    ]
    if clean:
        command.append("--clean")
    # Excluded by name, so that a machine which happens to have them installed still builds
    # the binary that ships rather than a larger private one.
    for module in EXCLUDED_MODULES:
        command += ["--exclude-module", module]
    for source, destination in data_files():
        command += ["--add-data", f"{source}{os.pathsep}{destination}"]
    command.append(str(entry))

    print(f"building for {target} with {Path(sys.executable).name}")
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        raise BuildError(f"pyinstaller exited with {result.returncode}")

    binary = output_dir / executable_name(target)
    if not binary.is_file():
        raise BuildError(f"pyinstaller reported success but {binary} is not there")
    if target != "windows":
        binary.chmod(EXECUTABLE_MODE)
    return binary


def write_entry_script(work_dir: Path) -> Path:
    """The script PyInstaller freezes.

    A generated file rather than `datasemver/__main__.py`: PyInstaller treats the entry
    script as a top-level module, and handing it a file that lives inside the package makes
    that package importable under two names.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    entry = work_dir / "datasemver_entry.py"
    entry.write_text(
        '"""Generated by scripts/build_executables.py; not part of the package."""\n\n'
        "from datasemver.cli.main import app\n\n"
        'if __name__ == "__main__":\n'
        "    app()\n",
        encoding="utf-8",
    )
    return entry


def data_files() -> list[tuple[Path, str]]:
    """The non-Python files to lay into the bundle, as absolute source and relative target.

    Absolute on the way in because PyInstaller resolves a relative `--add-data` source
    against `--specpath` rather than the working directory, which silently finds nothing.
    """
    found: list[tuple[Path, str]] = []
    for pattern in DATA_FILES:
        matches = sorted(PACKAGE.glob(pattern))
        if not matches:
            raise BuildError(f"no package data matched '{pattern}' under {PACKAGE}")
        for match in matches:
            destination = match.parent.relative_to(REPO_ROOT).as_posix()
            found.append((match.resolve(), destination))
    return found


def executable_name(target: str) -> str:
    return "datasemver.exe" if target == "windows" else "datasemver"


def archive_name(target: str) -> str:
    """A name carrying the version and the architecture, because a release holds several."""
    from datasemver import __version__

    machine = platform.machine().lower() or "unknown"
    return f"datasemver-{__version__}-{target}-{machine}"


def package(binary: Path, target: str, output_dir: Path) -> Path:
    """Wrap the executable, and the licence it ships under, for a release page."""
    stem = archive_name(target)
    extras = [path for path in (REPO_ROOT / "LICENSE", REPO_ROOT / "README.md") if path.is_file()]

    if target == "windows":
        destination = output_dir / f"{stem}.zip"
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(binary, binary.name)
            for path in extras:
                bundle.write(path, path.name)
        return destination

    destination = output_dir / f"{stem}.tar.gz"
    with tarfile.open(destination, "w:gz") as bundle:
        bundle.add(binary, binary.name, filter=_executable)
        for path in extras:
            bundle.add(path, path.name)
    return destination


def _executable(entry: tarfile.TarInfo) -> tarfile.TarInfo:
    """Keep the executable bit, which is the difference between a download that runs and one
    that answers "Permission denied"."""
    entry.mode = EXECUTABLE_MODE
    return entry


if __name__ == "__main__":
    raise SystemExit(main())
