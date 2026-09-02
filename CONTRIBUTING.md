# Contributing to DataSemver

Thanks for taking the time to help. This document covers how to get the project running
locally, what a good patch looks like, and how changes get reviewed. Everyone taking part
is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

```bash
git clone https://github.com/IzanVil/datasemver.git
cd datasemver
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The editable install puts the `datasemver` command on your PATH, so a change in the source
tree is picked up on the next run. Verify the setup:

```bash
datasemver diff tests/fixtures/old.csv tests/fixtures/new.csv
pytest
```

Python 3.10 or newer is required. Development dependencies are declared in the `dev` extra
of `pyproject.toml`; `requirements.txt` is kept for the plain `pip install -r` workflow.

## Running the tests

```bash
pytest                      # whole suite
pytest tests/test_rules.py  # a single module
pytest -k rename -v         # a single behaviour
pytest -q --tb=short        # quieter output while iterating
```

Coverage runs by default: `pytest` measures `datasemver` and `web`, prints the missing
lines and writes `coverage.xml`. The run fails below 85%; it currently sits above 99%.

```bash
pytest --cov-report=html    # browsable report in htmlcov/
pytest --no-cov             # skip the measurement while iterating
pytest -m "not web"         # skip the dashboard tests
```

The dashboard tests import `web`, which is not an installed package; `pythonpath = ["."]`
in `pyproject.toml` puts the repository root on the path so both `pytest` and
`python -m pytest` find it.

The suite is fast and hermetic: no network, no fixtures written outside `tmp_path`. Keep it
that way. Dataset fixtures live in `tests/fixtures/` and are shared through the fixtures
declared in `tests/conftest.py`; prefer building small dataframes inline when a test needs
a specific shape, and only add a file fixture when the format itself is under test. The
Parquet fixtures hold the same rows as `old.csv` and `new.csv`, which is what lets the
suite assert that both formats produce identical reports; regenerate them with
`pandas.DataFrame.to_parquet` if the CSV pair ever changes.

## Code style

- **PEP 8**, 100 character lines, four space indentation.
- **Type hints on every function signature**, including tests where they clarify intent.
  Modules use `from __future__ import annotations`.
- **Docstrings on public functions, classes and modules**, one sentence in the imperative
  mood. No inline commentary restating what the code says; if a block needs explaining,
  the explanation belongs in the docstring or in a better name.
- **Models are pydantic**. Anything that crosses a module boundary or reaches the JSON
  output is declared in `datasemver/core/models.py`.
- **No new runtime dependencies** without discussing it in an issue first. The current set
  is `pandas`, `pyarrow`, `pydantic`, `pyyaml`, `typer` and `rich`.
- Private helpers are prefixed with `_` and stay at the bottom of the module.

If you use formatters or linters, `ruff format` and `ruff check` with a 100 character line
length match the existing code. They are not enforced in CI yet.

## Adding a new detection

Most contributions fall into this shape. The path through the code is:

1. Add the case to `ChangeType` in `datasemver/core/models.py`.
2. Emit the `Change` from `datasemver/core/differ.py`, including the metrics a threshold
   rule would need. Add a threshold to `DiffConfig` rather than hardcoding a number.
3. Map it to a severity in `datasemver/rules/default_rules.yaml`, and register the metric
   in `THRESHOLD_RULES` in `datasemver/rules/engine.py` if it takes a limit.
4. Document it in `docs/rules.md`.
5. Cover it in `tests/test_differ.py` and, if it changes the resulting bump, in
   `tests/test_analyzer.py`.

Detections should be quiet by default: a rule that fires on every dataset is noise, and
noise is what makes the bump untrustworthy.

## Releasing

Releases are built and published by
[`.github/workflows/publish.yml`](.github/workflows/publish.yml). The flow is:

1. Bump the version in `pyproject.toml` and `datasemver/__init__.py`; both must match, and
   move the `Unreleased` section of `CHANGELOG.md` under the new version.
2. Commit, then tag: `git tag -a v0.1.0 -m "DataSemver 0.1.0"` and push the tag.
3. Publish a GitHub release pointing at that tag. The workflow builds the sdist and the
   wheel, checks the metadata with `twine`, refuses to continue when the tag and the
   version in `pyproject.toml` disagree, installs the wheel in a clean environment to
   confirm the `datasemver` command works, and uploads to PyPI.

Running it by hand from the Actions tab publishes to TestPyPI by default, and to PyPI when
the `pypi` target is chosen.

The workflow expects two repository secrets, `PYPI_API_TOKEN` and `TEST_PYPI_API_TOKEN`,
and two environments named `pypi` and `testpypi` to attach them to. Scope each token to
the `datasemver` project once it exists on the index.

Building locally, which is worth doing before tagging:

```bash
pip install build twine
python -m build
python -m twine check dist/*

python -m venv /tmp/verify
/tmp/verify/bin/pip install dist/datasemver-*.whl
/tmp/verify/bin/datasemver --help
```

`MANIFEST.in` decides what lands in the sdist: the package, its bundled rules, the docs,
the example rule profiles and the test suite. The dashboard under `web/`, the sample
`datasets/` and the CI helper in `scripts/` are deliberately left out, since they are part
of the repository rather than of the library.

## Reporting issues

Open an issue with the [bug report](.github/ISSUE_TEMPLATE/bug_report.md) or
[feature request](.github/ISSUE_TEMPLATE/feature_request.md) template. For a bug, the most
useful report contains:

- The exact command, including the flags.
- The bump you got and the bump you expected.
- A minimal pair of datasets that reproduces it, or the `--json` output with anything
  sensitive removed.
- Versions: `datasemver --help` works, `python --version`, `pip show pandas pydantic`.

Never attach real production data. A handful of synthetic rows that shows the same shape is
both safer and easier to debug.

## Pull requests

1. Fork the repository and branch from `main`, e.g. `feat/detect-primary-key-change`.
2. Keep the change focused. Unrelated refactors belong in their own pull request.
3. Add tests next to the module you touched, and update the documentation the change
   affects (`README.md`, `docs/rules.md`).
4. Run `pytest` before pushing. A red suite will not be reviewed.
5. Write commit messages in the imperative mood: `add rename detection for numeric
   columns`, not `added` or `adds`.
6. Fill in the [pull request template](.github/PULL_REQUEST_TEMPLATE.md), and say
   explicitly whether the change alters the bump produced for an existing dataset pair.

Review is usually a couple of rounds of comments. Anything that changes the classification
of existing data is a breaking change for users and will be scrutinised accordingly, so
motivate it in the description.
