---
name: Bug report
about: Something behaves differently from what the documentation promises
title: ""
labels: bug
assignees: ""
---

## What happened

A clear description of the behaviour you observed.

## What you expected

The bump, the changelog entry or the output you expected instead.

## Reproduction

The exact command:

```bash
datasemver diff old.csv new.csv --rules custom.yaml
```

A minimal pair of datasets that triggers it. Synthetic rows only, never production data:

```csv
id,name,score
1,ana,10
```

If a custom rules file is involved, paste it:

```yaml
major:
  - column_removed
```

## Output

The console output, or the relevant part of `--json`, with anything sensitive removed.

```
paste here
```

## Environment

- DataSemver version or commit:
- Python version (`python --version`):
- Operating system:
- `pip show pandas pydantic | grep -E "Name|Version"`:

## Anything else

Workarounds you found, related issues, or the point where the behaviour changed.
