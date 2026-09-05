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

Python 3.10 or newer is required. CI runs the suite on Linux across every supported version
and on macOS and Windows at both ends of the range, because this library reads files, sniffs
line endings and shells out to git, and those differ by platform. `.gitattributes` pins text
files to LF so a Windows checkout does not rewrite the fixtures and leave the suite measuring
the clone. Development dependencies are declared in the `dev` extra
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

The suite is fast and hermetic: no network, no fixtures written outside `tmp_path`, and no
environment read without `monkeypatch.setenv`, which is how the tests for the
`DATASEMVER_CSV_DELIMITER` override keep the rest of the run untouched. Keep it that way.
Dataset fixtures live in `tests/fixtures/` and are shared through the fixtures declared in
`tests/conftest.py`; prefer building small dataframes inline when a test needs a specific
shape, and only add a file fixture when the format itself is under test. The Parquet
fixtures hold the same rows as `old.csv` and `new.csv`, which is what lets the suite assert
that both formats produce identical reports; regenerate them with
`pandas.DataFrame.to_parquet` if the CSV pair ever changes.

## README captures

The terminal images in both READMEs are real runs, exported from the console the CLI prints
through rather than drawn by hand. Regenerate them whenever the CLI output changes, so the
images do not quietly drift from the tool:

```bash
python scripts/capture_cli.py
```

It writes `docs/assets/*.svg` from rich, then rasterises them to the `*.png` the READMEs
link, using whichever of `firefox`, `chromium` or `rsvg-convert` is on PATH. Without one of
those the SVGs are still refreshed and the PNGs are left alone. The images are referenced by
absolute URL and are deliberately kept out of the sdist.

The two dashboard images (`dashboard-report.png`, `dashboard-columns.png`) are taken by hand
in a browser, since a headless capture of a page that renders its report from a fetch is
more machinery than it earns. Retake them from `~/…/clientes_v1.csv` against
`clientes_v2.csv` at version `1.4.2`, which is the comparison the CLI capture already shows,
so both interfaces in the README describe the same diff.

## Checks

Four gates run in CI and all four run locally:

```bash
pytest                 # 190 tests, coverage floor 85%
ruff check .           # lint
ruff format --check .  # formatting
mypy                   # types
```

`ruff format .` writes the changes rather than reporting them. Markdown is excluded from
both ruff commands: the Python blocks inside the READMEs are aligned for reading, not to a
formatter's rules.

Everything the style section below asks for is checked by one of these, which is the point
of having them. Two deliberate exceptions live in `pyproject.toml`: `File(...)` and
`Form(...)` in a parameter default are how FastAPI declares uploads rather than a mutable
default by mistake, and `scripts/capture_cli.py` is left out of coverage because covering a
script that drives a headless browser would mean asserting against a mocked browser.

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

## The site

<https://izanvil.github.io/datasemver/> is served from the `gh-pages` branch, which shares
no history with `main`. The page is a marketing surface and this branch is a Python package;
keeping the composition of one out of the tree of the other is the whole reason for the
split.

```bash
git fetch origin gh-pages
git worktree add ../datasemver-site gh-pages
```

The captures it shows are not copied there. They are referenced from `main` by absolute URL,
the same files the READMEs embed, so the page cannot drift into showing output the
documentation does not. Regenerate them with `python scripts/capture_cli.py` on `main` and
the site picks them up with no second commit.

## Actions and dependencies

Every action is pinned to a commit SHA, with the version it corresponds to in a trailing
comment:

```yaml
uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7
```

A tag is a movable pointer: whoever controls `v7` controls what runs in CI, and the code
that runs there can read the repository and, in the publish workflow, mint a token the
index will accept. A SHA cannot move. Dependabot advances the pins and the comments together every Monday, so
they stay current rather than merely frozen, and it raises the dependency floors in
`pyproject.toml` when an advisory lands against one.

If you add a step, pin it the same way:

```bash
gh api repos/<owner>/<action>/commits/<tag> --jq .sha
```

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

There is no API token to store. Both indexes authenticate the workflow through Trusted
Publishing: the job mints a short-lived OpenID Connect token that says which repository,
which workflow file and which environment it came from, and the index checks that against
what it was told to expect. Nothing long-lived exists to leak, rotate or scope.

Each index is configured once, under **Publishing** in the project settings:

| Field | PyPI | TestPyPI |
| --- | --- | --- |
| Owner | `IzanVil` | `IzanVil` |
| Repository | `datasemver` | `datasemver` |
| Workflow | `publish.yml` | `publish.yml` |
| Environment | `pypi` | `testpypi` |

The environment name is part of what the index verifies, so the `environment:` blocks in
the workflow are load-bearing rather than decorative. `id-token: write` is granted to the
two publish jobs only; the build job stays read-only.

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
