<div align="center">

# DataSemver

**Your data changed. DataSemver tells you whether that is a patch, a minor or a breaking release.**

[![Tests](https://github.com/IzanVil/datasemver/actions/workflows/tests.yml/badge.svg)](https://github.com/IzanVil/datasemver/actions/workflows/tests.yml)
[![Coverage](https://codecov.io/gh/IzanVil/datasemver/branch/main/graph/badge.svg)](https://codecov.io/gh/IzanVil/datasemver)
[![PyPI](https://img.shields.io/pypi/v/datasemver.svg)](https://pypi.org/project/datasemver/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/IzanVil/datasemver/blob/main/LICENSE)

**English** · [Español](https://github.com/IzanVil/datasemver/blob/main/README.es.md)

</div>

DataSemver compares two versions of a CSV, JSON or Parquet dataset, classifies every
difference it finds according to a configurable rule set, and returns the semantic version
bump plus a ready-to-commit changelog entry. It is a CLI first, a Python library second,
and it needs no schema registry, no database and no service running.

<p align="center">
  <img src="https://raw.githubusercontent.com/IzanVil/datasemver/main/docs/assets/cli-diff.png" width="880"
       alt="Terminal showing datasemver diff: a MAJOR bump from 0.0.0 to 1.0.0, a column table marking country added, phone modified and legacy_code removed, a changes table classifying seven changes by severity, and the generated changelog entry.">
</p>

<p align="center">
  <sub><code>datasemver diff tests/fixtures/old.csv tests/fixtures/new.csv</code> — a removed column and an
  <code>int64</code> that became a <code>string</code> make this a breaking release.</sub>
</p>

---

## Table of contents

- [Why](#why)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Demo](#demo)
- [Semantic versioning for data](#semantic-versioning-for-data)
- [Command reference](#command-reference)
- [Configuration: rules in YAML](#configuration-rules-in-yaml)
- [Python API](#python-api)
- [GitHub Action](#github-action)
- [Web dashboard](#web-dashboard)
- [Project structure](#project-structure)
- [Changelog](#changelog)
- [Contributing](#contributing)
- [License](#license)

## Why

Code has SemVer, and data does not. A dropped column, a phone number that turned into a
string, a distribution that quietly shifted: all of them break downstream consumers, and
all of them usually ship as "updated the dataset". DataSemver makes that impact explicit
and reviewable, so a dataset release can be discussed the same way a library release is.

## Installation

From PyPI:

```bash
pip install datasemver
```

As a standalone command, without touching your environment:

```bash
pipx install datasemver
```

From source, for development or to run the dashboard:

```bash
git clone https://github.com/IzanVil/datasemver.git
cd datasemver
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

| Extra | Installs | For |
| --- | --- | --- |
| _(none)_ | `pandas`, `pyarrow`, `pydantic`, `pyyaml`, `typer`, `rich` | The library and the `datasemver` command |
| `dev` | `pytest`, `pytest-cov`, `httpx` | Running the test suite and measuring coverage |
| `web` | `fastapi`, `uvicorn`, `python-multipart` | The [web dashboard](#web-dashboard) |

```bash
pip install "datasemver[web]"
```

Requires Python 3.10 or newer. The package ships typed (`py.typed`), so type checkers see
the annotations of every public function.

## Quick start

```bash
pip install datasemver
datasemver diff old.csv new.csv --current-version 1.4.2
```

That prints the panel, the column comparison and the classified changes shown above, and
exits `0`. Nothing is written unless you ask for it.

<details>
<summary>The same run as selectable text</summary>

```
╭───────────── DataSemver ──────────────╮
│ Suggested bump: MAJOR                 │
│ 0.0.0 -> 1.0.0                        │
│                                       │
│ old: tests/fixtures/old.csv (8 rows)  │
│ new: tests/fixtures/new.csv (10 rows) │
╰───────────────────────────────────────╯
                                    Columns
┏━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ column      ┃ status    ┃ type old ┃ type new ┃ nulls         ┃ cardinality ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ country     │ added     │ -        │ string   │ - -> 0.0%     │ - -> 4      │
│ age         │ modified  │ int64    │ int64    │ 0.0% -> 0.0%  │ 8 -> 10     │
│ email       │ modified  │ string   │ string   │ 25.0% -> 0.0% │ 6 -> 10     │
│ phone       │ modified  │ int64    │ string   │ 0.0% -> 0.0%  │ 8 -> 10     │
│ score       │ modified  │ float64  │ float64  │ 0.0% -> 0.0%  │ 8 -> 10     │
│ legacy_code │ removed   │ string   │ -        │ 0.0% -> -     │ 8 -> -      │
│ id          │ unchanged │ int64    │ int64    │ 0.0% -> 0.0%  │ 8 -> 10     │
│ name        │ unchanged │ string   │ string   │ 0.0% -> 0.0%  │ 8 -> 10     │
└─────────────┴───────────┴──────────┴──────────┴───────────────┴─────────────┘
                                        Changes
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ severity ┃ rule                      ┃ description                                   ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ MAJOR    │ column_removed            │ Column 'legacy_code' was removed              │
│ MAJOR    │ type_changed_incompatible │ Column 'phone' changed type from int64 to     │
│          │                           │ string                                        │
│ MINOR    │ row_count_increased       │ Row count grew from 8 to 10 (+25.00%)         │
│ MINOR    │ column_added              │ Column 'country' was added                    │
│ PATCH    │ nulls_fixed               │ Column 'email' nulls dropped from 25.0% to    │
│          │                           │ 0.0%                                          │
│ PATCH    │ minor_stat_change         │ Column 'age' mean moved from 37.12 to 38.2    │
│          │                           │ (2.90%)                                       │
│ PATCH    │ minor_stat_change         │ Column 'score' mean moved from 72.47 to 71.22 │
│          │                           │ (1.72%)                                       │
└──────────┴───────────────────────────┴───────────────────────────────────────────────┘
```

</details>

Without `--output`, the changelog entry is printed at the end of the run:

```markdown
## [1.0.0] - 2026-09-02

### Major
- Column 'legacy_code' was removed
- Column 'phone' changed type from int64 to string

### Minor
- Row count grew from 8 to 10 (+25.00%)
- Column 'country' was added

### Patch
- Column 'email' nulls dropped from 25.0% to 0.0%
- Column 'age' mean moved from 37.12 to 38.2 (2.90%)
- Column 'score' mean moved from 72.47 to 71.22 (1.72%)
```

Wire it into a release script by reading the bump from the JSON output:

```bash
BUMP=$(datasemver diff old.csv new.csv --json | jq -r '.bump')
datasemver diff old.csv new.csv --current-version "$(cat VERSION)" --output CHANGELOG.md
```

## Demo

A recording of the CLI lives in [`demo.cast`](https://github.com/IzanVil/datasemver/blob/main/demo.cast) and replays locally:

```bash
pip install asciinema
asciinema play demo.cast
```

Re-record it after a change in the CLI output, then upload it to get a shareable player:

```bash
asciinema rec demo.cast --overwrite --cols 90 --rows 40
asciinema upload demo.cast
```

## Semantic versioning for data

The bump is the strongest severity found across all detected changes. What "strongest"
means is entirely defined by the rules file, but the defaults follow the reading below.

| Bump | Meaning for consumers | Default triggers |
| --- | --- | --- |
| **Major** | Existing queries and pipelines can break | Column removed or renamed, incompatible type change (`int64` → `string`), distribution shift of at least 0.5 σ, more than 20% of rows lost, more than 10 points of nulls introduced |
| **Minor** | New information, existing contracts still hold | Column added, rows added, rows removed below the major threshold, new or removed category, cardinality shift, nulls introduced below the major threshold |
| **Patch** | Same meaning, better data | Nulls filled in, small statistical drift, compatible type widening (`int64` → `float64`) |

Changes that no rule covers are still listed in the report as *unclassified* and never
inflate the bump. If nothing matches, the version is left untouched.

What DataSemver looks at:

- **Schema** — added, removed and renamed columns, dtype changes, nullability.
- **Content** — row counts, cardinality, mean and standard deviation of numeric columns,
  mode and category sets of categorical ones.
- **Semantics** — renamed columns, inferred from the similarity of both the column name
  and its values, so `user_name` → `username` is reported as a rename rather than as a
  removal plus an addition.

## Command reference

```bash
datasemver diff OLD NEW [OPTIONS]
datasemver rules [RULES_FILE]
python -m datasemver diff OLD NEW     # equivalent, no installation needed
```

| Option | Short | Description |
| --- | --- | --- |
| `--rules PATH` | `-r` | Rules file replacing the bundled defaults |
| `--current-version TEXT` | `-c` | Version the new dataset is bumped from (default `0.0.0`) |
| `--output PATH` | `-o` | Write the changelog entry to a file, prepending it if it already exists |
| `--json` | | Print the full report as JSON instead of the tables |

Examples:

```bash
datasemver diff old.json new.json --current-version 1.4.2
datasemver diff snapshots/2026-08.parquet snapshots/2026-09.parquet
datasemver diff old.csv new.csv --rules examples/strict_rules.yaml
datasemver diff old.csv new.csv --output CHANGELOG.md
datasemver diff old.csv new.csv --json | jq '.classified[] | {severity, rule: .rule}'
datasemver rules examples/lenient_rules.yaml
```

Formats are detected by extension: `.csv`, `.tsv`, `.json`, `.jsonl`, `.ndjson`, `.parquet`
and `.pq`. The delimiter of a `.csv` is detected from its first lines — comma, semicolon,
tab and pipe are recognised, and a character that only appears inside quoted values does
not win — while `.tsv` always uses the tab. Set `DATASEMVER_CSV_DELIMITER` to skip the
detection and force a single character, the tab included and written as `\t`; it overrides
the tab of a `.tsv` as well, and an empty value means unset. Nested JSON objects and
Parquet structs are flattened with a `.` separator, so `{"user": {"name": "..."}}` is
profiled as the column `user.name`. The command exits with `2` on a missing file, an
unsupported extension, an unreadable dataset or an invalid rules file.

<p align="center">
  <img src="https://raw.githubusercontent.com/IzanVil/datasemver/main/docs/assets/cli-delimiter.png" width="880"
       alt="Terminal showing datasemver diff on two semicolon-delimited CSV files: five columns correctly split into id, cliente, pais, importe and estado, a new canal column, and a MINOR bump from 1.4.2 to 1.5.0.">
</p>

<p align="center">
  <sub>A semicolon-delimited export, where every <code>importe</code> also contains a comma.
  The comma never reaches the header, so the semicolon wins and the file loads as five
  columns instead of one.</sub>
</p>

Types are inferred for the text formats, where a column of `"12"` values is read as
`int64`. Parquet carries its own schema and is trusted as it stands, so a column stored as
a string stays a string even when every value looks numeric. Comparing a CSV against the
Parquet export of the same data is supported and reports the same changes:

```bash
datasemver diff tests/fixtures/old.csv tests/fixtures/new.parquet
```

## Configuration: rules in YAML

Every severity is a list of rules. The engine evaluates `major`, then `minor`, then
`patch`, and the first rule that matches a change assigns its severity:

```yaml
major:
  - column_removed
  - type_changed_incompatible
  - row_count_decrease_greater_than: 20

minor:
  - column_added
  - row_count_decreased

patch:
  - nulls_fixed
  - minor_stat_change
```

Pass it with `--rules custom.yaml` to replace the defaults, and check how it was parsed
with `datasemver rules custom.yaml`, which prints the rule set exactly as the engine
understood it:

<p align="center">
  <img src="https://raw.githubusercontent.com/IzanVil/datasemver/main/docs/assets/cli-rules.png" width="760"
       alt="Terminal showing datasemver rules: the bundled default rule set printed as three colour-coded severity groups, six rules under major, seven under minor and three under patch.">
</p>
 Threshold rules such as
`row_count_decrease_greater_than` pair naturally with their plain counterpart in a lower
severity, which then acts as the fallback. Unknown rule names, unknown severities and
thresholds on rules that do not accept one are rejected with an error instead of being
ignored.

The full catalogue of rules, metrics and thresholds is in [docs/rules.md](https://github.com/IzanVil/datasemver/blob/main/docs/rules.md).
Two ready-made profiles ship in [`examples/`](https://github.com/IzanVil/datasemver/tree/main/examples): `strict_rules.yaml` and
`lenient_rules.yaml`.

## Python API

```python
from datasemver import analyze

report = analyze("old.csv", "new.csv", current_version="1.4.2")

print(report.bump)          # Severity.MAJOR
print(report.next_version)  # 2.0.0

for item in report.classified:
    print(item.severity, item.rule, item.change.description)
```

`analyze_schemas()` takes two already loaded profiles, so dataframes coming from anywhere
can be compared without touching the filesystem:

```python
import pandas as pd
from datasemver.core.analyzer import analyze_schemas
from datasemver.formats.loader import schema_from_frame

report = analyze_schemas(
    schema_from_frame(pd.read_sql(query, engine), "warehouse@yesterday"),
    schema_from_frame(pd.read_sql(query, engine), "warehouse@today"),
)
```

## GitHub Action

[`.github/workflows/datasemver.yml`](https://github.com/IzanVil/datasemver/blob/main/.github/workflows/datasemver.yml) runs DataSemver on
every pull request and posts the result as a comment. It compares each dataset the branch
touches against its version in the base branch, and rewrites the same comment on every push
instead of stacking new ones.

```
## DataSemver report

Suggested bump for this branch: **MAJOR**

| Dataset                | Current | Suggested | Bump  | Changes |
| ---------------------- | ------- | --------- | ----- | ------- |
| `data/customers.csv`   | 1.4.2   | **2.0.0** | MAJOR | 7       |
| `data/users.json`      | 0.0.0   | **0.1.0** | MINOR | 3       |

<details><summary><code>data/customers.csv</code> — 7 classified change(s)</summary>

- **MAJOR** (`column_removed`): Column 'legacy_code' was removed
- **MAJOR** (`type_changed_incompatible`): Column 'phone' changed type from int64 to string
- **MINOR** (`row_count_increased`): Row count grew from 8 to 10 (+25.00%)
- … and 4 more

</details>
```

The work happens in [`scripts/run_datasemver_on_pr.py`](https://github.com/IzanVil/datasemver/blob/main/scripts/run_datasemver_on_pr.py),
so the workflow stays a thin wrapper and the same analysis can be run by hand:

```bash
python scripts/run_datasemver_on_pr.py --base-ref origin/main --output report.md
```

| Option | Description |
| --- | --- |
| `--base-ref` | Ref holding the previous version of each dataset (default `origin/main`) |
| `--head-ref` | Ref to compare against the base; defaults to the working tree |
| `--paths` | Analyse these datasets instead of detecting the changed ones |
| `--rules` | Rules file passed through to `datasemver diff` |
| `--default-version` | Version assumed when a dataset has no sidecar file |
| `--top-changes` | Changes listed per dataset (default 5) |
| `--output` | Write the Markdown report to this file |

It exposes `has_report`, `max_bump` and `dataset_count` as step outputs, writes the report
to the job summary, and always exits `0`: a branch with no dataset changes, a dataset added
for the first time, an unreadable file or a missing base ref are reported rather than
failing the job.

### Dataset versions

The current version of a dataset is read from a sidecar file committed next to it, so each
dataset carries its own version:

```
data/customers.csv
data/customers.csv.version   # contains 1.4.2
```

Without a sidecar the analysis starts from `--default-version` (`0.0.0`). Bumping is
deliberate: the comment tells you the version the dataset deserves, and you write it into
the sidecar in the same pull request.

### Using it in another repository

Copy both files into the target repository and install DataSemver from PyPI instead of the
local checkout:

```yaml
name: DataSemver

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  analyse:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install datasemver
      - id: datasemver
        run: |
          python scripts/run_datasemver_on_pr.py \
            --base-ref "origin/${{ github.base_ref }}" \
            --rules .datasemver/rules.yaml \
            --output "${{ runner.temp }}/report.md"
      - if: steps.datasemver.outputs.has_report == 'true'
        uses: actions/github-script@v7
        env:
          REPORT_PATH: ${{ runner.temp }}/report.md
        with:
          script: |
            const fs = require('fs');
            const body = fs.readFileSync(process.env.REPORT_PATH, 'utf8');
            const { owner, repo } = context.repo;
            await github.rest.issues.createComment({
              owner,
              repo,
              issue_number: context.issue.number,
              body,
            });
```

`fetch-depth: 0` is required: without the full history the base version of the dataset is
not in the clone. The default `GITHUB_TOKEN` is enough as long as the job declares
`pull-requests: write`.

Two limits worth knowing. Pull requests opened from a fork get a read-only token, so the
comment step is skipped for them; the report is still in the job summary. And a dataset
large enough to be stored in Git LFS needs `lfs: true` on the checkout step, otherwise the
base version is a pointer file rather than data.

## Web dashboard

A FastAPI backend and a dependency-free frontend live in [`datasemver_web/`](https://github.com/IzanVil/datasemver/tree/main/datasemver_web).
Upload two versions of a dataset, or pick two versions from a directory, and read the
bump, the classified changes, the column comparison and the changelog entry in the
browser. It ships in the package, so it needs no checkout:

```bash
pip install "datasemver[web]"
uvicorn datasemver_web.backend.main:app
```

From a clone, `pip install -r requirements-web.txt` and add `--reload`.

Then open <http://127.0.0.1:8000>; the backend serves the frontend, so that is the only
command. The history view scans `./datasets/` by default, grouping files named
`customers_v1.csv`, `customers_v2.csv` and so on.

The dashboard is a client of the library, not a fork of it: it calls `analyze()` and
returns the same report the CLI prints with `--json`.

```bash
curl -X POST http://127.0.0.1:8000/api/diff \
  -F "old=@tests/fixtures/old.csv" \
  -F "new=@tests/fixtures/new.csv" \
  -F "current_version=1.4.2"
```

Endpoints, configuration and the dataset naming convention are documented in
[datasemver_web/README.md](https://github.com/IzanVil/datasemver/blob/main/datasemver_web/README.md).

## Project structure

```
datasemver/
├── core/
│   ├── analyzer.py       load, diff, classify, version
│   ├── changelog.py      changelog rendering and file writing
│   ├── differ.py         comparison of two dataset profiles
│   └── models.py         pydantic models shared across the pipeline
├── formats/
│   ├── loader.py         CSV, JSON and Parquet readers
│   └── utils.py          type inference and column profiling
├── rules/
│   ├── engine.py         rule parsing and severity assignment
│   └── default_rules.yaml
├── utils/
│   ├── similarity.py     rename detection heuristics
│   └── version.py        semantic version arithmetic
└── cli/main.py           typer entry point

CHANGELOG.md              the project's own versions
docs/rules.md             rule catalogue
examples/                 alternative rule profiles
scripts/                  CI helper that analyses the datasets a branch touches
web/                      FastAPI backend and static frontend for the dashboard
datasets/                 sample versioned datasets for the dashboard history view
.github/workflows/        pull request analysis, the test matrix and the release
tests/                    pytest suite and dataset fixtures
demo.cast                 asciinema recording used in the demo above
```

## Changelog

Every released version is described in [CHANGELOG.md](https://github.com/IzanVil/datasemver/blob/main/CHANGELOG.md), which uses the same
vocabulary the tool applies to datasets: **Major** for changes that break what consumers
already depend on, **Minor** for new capability that leaves existing contracts intact,
**Patch** for fixes that keep the same meaning.

## Contributing

Issues and pull requests are welcome. Start with [CONTRIBUTING.md](https://github.com/IzanVil/datasemver/blob/main/CONTRIBUTING.md) for the
development setup, the test workflow and the style expected in a patch. Everyone taking
part is expected to follow the [Code of Conduct](https://github.com/IzanVil/datasemver/blob/main/CODE_OF_CONDUCT.md).

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT. See [LICENSE](https://github.com/IzanVil/datasemver/blob/main/LICENSE).
