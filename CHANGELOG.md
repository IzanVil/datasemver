# Changelog

DataSemver versions itself with the vocabulary it applies to datasets: **Major** for
changes that break what consumers already depend on, **Minor** for new capability that
leaves existing contracts intact, **Patch** for fixes that keep the same meaning.

This project follows [Semantic Versioning](https://semver.org).

## [Unreleased]

### Patch
- Both READMEs show the dashboard. It was the only interface the project described entirely
  on trust: the bump and the classified changes, then the column table and the changelog
  entry with its copy button. The comparison is the one the CLI capture already uses, so the
  two interfaces in the page describe the same diff rather than two unrelated ones. Taken by
  hand — a headless capture of a page that renders its report from a fetch is more machinery
  than it earns — and `CONTRIBUTING` says how to retake them.

## [0.2.5] - 2026-09-05

### Minor
- The dashboard ships in the distribution. `pip install "datasemver[web]"` installed
  fastapi, uvicorn and python-multipart and then no dashboard: the README's table said that
  extra was "for the web dashboard", but `packages.find` only ever collected `datasemver*`
  and `MANIFEST.in` pruned `web`, so `uvicorn web.backend.main:app` answered
  `ModuleNotFoundError: No module named 'web'`. It had been that way since 0.1.0.
- The package is `datasemver_web`, not `web`. A distribution that claims a name that
  generic in `site-packages` collides with any other project that has a module called
  `web`. Run it as `uvicorn datasemver_web.backend.main:app`.
- The frontend is declared as package data. It is HTML, CSS and JavaScript, so a wheel
  would have carried the backend and served nothing.
- Python 3.14 is tested and declared. The suite already passed on it, and every runtime
  dependency resolves there: pandas and pyarrow ship cp314 wheels, and pydantic is a
  universal wheel over a `pydantic-core` that has one. The matrix, the classifiers and the
  badge in all three READMEs say 3.10 to 3.14 now.

### Patch
- Every action in every workflow is pinned to a commit SHA rather than a version tag, all
  seventeen references. A tag is a movable pointer, so `actions/checkout@v7` meant whoever
  controls that tag decides what runs in CI — where the code can read the repository and,
  in the publish workflow, reach a PyPI token. The version each SHA corresponds to stays in
  a trailing comment so the file is still readable.
- Dependabot watches both the actions and the Python dependencies, weekly. The floors in
  `pyproject.toml` were raised by hand once, after an audit found a critical advisory under
  `pyarrow>=10`; doing that by hand neither scales nor repeats, and a pinned SHA is also a
  frozen SHA, so something has to advance it.
- `scripts/run_datasemver_on_pr.py` has tests, and coverage measures it. It is 195
  statements holding the whole of the GitHub Action, it was the most externally visible
  code in the project, and it had none: the 99% figure was measured over `datasemver` and
  `web` only, so it reported nothing about the part users copy into their own repositories.
  Thirty-two tests now run it against a real git repository built in `tmp_path` — refs,
  blobs, sidecar versions and a genuine `datasemver diff` subprocess — rather than against
  a mocked `git`, which would have hidden exactly the behaviours worth pinning. It sits at
  98%, and the project total is 99% with it included.
- Two of those behaviours turned out to be undocumented and are now fixed in tests: a
  deleted dataset is never detected, because `--diff-filter=ACMRT` excludes deletions, and
  the sidecar version is read from the base ref rather than from the branch.
- A `Quality` workflow runs ruff and mypy. `CONTRIBUTING` asked for PEP 8, a 100 character
  line and a type hint on every signature, and nothing checked any of it; the package
  advertised `py.typed` with nothing verifying the annotations it promises. Both claims are
  now enforced on every push and pull request.
- Fixing what those found: seven generators in `core/differ.py` and one context manager in
  the dashboard had no return annotation, `git()` in the CI helper returned `str | bytes`
  with callers assuming one or the other — it is overloaded on the `text` flag now, so the
  five call sites type-check — imports in `tests/conftest.py` sat below a function
  definition, and a handful of lines ran past the column limit the guide sets.

## [0.2.4] - 2026-09-04

### Patch
- The PyPI project page is built from its own `README.pypi.md` and no longer depends on the
  repository being public. `README.md` embeds terminal captures and links to `LICENSE`,
  `docs/rules.md` and the Spanish edition, all served by GitHub; whenever the repository is
  private those answer 404, and the package page — which stays public whatever the
  repository does — showed broken images and dead links with no way to know anyone was
  looking. The captures and the cross-links stay in `README.md`, where GitHub renders them.
- The `Documentation` project URL is gone. It deep-linked to a file in the repository, so
  it was the one sidebar entry that promised documentation and delivered a 404 whenever the
  repository was private. What it pointed at is now the project page itself. `Homepage`,
  `Repository` and `Issues` stay: a package should say where its source lives.

## [0.2.3] - 2026-09-04

Security release. Anyone on an earlier version should upgrade: the floors those releases
declare still resolve to a pyarrow carrying CVE-2023-47248.

### Patch
- Every dependency floor that admitted a known-vulnerable version has been raised; no
  version any of them now allows carries a published advisory. `pyarrow>=10` admitted
  CVE-2023-47248, rated critical: arbitrary code execution while reading a malicious
  Parquet file. Reading data nobody vouched for is the point of this library, so the floor
  is now `>=23.0.1`, the first release clear of that, of CVE-2024-52338 and of
  CVE-2026-25087, and one that still ships wheels for every supported Python.
  `python-multipart>=0.0.9` admitted eight advisories including CVE-2026-24486, an
  arbitrary file write, and four denial-of-service issues; it is the parser every dashboard
  upload passes through, and the floor is now `>=0.0.31`. Also `pydantic>=2.4`
  (CVE-2024-3772, ReDoS), `pytest>=9.0.3` (CVE-2025-71176) and the build requirement
  `setuptools>=83`, where CVE-2026-59890 let a `MANIFEST.in` exclusion be bypassed in an
  sdist — this package uses those exclusions to decide what ships. The requirements files
  carry the same floors.
- The dashboard's upload limit is applied while the body is written rather than once it has
  landed. It was advisory before: a 14 MB upload against a 1 MB limit wrote all 14 MB to
  disk and was then rejected, so the cap bounded what was accepted but not what a request
  could cost. A rejected upload now writes one byte past the limit and is deleted.
- The pull request workflow passes event values to the shell through the environment
  instead of `${{ }}` interpolation, which pastes them in before bash parses the script.
- `SECURITY.md`: how to report privately, what parsing a dataset does and does not do, and
  why the dashboard belongs on the loopback interface.

## [0.2.2] - 2026-09-04

### Patch
- Both READMEs open with a real terminal capture of `datasemver diff` instead of asking the
  reader to imagine the output, and carry two more: the semicolon-delimited CSV that proves
  the delimiter detection, and `datasemver rules` printing the parsed rule set. The full run
  is still there as selectable text, folded into a `<details>` so it stays greppable.
- `scripts/capture_cli.py` regenerates those images from real CLI runs, by swapping the
  console the CLI prints through for a recording one. They cannot drift into showing output
  the tool no longer produces without someone editing them by hand.
- The sdist now carries `README.es.md`. The capture PNGs stay out of it, since the READMEs
  reference them by absolute URL.
- The repository is public, which is what the absolute links added in 0.2.1 assumed. While
  it was private every one of them, and the badges, answered 404 to anyone but the owner —
  including on the PyPI page for 0.2.0.

## [0.2.1] - 2026-09-03

### Patch
- The PyPI project page is built from `README.md`, where every link was relative and
  therefore dead once rendered off GitHub: `LICENSE`, `CONTRIBUTING.md`, `docs/rules.md`,
  `web/README.md` and nine others resolved against `pypi.org` and found nothing. All of
  them are absolute now, which works on both sites.
- The demo section led with an asciinema badge pointing at the `000000` placeholder, a
  guaranteed 404 image at the top of the page every visitor sees first. It is gone until
  there is a cast to point at; the instructions to record and upload one remain.
- Publishing a version that is already on the index is a no-op rather than a failed job.
  Re-running the workflow after a successful upload used to fail on `400 File already
  exists`, which reads as a broken release when nothing is wrong.
- Spanish README in `README.es.md`, a full translation kept section for section with the
  English one so a link into either has a counterpart in the other. Recorded CLI output,
  rule identifiers, YAML and workflows stay untranslated, and a link that still leads to
  English-only material says so.
- Both READMEs corrected where they had drifted: the `dev` extra installs `pytest-cov`,
  `.github/workflows/` holds three workflows rather than one, and the changelog is its own
  section instead of a line under Contributing.

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

[Unreleased]: https://github.com/IzanVil/datasemver/compare/v0.2.5...HEAD
[0.2.5]: https://github.com/IzanVil/datasemver/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/IzanVil/datasemver/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/IzanVil/datasemver/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/IzanVil/datasemver/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/IzanVil/datasemver/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/IzanVil/datasemver/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/IzanVil/datasemver/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/IzanVil/datasemver/releases/tag/v0.0.1
