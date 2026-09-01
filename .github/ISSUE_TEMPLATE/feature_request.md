---
name: Feature request
about: Suggest a detection, an option or an improvement
title: ""
labels: enhancement
assignees: ""
---

## The problem

The situation you are in and why the current behaviour does not cover it. Concrete beats
abstract: describe the dataset change you cannot classify today.

## The change you would like

What DataSemver should do. If it is a new detection, name it as a rule and say which
severity it belongs to by default:

```yaml
major:
  - primary_key_changed
```

## Example

A before and after that shows the detection firing, and the report you would expect.

```bash
datasemver diff old.csv new.csv
# expected: Suggested bump: MAJOR (primary_key_changed)
```

## Alternatives considered

Custom rules, a pre-processing step, another tool: what you tried and why it fell short.

## Scope

- [ ] I am willing to open a pull request for this
- [ ] This would change the bump produced for datasets that already work today
