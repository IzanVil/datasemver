# Rules

A rules file maps change types to severities. The engine evaluates `major` first, then
`minor`, then `patch`, and the first rule that matches a change assigns its severity. The
strongest severity found across all changes becomes the suggested bump; changes that match
no rule are reported as unclassified and do not affect the bump.

```yaml
major:
  - column_removed
  - row_count_decrease_greater_than: 20

minor:
  - column_added

patch:
  - nulls_fixed
```

Pass a file with `--rules custom.yaml` to replace the bundled defaults entirely, and run
`datasemver rules custom.yaml` to check how it was parsed.

## Change types

| Rule | Fires when |
| --- | --- |
| `column_added` | A column exists only in the new dataset |
| `column_removed` | A column exists only in the old dataset |
| `column_renamed` | A removed and an added column match by name and value similarity |
| `type_changed_incompatible` | A column changed to an unrelated type, e.g. `int64` to `string` |
| `type_changed_compatible` | A column widened along `bool` → `int64` → `float64` |
| `row_count_increased` | The new dataset has more rows |
| `row_count_decreased` | The new dataset has fewer rows |
| `nulls_fixed` | The null ratio of a column dropped by more than 1 point |
| `nulls_introduced` | The null ratio of a column grew by more than 1 point |
| `new_category_added` | A categorical column gained values |
| `category_removed` | A categorical column lost values |
| `cardinality_changed` | The share of distinct values of a column moved by more than 10 points |
| `distribution_shift` | A numeric mean moved by at least 0.5 standard deviations |
| `minor_stat_change` | A numeric mean moved by more than 1% but below the shift threshold |

A column is treated as categorical when it holds at most 200 distinct values and its
distinct values cover at most half of its non-null rows. Contiguous integer keys are
excluded from the numeric statistics, since their mean carries no business meaning.

## Threshold rules

These accept a numeric limit and match only when the metric is strictly above it.

| Rule | Metric |
| --- | --- |
| `row_count_decrease_greater_than` | Percentage of rows lost |
| `row_count_increase_greater_than` | Percentage of rows gained |
| `null_ratio_increase_greater_than` | Points of null ratio gained by a column |
| `null_ratio_decrease_greater_than` | Points of null ratio lost by a column |
| `mean_shift_greater_than` | Percentage the mean of a numeric column moved |
| `cardinality_change_greater_than` | Percentage the distinct value count moved |

Combine a threshold rule with its plain counterpart to get a fallback severity:

```yaml
major:
  - row_count_decrease_greater_than: 20
minor:
  - row_count_decreased
```

An unknown rule name, an unknown severity, or a threshold on a rule that does not take one
raises an error instead of being silently ignored.
