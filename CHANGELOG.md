# Changelog

DataSemver versions itself with the vocabulary it applies to datasets: **Major** for
changes that break what consumers already depend on, **Minor** for new capability that
leaves existing contracts intact, **Patch** for fixes that keep the same meaning.

This project follows [Semantic Versioning](https://semver.org).

## [Unreleased]

## [0.2.0] - 2026-09-02

### Minor
- CSV delimiter detection: `,`, `;`, tab and `|` are recognised from the first lines of
  the file, so a semicolon-separated export no longer loads as a single column. A
  candidate only wins if it appears in the header and splits every sampled line into the
  same number of fields, and `.tsv` still forces the tab.
- `DATASEMVER_CSV_DELIMITER` forces a single delimiter and skips the detection, the tab
  included and written as `\t`. It overrides the tab of a `.tsv` too, an empty value means
  unset, and anything longer than one character is an error rather than a silent fallback.

### Patch
- The dashboard lays out its history controls consistently on narrow screens, and the
  comparison header shows dataset file names instead of full paths, with the paths kept in
  the title attribute.
- `pytest --collect-only` no longer reports 0% coverage and a failing total for a run that
  never happened.
- Workflows moved to the action majors that run on Node 24: `checkout@v7`,
  `setup-python@v7`, `github-script@v9`, `upload-artifact@v7`, `download-artifact@v8` and
  `codecov-action@v7`.
- The dashboard tests are collected by the `pytest` console script, not only by
  `python -m pytest`: the repository root reaches `sys.path` through `pythonpath` instead
  of relying on the current directory, which is what broke the test workflow on every
  Python version.
- Every project link pointed at `datamserver`, the repository's name before it was
  renamed. The README badges, the clone snippets and the four URLs in the package metadata
  now name `datasemver`, so the PyPI page no longer leans on a GitHub redirect.

## [0.1.0] - 2026-09-02

### Minor
- Web dashboard: a FastAPI backend that imports the library and a static frontend with no
  build step. Upload two datasets or pick two versions from a directory, and read the
  bump, the classified changes, the column comparison and the changelog in the browser.
  `POST /api/diff`, `GET /api/history`, `GET /api/history/{dataset}/diff` and
  `GET /api/meta`.
- Packaging for PyPI: SPDX license, classifiers, project URLs, a `py.typed` marker so the
  annotations reach type checkers, a `MANIFEST.in` that keeps the sdist to the library,
  and `dev` and `web` extras.
- Release workflow: builds the sdist and the wheel, checks the metadata, refuses a tag
  that disagrees with the version in `pyproject.toml`, installs the wheel in a clean
  environment and publishes to PyPI on a GitHub release.
- Test workflow across Python 3.10 to 3.13, with coverage measured on every run and a
  floor of 85%. The suite grew from 68 to 151 tests at 99% coverage.

### Patch
- `Severity` comparisons against strings fell back to the alphabetical order of `str`,
  which made `bump >= "minor"` false for a major bump. They now compare by impact, and a
  string that is not a severity raises `TypeError` instead of comparing alphabetically.
- Documentation for both installation paths, the release flow and the coverage workflow.

## [0.0.1] - 2026-09-02

First working version.

### Minor
- Compare two versions of a dataset and get the semantic version bump they deserve, with
  the changelog entry that describes them.
- Schema changes: columns added, removed and renamed, type changes split into compatible
  widenings and breaking changes, and nullability shifts.
- Content changes: row counts, cardinality, mean and standard deviation of numeric
  columns, mode and category sets of categorical ones.
- Rename detection from the similarity of both the column name and its values, so
  `user_name` becoming `username` is reported as a rename rather than a removal plus an
  addition.
- Configurable rule engine: severities are lists of rules in YAML, threshold rules such as
  `row_count_decrease_greater_than` pair with a plain counterpart in a lower severity, and
  an unknown rule or severity is an error rather than a silent no-op.
- CSV, JSON (array and lines, nested objects flattened with `.`) and Parquet, whose
  declared schema is trusted as it stands rather than re-inferred.
- CLI built on typer and rich: `datasemver diff` with `--rules`, `--current-version`,
  `--output` and `--json`, plus `datasemver rules` to inspect a rule set.
- GitHub Action that analyses the datasets a pull request touches and posts the suggested
  bump as a comment, rewriting the same comment on every push.

[Unreleased]: https://github.com/IzanVil/datasemver/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/IzanVil/datasemver/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/IzanVil/datasemver/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/IzanVil/datasemver/releases/tag/v0.0.1
