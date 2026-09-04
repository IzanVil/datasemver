# DataSemver

[![PyPI](https://img.shields.io/pypi/v/datasemver.svg)](https://pypi.org/project/datasemver/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

**Your data changed. DataSemver tells you whether that is a patch, a minor or a breaking release.**

DataSemver compares two versions of a CSV, JSON or Parquet dataset, classifies every
difference it finds against a configurable rule set, and returns the semantic version bump
plus a ready-to-commit changelog entry. It is a CLI first and a Python library second, and
it needs no schema registry, no database and no service running.

## Install

```bash
pip install datasemver              # library and CLI
pip install "datasemver[web]"       # adds the dashboard
pipx install datasemver             # standalone command
```

Python 3.10 or newer. The package ships typed, so `py.typed` annotations reach type
checkers.

## Use it

```bash
datasemver diff old.csv new.csv --current-version 1.4.2
```

```
╭───────────── DataSemver ──────────────╮
│ Suggested bump: MAJOR                 │
│ 0.0.0 -> 1.0.0                        │
│                                       │
│ old: old.csv (8 rows)                 │
│ new: new.csv (10 rows)                │
╰───────────────────────────────────────╯
                                    Columns
┏━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ column      ┃ status    ┃ type old ┃ type new ┃ nulls         ┃ cardinality ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ country     │ added     │ -        │ string   │ - -> 0.0%     │ - -> 4      │
│ phone       │ modified  │ int64    │ string   │ 0.0% -> 0.0%  │ 8 -> 10     │
│ email       │ modified  │ string   │ string   │ 25.0% -> 0.0% │ 6 -> 10     │
│ legacy_code │ removed   │ string   │ -        │ 0.0% -> -     │ 8 -> -      │
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
└──────────┴───────────────────────────┴───────────────────────────────────────────────┘
```

A removed column and an `int64` that became a `string` make this a breaking release.
Without `--output`, the changelog entry is printed at the end; with it, the entry is
prepended to the file you name.

```bash
datasemver diff old.csv new.csv --output CHANGELOG.md
datasemver diff old.csv new.csv --json | jq -r '.bump'
datasemver rules examples/lenient_rules.yaml
```

| Option | Short | Description |
| --- | --- | --- |
| `--rules PATH` | `-r` | Rule file replacing the bundled defaults |
| `--current-version TEXT` | `-c` | Version the new dataset is bumped from (default `0.0.0`) |
| `--output PATH` | `-o` | Write the changelog entry, prepending it if the file exists |
| `--json` | | Print the full report as JSON instead of the tables |

## What it looks at

- **Schema** — columns added, removed and renamed, dtype changes, nullability.
- **Content** — row counts, cardinality, mean and standard deviation of numeric columns,
  mode and category sets of categorical ones.
- **Semantics** — renames inferred from the similarity of both the column name and its
  values, so `user_name` becoming `username` is one rename rather than a removal plus an
  addition.

The bump is the strongest severity across every classified change. Changes no rule covers
are reported as unclassified and never inflate it.

| Bump | Meaning for consumers |
| --- | --- |
| **Major** | Existing queries and pipelines can break |
| **Minor** | New information, existing contracts still hold |
| **Patch** | Same meaning, better data |

## Formats

Detected by extension: `.csv`, `.tsv`, `.json`, `.jsonl`, `.ndjson`, `.parquet`, `.pq`.

The delimiter of a `.csv` is detected from its first lines — comma, semicolon, tab and pipe
are recognised, and a character that only appears inside quoted values does not win — while
`.tsv` always uses the tab. Set `DATASEMVER_CSV_DELIMITER` to skip detection and force one
character, the tab written as `\t`.

Nested JSON objects and Parquet structs are flattened with a `.`, so
`{"user": {"name": "..."}}` is profiled as `user.name`. Types are inferred for the text
formats; Parquet carries its own schema and is trusted as it stands.

## Rules

Every severity is a list of rules, evaluated `major`, then `minor`, then `patch`. The first
rule that matches a change assigns its severity.

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

Pass it with `--rules custom.yaml`, and check how it was parsed with `datasemver rules
custom.yaml`. Threshold rules pair with their plain counterpart in a lower severity, which
then acts as the fallback. Unknown rule names and severities are errors, not silent no-ops.

## Python API

```python
from datasemver import analyze

report = analyze("old.csv", "new.csv", current_version="1.4.2")

print(report.bump)          # Severity.MAJOR
print(report.next_version)  # 2.0.0

for item in report.classified:
    print(item.severity, item.rule, item.change.description)
```

`analyze_schemas()` takes two already loaded profiles, so dataframes from anywhere can be
compared without touching the filesystem:

```python
import pandas as pd
from datasemver.core.analyzer import analyze_schemas
from datasemver.formats.loader import schema_from_frame

report = analyze_schemas(
    schema_from_frame(pd.read_sql(query, engine), "warehouse@yesterday"),
    schema_from_frame(pd.read_sql(query, engine), "warehouse@today"),
)
```

## Also in the box

- A **web dashboard** — FastAPI backend, no-build frontend — under the `web` extra, run
  with `uvicorn datasemver_web.backend.main:app`. It is a local tool with no
  authentication: keep it on the loopback interface.
- A **GitHub Action** that analyses the datasets a pull request touches and posts the
  suggested bump as a comment, rewritten on each push.
- Two ready-made rule profiles, strict and lenient, and a full catalogue of rules, metrics
  and thresholds.

Those, the source, the changelog and a Spanish edition of this page live in the project
repository, linked from this page's sidebar.

## Security

Reading a dataset parses it. CSV and JSON go through pandas and the standard library, which
do not execute file content; Parquet goes through pyarrow, and the dependency floor is
`pyarrow>=23.0.1` because earlier versions carried a critical code-execution flaw
(CVE-2023-47248) triggered by a malicious Parquet file. Do not lower that floor. Rule files
are YAML loaded with `yaml.safe_load` and cannot execute code. The library and the CLI never
open a socket, and write nothing unless you pass `--output`.

## License

MIT.
