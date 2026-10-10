"""The `requirements/` files mirror the parts of `pyproject.toml` that are meant to match.

`pyproject.toml` is the source of truth for what the package needs; `requirements/` exists so
`pip install -r` reaches the same set without parsing extras. That is a mirror kept by hand,
and the one that matters most is the runtime set: the `pyarrow>=23.0.1` floor is a security
floor, chosen above CVE-2023-47248 and two more, so a `requirements/base.txt` that drifted
below it would reintroduce the hole for everyone who installs that way. These tests fail the
moment a floor is changed in one place and not the other.

`dev` is deliberately not mirrored and is asserted to stay that way: the `dev` extra carries
`sqlalchemy` and `duckdb` so CI exercises the engines, while `requirements/dev.txt` carries
`build` and `twine` for the plain-pip packaging workflow. Equating them would be wrong, so the
test that would is replaced by one pinning that they differ on purpose.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# `tomllib` is the standard library's TOML reader from 3.11 on. The test matrix still carries
# 3.10, where it does not exist and there is nothing to fall back to without adding a
# dependency; the drift this guards is caught on the five newer rows, which is enough.
tomllib = pytest.importorskip("tomllib")

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

# Each requirements file and the pyproject section it is a mirror of. `base.txt` mirrors the
# runtime dependencies; the four extras below mirror their optional-dependency groups exactly.
# `dev` is absent on purpose -- see the module docstring and the test at the bottom.
MIRRORED = {
    "base.txt": PYPROJECT["dependencies"],
    "sql.txt": PYPROJECT["optional-dependencies"]["sql"],
    "duckdb.txt": PYPROJECT["optional-dependencies"]["duckdb"],
    "excel.txt": PYPROJECT["optional-dependencies"]["excel"],
    "web.txt": PYPROJECT["optional-dependencies"]["web"],
}


def _requirements(name: str) -> set[str]:
    """The pinned requirements in a `requirements/` file, dropping `-r` includes and comments."""
    lines = (ROOT / "requirements" / name).read_text(encoding="utf-8").splitlines()
    specs = set()
    for line in lines:
        stripped = line.split("#", 1)[0].strip()
        if not stripped or stripped.startswith(("-r ", "--requirement")):
            continue
        specs.add(stripped)
    return specs


@pytest.mark.parametrize("name", sorted(MIRRORED))
def test_requirements_file_mirrors_pyproject(name: str):
    assert _requirements(name) == set(MIRRORED[name]), (
        f"requirements/{name} has drifted from pyproject.toml; keep the two in step"
    )


def test_dev_requirements_are_not_a_mirror_on_purpose():
    """The one file that is not a mirror, pinned so a future sync does not quietly break it.

    `requirements/dev.txt` is the plain-pip developer set and carries packaging tools the `dev`
    extra leaves out, while the extra carries the engine libraries CI needs. If these ever
    become equal, either the packaging tools left the file or the engines left the extra, and
    both are a regression this names rather than a tidy-up.
    """
    dev_extra = set(PYPROJECT["optional-dependencies"]["dev"])
    dev_file = _requirements("dev.txt")

    assert dev_file != dev_extra
    assert {"build>=1.6.1", "twine>=7.0.0"} <= dev_file, "dev.txt lost its packaging tools"
    assert {"sqlalchemy>=2.0", "duckdb>=1.1"} <= dev_extra, "the dev extra lost an engine"
