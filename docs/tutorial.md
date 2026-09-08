# Tutorial: the cleaning that changed the answer

A data team is handed the Titanic passenger list and asked to tidy it up for a report. They
do four sensible things:

- drop `Cabin`, which is empty for 77% of the rows
- fill the missing ages with the median, so charts stop having gaps
- round `Fare` to whole units, because nobody quotes fares to four decimals
- scope the report to first and second class, which is what it was about

Every one of those is defensible. Together they produce a dataset where the survival rate is
**56%** instead of **38%**, and nothing in the column list says so.

This walkthrough takes about five minutes and needs no account, no service and no sample data
beyond one public file.

## Setting up

```bash
pip install datasemver
curl -o passengers_v1.csv \
  https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv
```

That is 891 rows and 12 columns. Now produce the tidied version, which is the "v2" a pipeline
would have written:

```python
# clean.py
import pandas as pd

d = pd.read_csv("passengers_v1.csv")
d = d.drop(columns=["Cabin"])                   # 77% empty
d["Age"] = d["Age"].fillna(d["Age"].median())   # fill the gaps
d["Fare"] = d["Fare"].round(0).astype(int)      # round the fares
d = d[d["Pclass"] != 3]                         # the report is about 1st and 2nd
d.to_csv("passengers_v2.csv", index=False)
```

```bash
python clean.py
```

## Asking what happened

```bash
datasemver diff passengers_v1.csv passengers_v2.csv --current-version 1.2.0
```

The changelog entry it prints is the part worth reading:

```markdown
## [2.0.0] - 2026-09-08

### Major
- Row count fell from 891 to 400 (-55.11%)
- Column 'Cabin' was removed
- Column 'Survived' distribution moved (KS 0.250): mean 0.3838 -> 0.5575, std 0.4863 -> 0.4967
- Column 'Pclass' distribution moved (KS 0.750): mean 2.309 -> 1.46, std 0.8356 -> 0.4984
- Column 'Age' distribution moved (KS 0.155): mean 29.7 -> 33.57, std 14.52 -> 14.31
- Column 'Parch' distribution moved (KS 0.250): mean 0.3816 -> 0.3675, std 0.8056 -> 0.691
- Column 'Fare' changed type from float64 to int64
- Column 'Fare' distribution moved (KS 0.306): mean 32.2 -> 54.96, std 49.67 -> 66.23

### Minor
- Column 'Embarked' balance shifted (PSI 0.164): 'Q' 8.7% -> 1.3%

### Patch
- Column 'PassengerId' mean moved from 446 to 454.4 (1.88%)
- Column 'Age' nulls dropped from 19.9% to 0.0%
- Column 'SibSp' mean moved from 0.523 to 0.41 (21.61%)
```

`1.2.0` becomes `2.0.0`, and the reason is not that a column disappeared.

## Reading the answer

**`Survived` moved from 0.3838 to 0.5575.** This is the line that matters. Anyone who computes
a survival rate from v2 gets 56% where v1 said 38%, and no schema check anywhere would have
caught it: the column is still there, still named the same, still a number. It moved because
third class was filtered out, and third class is where most of the deaths were. The filter was
about scope; the effect was on the answer.

**`Embarked` is a minor, not a major.** Every port that was there is still there — the category
set is unchanged — but Queenstown went from 8.7% of passengers to 1.3%. A comparison of the
distinct values sees nothing. The Population Stability Index sees 0.164, which is the band
between "worth knowing" and "no longer the same population".

**`Age` gets two findings of different severity.** Its nulls dropping from 19.9% to zero is a
`patch`: the dataset says what it said, with fewer gaps. Its distribution moving is a `major`,
because filling a fifth of a column with one value is not a neutral act. Both are true at once,
and the stronger one sets the bump.

**Rounding `Fare` is a breaking type change on its own.** `float64` to `int64` is a narrowing,
not a widening: every fare that had a fractional part no longer round-trips, and code that
divided by it now does integer division. Widening the other way — `int64` to `float64` — would
have been a patch. The direction is the whole difference.

**`PassengerId` is reported as a patch and can be ignored**, which is the point of it being a
patch rather than silence. It is an identifier; its mean carries no meaning. A rules file can
say so, and the next section does.

## Refusing it

Finding out afterwards is worth less than not shipping it. `--fail-on` turns the report into a
gate:

```bash
datasemver diff passengers_v1.csv passengers_v2.csv --fail-on major
```

```
refused: suggested bump is major, which reaches the --fail-on threshold of major
```

```bash
echo $?   # 1
```

Three exit codes, so a pipeline can tell them apart: `0` ran and had nothing to refuse, `1` ran
and the bump reached the threshold, `2` could not run at all. The same flag works in the
[GitHub Action](https://github.com/IzanVil/datasemver/blob/main/.github/workflows/datasemver.yml),
where the refusal arrives after the comment explaining it.

### Saying which columns you meant

`PassengerId` drifting is noise, and so is the row count if the report is *supposed* to narrow.
A rules file says which is which:

```yaml
# report-rules.yaml
major:
  - column_removed
  - distribution_shift: {columns: [Survived, Fare]}
minor:
  - distribution_shift
  - category_balance_shift
ignore:
  - minor_stat_change: {columns: [PassengerId]}
```

```bash
datasemver diff passengers_v1.csv passengers_v2.csv --rules report-rules.yaml
```

The two columns the report is actually about keep their severity; the rest drop a level; the
identifier is reported and counts for nothing:

```
MAJOR  column_removed          Column 'Cabin' was removed
MAJOR  distribution_shift      Column 'Survived' distribution moved (KS 0.250)
MAJOR  distribution_shift      Column 'Fare' distribution moved (KS 0.306)
MINOR  distribution_shift      Column 'Pclass' distribution moved (KS 0.750)
MINOR  distribution_shift      Column 'Age' distribution moved (KS 0.155)
MINOR  category_balance_shift  Column 'Embarked' balance shifted (PSI 0.164)
—      minor_stat_change       Column 'PassengerId' mean moved from 446 to 454.4
```

`ignore` is not silence. The change is still detected and still printed; it is left
unclassified so it contributes nothing to the bump. "This was expected" and "nothing happened"
are different answers, and only one of them is true.

## Which rows, not just which shape

Everything above compares profiles. Give it a key and it compares rows:

```bash
datasemver diff passengers_v1.csv passengers_v2.csv --key PassengerId
```

```
0 row(s) added and 491 removed, matched on the key
266 of 400 row(s) present in both changed value (66.5%): Fare (248), Age (41)
```

Two thirds of the rows that survived the filter also changed value — which the row count alone
could never have told you, because it only fell.

## Keeping the answer without keeping the data

A comparison reads a profile, and a profile is small:

```bash
datasemver profile passengers_v1.csv
```

```
profile written passengers_v1.profile.json (12 columns, 891 rows, 6211 bytes)
```

6 KB against 60 KB here; on a 63 MB Parquet file it is 2.9 KB. Commit it beside the dataset and
the next comparison needs only the new version:

```bash
datasemver diff passengers_v1.profile.json passengers_v3.csv
```

The file it describes does not have to exist any more. That is what makes this work against a
dataset too large to keep two copies of, or one that lives in a warehouse you can only query.

## Where to go next

- [The rule catalogue](https://github.com/IzanVil/datasemver/blob/main/docs/rules.md) — every rule, metric and threshold
- [The README](https://github.com/IzanVil/datasemver/blob/main/README.md) — databases, workbooks, DVC, the dashboard and the Python API
- `datasemver rules` — prints the rule set exactly as the engine understood it, which is the fastest way to check a rules file does what you meant
