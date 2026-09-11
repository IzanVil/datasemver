# Changelog

DataSemver versions itself with the vocabulary it applies to datasets: **Major** for
changes that break what consumers already depend on, **Minor** for new capability that
leaves existing contracts intact, **Patch** for fixes that keep the same meaning.

This project follows [Semantic Versioning](https://semver.org).

## [Unreleased]

## [0.8.2] - 2026-09-11

### Patch
- A column of arrays is profiled instead of crashing the command. A JSON list field, or a
  Parquet or Feather `LIST` column, arrived as a value `hash` refuses, and every statistic a
  profile holds needs a hashable one -- so `nunique` raised `TypeError: unhashable type: 'list'`
  and the traceback reached the terminal, on a file nobody would call malformed. It exited `1`
  as it did so, which is the code a refused bump uses, so a pipeline running with `--fail-on`
  could not tell an unreadable dataset from a rejected one. Such a column is now profiled on the
  text of its values: `["a", "b"]` and `["c"]` are two distinct values, the column reads as a
  string, and the cardinality and the balance a comparison is about to compare are there.
  Refusing the dataset was the other option, and a column of tags is not a broken dataset.
- The standalone executable carries the same extras wherever it is built, and it now carries
  `excel` as well as `sql`. The build froze whatever happened to be installed beside it, so the
  release binary had database support and the one a contributor built on their own machine
  could have had more -- two different files, both called `datasemver`, both claiming the same
  version. `scripts/build_executables.py` declares the list, refuses to build without it, and
  passes everything outside it to PyInstaller as `--exclude-module`, so a machine with `duckdb`
  installed still produces the published binary. The workflow reads that list from the script
  rather than repeating it. Workbooks went in because someone holding one file cannot add an
  extra afterwards and `openpyxl` is small; the `duckdb` engines stayed out because they cost
  22 MB of the download -- 110 MB against 132 -- for answers the default engine already gives.
- The build checks the binary it produced. A build that succeeds and a binary that works are
  different things, and the gap between them is where a missing extra hides until someone
  downloads it: the script now runs the file over one dataset of every format it claims to
  read, confirms the bundled rules are in there, and confirms that an excluded engine is
  refused rather than crashing.
- The message for a missing extra says something a reader can act on. Inside the executable
  there is no environment to install into, so `pip install "datasemver[duckdb]"` was advice
  for a machine the reader may not have; the binary now says the feature is not part of it and
  that it needs a Python installation, and says the rest only where it applies. Both readmes
  say which extras the binary carries and which it does not.

## [0.8.1] - 2026-09-11

### Patch
- The action can be published. Its description was 140 characters and the GitHub Marketplace
  refuses anything over 125, which is a limit that exists only inside a form: the listing
  validates on submit, so nothing in the repository knew, `action.yml` was perfectly valid
  YAML, and the first sign of trouble was a person clicking Publish and being told no. It is
  109 characters now -- the clause it lost, that a run can refuse the merge, is two paragraphs
  down in both readmes -- and a test asserts the limit, so the next edit that grows past it
  fails in the commit that does it rather than months later in a form. The `uses:` line in the
  readmes points at this release, since it is the first tag the Marketplace will accept.

## [0.8.0] - 2026-09-11

### Major
- A profile written without `-o` keeps the whole dataset name, where it kept only the part
  before the first dot. `sales.2024.csv` and `sales.2025.csv` are two versions of one dataset
  -- the case this tool exists for -- and both of them answered to `sales.profile.json`, so
  profiling the second silently overwrote the first. The suffix that comes off is now the one
  `dataset_suffix` already defines, which is what kept `dump.csv.gz` from becoming
  `dump.csv.profile.json` and is the only reason the old rule reached for the first dot at
  all. A workbook sheet and a database table are part of what is being profiled and now reach
  the name too: `quarterly.xlsx#Q3` writes `quarterly-Q3.profile.json`, where two sheets of
  one workbook used to share a file. Recorded as major because a script that hard-coded the
  old name reads a file that is no longer written.
- `default_profile_path` is imported from `datasemver.formats.loader` rather than
  `datasemver.core.profile`. Naming a profile means knowing what a dataset suffix is and what
  a connection URL is, and both are what the loader knows; `core.profile` cannot reach for
  either without closing the import circle it is already written around. It was never
  exported from the package root, whose contents are the interface the project promises.
- The licence is the Apache License 2.0, where it was MIT. It is recorded as major for the
  same reason a dataset's contract change is: what someone is allowed to build on this is now
  stated differently. In practice the permissions are the ones MIT already gave -- use, modify
  and redistribute, commercially and inside closed software -- with three things written down
  that MIT leaves silent: an explicit patent grant, a requirement that modified files say they
  were modified, and a clause reserving the project's name and marks. A fork stays free to
  exist and is not free to present itself as this project, which is the protection that
  matters for a small project and the one a copyleft licence would not have given.
- Releases up to and including 0.7.0 were published under MIT and stay available under it. A
  licence already granted on a published artefact cannot be withdrawn, so this applies from
  the next release onwards. Contributions made by others while the project was MIT are carried
  in under MIT's own permission to sublicense.

### Minor
- The pull request analysis is an action, so adopting it is five lines of YAML rather than
  two files to copy and keep up to date. `uses: IzanVil/datasemver@v0.8.0` sets up Python,
  installs the library, resolves the base ref, analyses the datasets the branch changed,
  posts the report as a comment and rewrites that comment on every push -- the same sequence
  the workflow here has been running, now behind `action.yml` with inputs for the rules file,
  the threshold, the engine, the paths and the token. It installs the library from its own
  checkout rather than from the index, so the tag picks the pair that was tested together
  rather than a script and a library that happen to be nearby.
  `fail-on` still refuses after the report is posted and never before it, which is the
  ordering the gate has always had and is now a test rather than a comment: a refusal that
  suppressed its own explanation blocks a merge without saying which dataset or why. This
  repository's own workflow runs it from the working tree, so every pull request here is a
  rehearsal of what it does in someone else's repository, and the parts no YAML parser checks
  -- the script path, the pinned action SHAs, the step order, the inputs the workflow passes
  -- are asserted in the suite.
- A dataset can be profiled without being loaded. Every statistic a profile holds is an
  aggregate, and an aggregate does not need the dataset in memory -- only the thing computing
  it does -- so `--engine duckdb` computes them over the file through DuckDB instead of over a
  dataframe, behind the new `duckdb` extra. On 16M rows and seven columns that is 21.4 s and
  3190 MB down to 16.1 s and 1736 MB for a Parquet file, and 49.9 s and 3311 MB down to 20.9 s
  and 2856 MB for the 1.21 GB CSV of the same data. The numbers it returns are the numbers the
  dataframe path returns, down to float rounding: the same types, null ratios, cardinalities,
  categories and quantile grids, asserted column by column against each other in the suite.
  `--engine duckdb-sketch` goes further, at 3.1 s and 1246 MB, by taking the quantile grid from
  a t-digest rather than computing it -- everything else stays exact, because a sketched
  cardinality answers 616 for 500 distinct values and would report a change nobody made, while
  a sketched grid is out by 0.23% of a column's range at worst and its two ends are not
  estimated at all. On the measured pair it moved one KS statistic from 0.118 to 0.119 and
  changed nothing else: same changes, same severities, same bump.

  Neither is chosen for anyone. A run that switched engine because a file looked large would
  answer a question nobody asked, so `--engine` and `DATASEMVER_ENGINE` are the only ways in,
  and what these engines cannot read -- a nested column, a workbook, a database table, `--key`,
  which needs the rows they exist not to load -- is refused by name rather than quietly handed
  back to the other path. `DATASEMVER_DUCKDB_MEMORY_LIMIT` caps what DuckDB may hold, and what
  does not fit spills to disk. A stored profile now records which engine wrote it, the way it
  already records which version did; a profile that says nothing came from the dataframe path,
  which is what every profile written until now did.
- The dashboard reads compressed datasets, and the upload limit now counts the size that
  decides what reading one costs. It counted the bytes that arrived, which for a `.csv.gz` is
  the wrong number by three orders of magnitude: measured through the endpoint, a 0.25 MB
  upload -- one percent of the 25 MB limit -- became 86 MB of dataframe and took peak memory
  from 138 MB to 656 MB, and that was ordinary repetitive data at 344:1 rather than anything
  crafted. Gzip reaches about 1030:1 when someone is trying. So a compressed upload is now
  decompressed under the rule the size check already followed -- read one chunk past the limit
  and no further -- and refused with `413` naming what it holds once decompressed. The refusal
  costs one chunk of memory rather than the expansion, which is the property that makes it a
  guard rather than a slower way of running the attack, and a test asserts it as a memory peak
  rather than trusting the reading. With the expansion bounded, `.csv.gz` and `.tsv.gz` are
  back among the formats the dashboard accepts, so the one surface that could not read a
  format the rest of the tool supports can read it again. Closes #8.
- Feather. `.feather` and `.arrow` -- the two names the Arrow IPC file format is written under
  -- are read, which closes the last common columnar format this could not open. It needs no
  new dependency: `pyarrow` has been a hard requirement since the beginning, and it is what
  pandas reads a Feather file with. The types are trusted exactly as Parquet's are, and for
  the same reason rather than a similar one: both are Arrow, so the file states what every
  column is, and inferring again would be second-guessing a schema that was written down
  instead of reading one that was not. A column of postcodes stays strings rather than
  becoming integers with the leading zero gone. Structs are flattened into dotted columns the
  way Parquet's and JSON's already were, and the dashboard accepts the two extensions without
  being told, because its upload list is derived from the formats the library reads.
  `--schema-only` is deliberately left alone: a Feather file carries no per-column statistics
  in its metadata the way a Parquet footer does, so there is nothing to read there instead of
  the rows. Closes #3.

### Patch
- Regenerating the terminal captures is reproducible. Two of the four show a changelog entry,
  which carries the date it was generated, so the script rewrote those two images on any day
  but the one before -- and a regeneration then could not answer the only question it raises,
  which is whether the tool's output actually moved. The date the committed images already
  carry is pinned in the script, and a run on current `main` now reproduces all four byte for
  byte, `cli-dvc` included: the capture #5 was opened about turns out to have been up to date
  since the DVC integration landed, and the report that it was stale came from a machine where
  the script found no DVC and said so.
- The dashboard no longer offers a format it then refuses. `/api/meta` reported the whole set
  of extensions the library reads, and the frontend builds the file picker's `accept` list and
  the hint below it from exactly that -- so the picker invited a `.csv.gz` and the server
  turned it away, with a message that enumerated `.csv.gz` among the extensions it said it
  wanted. What `/api/meta` reports is now what an upload is actually accepted for, held by a
  test as a subset rather than as a list, so the two cannot drift apart again in the silence
  they drifted apart in the first time -- an interface lying quietly does not throw. Fixed in
  #10 by @slsgzs-cloud. The two sets happen to be equal again now that the guard below let the
  compressed formats back in, and the test holds either way. Closes #9.
- Profiling a database table no longer writes the connection password to disk. With no `-o`,
  the whole source became the file name, so `postgresql://reader:s3cret@warehouse/analytics`
  wrote `postgresql:/reader:s3cret@warehouse/analytics#customers.profile.json` -- creating
  the directories on the way -- and the credential stayed there, in whatever tracks that
  directory, long after the command. A table is now named after itself, in the working
  directory: `customers.profile.json`. The contents were already redacted, for the reason the
  name should have been.
- The tutorial is in Spanish too, at `docs/tutorial.es.md`, which is the last document that was
  only in one language. The tool prints English, so the output blocks and the commands are
  reproduced exactly as they come back rather than translated -- a page showing a terminal that
  says something the terminal does not say is worse than an English one. The comments in the
  example script the reader writes themselves are translated, since those are prose.

## [0.7.0] - 2026-09-08

### Minor
- Excel. `.xlsx` and `.xlsm` are read through the `excel` extra, and a source names a sheet
  after `#` the way a database source names a table -- `quarterly.xlsx#Q2` -- because a
  workbook and a database are the two sources here that hold more than one dataset and there
  is no reason to invent a second spelling. Without a fragment the first sheet is read; a bare
  number is a position and a quoted one is a name, so a sheet actually called `2024` is
  reachable. Naming a sheet that is not there answers with the ones that are, which is what
  the reader needs next. Types are inferred as for CSV, since numbers stored as text are the
  normal state of a spreadsheet rather than an edge case. The dashboard accepts workbooks
  without being told, because its upload list is derived from the supported formats.
- The dashboard does what the library does. It was two releases behind: profiles, the row
  comparison and the distribution statistics reached the CLI and stopped there, so the
  interface most people meet first answered 0.5.0's questions with 0.6.0's engine. Either side
  of a comparison can now be a stored profile, which is what lets one reach a version past the
  upload limit or gone from disk entirely; `POST /api/profile` returns the profile of an upload
  and the **Save profile** button downloads it; and a **Key** field compares rows.
- Uploading a profile needed the compound suffix to survive being stored. The server names an
  upload itself, so that nothing a caller sends reaches a path, and `Path("x.profile.json")`
  has a suffix of `.json` -- which is a dataset format here, so a profile would have been read
  back as an array of records. It keeps both parts now, and `/api/meta` reports the profile
  suffix apart from the dataset formats, because a profile is not one of them.
- The pull request script takes `--fail-on` and the workflow can refuse a merge. `--fail-on`
  reached the CLI in 0.6.0 and stopped there, so the surface people actually consume this
  through -- the comment on a pull request -- could still only describe what it found. The
  refusal runs after the comment is posted, never before: a gate that suppressed its own
  explanation would block a merge and never say which dataset or why. Off unless
  `DATASEMVER_FAIL_ON` is set, because a repository already running this expects an exit code
  of zero.
- The package namespace exports what the last two releases added. `datasemver` exposed
  `analyze` and four models, so profiles, the row comparison and `analyze_schemas` were only
  reachable through `datasemver.core.*` -- and the README documented one of those paths as the
  way in, which makes an internal module part of the contract in a package that ships
  `py.typed`. Twenty-one names are exported now, the READMEs import from the package, and a
  test fails on any name in `__all__` that stops resolving.

### Patch
- A tutorial, in `docs/tutorial.md`. It works through the Titanic passenger list and four
  changes a data team would defend one at a time -- drop a column that is 77% empty, fill the
  missing ages, round the fares, scope the report to first and second class -- which together
  move the survival rate from 38% to 56% without touching a column name. Every command in it
  was run and every number in it came back from the tool rather than from an estimate.
- The dashboard's own README describes the dashboard as it is. Its endpoint table listed four
  where there are five, the file tree still carried the directory name from before the package
  was renamed, and the request it documents was missing both the `key` field and the fact that
  either side may be a stored profile -- everything added to the thing the document is about.
- `requirements/base.txt` listed `pytest` as something the library needs to run. It does not:
  `pyproject.toml` has never had it among `dependencies`, so the file was overstating what an
  install costs and putting a test runner into environments that only wanted to read a CSV. It
  moved to `dev.txt`, where the rest of the tooling already was, and `base.txt` now matches
  `dependencies` name for name.
- The repository root holds what builds the project and little else. Seventeen tracked files
  there had become hard to read past: the community documents moved to `.github`, where GitHub
  reads them exactly as it did before and the security policy still fills the Security tab;
  the demo recording and the PyPI readme moved to `docs`; and the four `requirements-*.txt`
  became `requirements/`, whose `-r` lines pip resolves relative to the file holding them.
  Eight files are left. Nothing was deleted and nothing changed what it does.
- Every reference moved with them, which is most of the work: the links in three READMEs and
  on both pages of the site, `readme` in `pyproject.toml`, the install commands, the project
  layout listings and the dashboard's own README. `MANIFEST.in` needed its includes placed
  after `prune .github`, or the prune would have taken the three documents it is not aimed at
  and a source distribution would have quietly lost them.
- The terminal captures in the READMEs show what the tool prints. They were generated the day
  before the release that changed it, so `datasemver rules` was pictured with a rule set that
  no longer exists and described in its alt text as six rules under major where there are
  seven, and seven under minor where there are ten. `scripts/capture_cli.py` regenerated three
  of the four; `cli-dvc` needs DVC on the machine and was left alone.
- The dashboard has a mark: two blocks for the two versions, split by the seam that is the
  comparison between them. It is inline SVG taking its colours from the theme tokens the page
  already switches on, so it follows light and dark without a second copy, and there is a
  matching favicon which carries its own palette because a favicon is fetched on its own and
  inherits nothing from the page.
- `.svg` was missing from both the wheel's package data and `MANIFEST.in`, which is the same
  gap that once shipped the dashboard's dependencies without the dashboard. The favicon would
  have been served as a 404 from an installed copy and from nowhere else. Two tests hold it:
  the page carries its mark, and the favicon is served.
- The mark reaches the surfaces a reader meets first: both READMEs and the PyPI page carry it,
  and the project site has it in its nav along with a favicon it did not have at all. The seam
  takes each surface's own accent token rather than naming a colour -- teal on the site, blue
  in the dashboard -- so the form is what identifies the project and the colour is whatever the
  page it sits on already uses. GitHub gets a `<picture>` so the mark follows the reader's
  theme there too; PyPI gets a plain image, because it strips the element that would.

## [0.6.0] - 2026-09-07

### Minor
- `--key` compares the datasets row by row instead of profile against profile. A profile
  cannot answer which rows changed -- a version where a third of the rows were rewritten with
  values drawn the same way has the same profile as the one before it, and is a different
  dataset to anyone joining against it. Rows added, removed and changed are reported, with the
  columns that changed and how many rows each accounts for. It needs both datasets in memory,
  so it stays opt-in; a key that is missing or repeated is refused with the count rather than
  matched arbitrarily, because there is no answer to guess about which of two rows sharing a
  key is the one that moved.
- Any rule takes a `columns` list, and `ignore` takes rules that are detected and left
  unclassified. Severities were uniform across every column, so tolerating the one that drifts
  by design -- an `ingested_at`, a load counter -- meant raising the threshold for all of them,
  spending the signal everywhere to silence it in one place. An ignored change still appears in
  the diff and contributes nothing to the bump, because "this was expected" and "nothing
  happened" are different answers.
- `--schema-only` profiles Parquet from its footer instead of its rows: the schema, the null
  counts and the ranges are all in there, which is every input the breaking-change rules need.
  Five point four seconds and 641 MB become one second and 137 MB over two 61 MB files. It
  answers less on purpose and says so -- with no data read there is no distribution to compare,
  and a footer that does not carry statistics is refused rather than read as zero nulls, which
  would turn a column that is entirely null into a column with none.
- The DVC run and the pull request script read a profile committed beside the dataset when one
  is there, in place of the previous version itself. `dvc get` pulled the whole base dataset
  from the cache or the remote and the pull request script pulled it through git on every push;
  both now read a few hundred bytes of text out of the base revision, the way the `.version`
  sidecar already worked. A DVC comparison no longer needs the remote at all, and works on a
  revision whose data has since been collected.
- `datasemver --version`.
- Datetime columns are compared. One carried a type, a null ratio and a cardinality and
  nothing else, because the statistics were filled in for `int64` and `float64` only, so the
  most common thing that happens to a date column -- the whole window sliding forward, or an
  export that now covers half the period -- was reported as no change at all. Five thousand
  hourly rows moved six years is a `major` now. They are profiled on their epoch in seconds
  and compared with the same KS statistic as any other column, but never on a relative move
  of the mean: a percentage of an epoch is a percentage of the time since 1970. The change is
  described in dates.
- A categorical column past the tracked limit is compared on its balance instead of not at
  all. The limit was a cliff: 200 distinct values were profiled with their counts and 201 with
  nothing, so a city column collapsing until one value held 95% of the rows was reported as no
  change. Everything below the most frequent values is summed into one bucket now, which is
  how PSI is computed on a high-cardinality feature anyway, and the exact category set is
  still only kept where it is exact -- a value missing from a sample of a set is not a value
  that was removed. Where two versions truncate at different places only the categories both
  kept are compared, so a category sitting near the cut is not read as one that disappeared.
- Comparisons read distributions, not single numbers. A column's profile now carries a
  quantile grid and, for a categorical column, the count per category, and two changes are
  detected from them: `distribution_shift` on the Kolmogorov-Smirnov statistic, and
  `category_balance_shift` on the Population Stability Index. Three changes that a version
  before this reported as no change at all: a fraud label going from 50/50 to 1/99 with both
  values still present, a spread growing from one to forty with the mean unmoved, and a column
  splitting into two modes around the same centre. Only the mean was ever compared, and the
  comparison returned before reaching anything else whenever the mean had not moved.
- Both are measured against what the sample size supports, because the same change makes the
  tool wrong in the other direction otherwise. A KS statistic has no fixed reading: on four
  rows against five, appending one row moves the distribution by a fifth, so a shift has to
  clear the critical value for those sizes as well as the threshold. Six rows and one outlier
  used to be a `major`; it is a `minor` now, and the fixture pair that first surfaced this is
  a test.
- `datasemver profile` writes what a comparison reads to a file, and `diff` accepts one
  wherever it accepts a dataset, on either side. A profile is a few hundred bytes against
  megabytes of data -- 2.9 KB for a 63 MB Parquet -- so it can be committed beside the
  dataset, and the version it describes never has to be fetched again, or exist at all. The
  dispatch sits in `load_schema`, so the Python API, the dashboard and the DVC run all got it
  at once. `.profile.json` marks one, kept apart from `.json` because that is a format read as
  data, and a profile from a newer DataSemver is refused rather than half-understood.
- `--fail-on major` on `diff` and `dvc` exits `1` when the suggested bump reaches a severity,
  so a pipeline can refuse a dataset instead of only describing it. The command found a
  breaking change and exited `0` before, which left parsing the JSON as the only way to act on
  it. Exit `2` still means the run itself failed: a caller that cannot tell a rejected dataset
  from a broken pipeline cannot do anything useful with either.

### Patch
- The suite no longer depends on how wide the terminal running it is. Rich wraps to the
  console it finds, so a correct message broke across a line in a different place on a Windows
  runner than on the machine the assertion was written on, and a test about the message failed
  over the wrap. The width is pinned for the whole suite, and the assertions that span a space
  collapse the line breaks first. Caught by CI on Windows, then reproduced locally by running
  the suite at a narrow width, which also found an older test with the same fragility.
- Two rows that both hold no value compared as different, and a column whose type widened from
  `int64` to `float64` compared as every row changed. Both came out of comparing values as text:
  a pandas NA does not survive `==` as a boolean, and `1` and `1.0` are the same number written
  two ways. Numbers are compared as numbers and a missing value is substituted before the
  comparison rather than after it. Found by the tests for the feature, before it shipped.
- A date read as a different date depending on how it was stored. The epoch conversion divided
  by a fixed billion, and `astype("int64")` counts in the column's own resolution, which is
  microseconds on pandas 3 and nanoseconds before it -- so 2020 arrived as 1970. It casts to a
  named unit first, and four resolutions and a timezone are pinned by tests.
- A column holding one repeated value compared as maximally different from itself. The KS
  approximation compared one version's quantile levels against the other's distribution, which
  is only the same thing where the distribution has no steps in it; a constant column is all
  step. Both distributions are read at the same point now. Found by its own test rather than
  by a user.
- The release workflow compares the tag against the version in `pyproject.toml` whenever the
  ref is a tag, not only on a `release` event. Every release since 0.3.0 was published by
  dispatching the workflow from a tag, which is the path the check was not covering: it was
  skipped, the upload went ahead, and a tag disagreeing with `pyproject.toml` would have
  reached the index unnoticed. A dispatch from a branch still skips it, because there the ref
  is a branch name and there is nothing to compare.
- The test suite the sdist ships can be run from the sdist. `MANIFEST.in` prunes `.github`
  and `scripts` and includes `tests`, so three test modules travelled to a place where what
  they read does not exist; two of them failed at import, and a collection error stops the
  whole run, so unpacking the sdist and running `pytest` executed no tests at all. They skip
  with the reason now, and still run in a checkout, where they are the ones doing the work.

## [0.5.0] - 2026-09-07

### Minor
- Standalone executables. Every release now carries one file per platform that brings its own
  Python — Linux, Windows, macOS on Apple Silicon and macOS on Intel — so the tool runs on a
  machine with no Python and no pip. `scripts/build_executables.py` builds one with
  PyInstaller and wraps it with the licence in a tar.gz or a zip named for the version and the
  architecture, keeping the executable bit that is the difference between a download that runs
  and one that answers "Permission denied". The `sql` extra is built in on purpose: someone
  running a binary has no way to add an extra afterwards, so leaving it out would have made
  database sources permanently unreachable there. The dashboard is not included and still
  needs a Python install.
- PyInstaller cannot cross-compile, so `--platform` checks that the machine is the one being
  asked for instead of pretending to target it, and the workflow takes its four binaries from
  four runners. Each one is run before it is uploaded: `--help`, a comparison, a Parquet
  comparison, and `rules`, which is what proves the bundled rules file is actually in there.
- `datasemver dvc` compares the datasets DVC reports as changed between two revisions. DVC
  keeps data out of git — a commit records a `.dvc` pointer holding a hash, and the bytes live
  in a cache or a remote — so the previous version cannot be read with `git show` the way the
  pull request script reads it. It is fetched with `dvc get` instead. Renamed datasets are read
  under each of their two names; added and deleted ones are reported as skipped, with the
  reason. `--json` and `--output` give the run as structured data or as a Markdown report, and
  the version each comparison starts from is read from the `.version` sidecar in the base
  revision, so a bump continues from the last one rather than restarting at `0.0.0`.
- DVC is never imported. It is run as a command, so it can live in a different environment and
  DataSemver still installs and runs without it. The two failures a first-time user hits — no
  DVC on PATH, and data that was never pulled — are translated into sentences that name
  `pip install dvc` and `dvc pull`; DVC reports the second as "unexpected error", which reads
  like a bug rather than a missing pull.

### Patch
- The CLI no longer dies when its output is redirected on Windows. Rich reaches for the
  pre-VT Windows console API whenever it cannot confirm the terminal understands escape
  sequences, and it cannot confirm that through a pipe, because `GetConsoleMode` fails on a
  pipe handle. It then called that API on the pipe: `datasemver rules | findstr x` ended in
  `OSError: [Errno 22] Invalid argument`. The suite never saw it because the test runner
  replaces stdout with an object that has no file descriptor at all.
- Errors printed by the CLI no longer lose anything inside square brackets. Rich read them as
  style tags, so the advice for reading a database arrived as `pip install "datasemver"` —
  which installs the wrong thing — instead of `pip install "datasemver[sql]"`. Every error the
  CLI prints went through that same line.
- Tests for the paths and text that behave differently by operating system: directory names
  with spaces, with accents and outside Latin-1, a changelog written to and prepended in such
  a path, a column name outside Latin-1 travelling from a CSV header into a changelog entry,
  a SQLite file opened from an accented directory, and a file whose lines end the way Windows
  writes them. They run on all three systems in CI, which is the point: none of them fails on
  the machine the code is written on.
- Reviewing the code for the same class of problem found nothing to change. Every read and
  write already names its encoding, so a Windows default of cp1252 never applies; there is no
  `chmod`, no `os.name` branch and no `shell=True`; and Rich has not used colorama since it
  began driving the Windows console API itself.
- The Trusted Publishing setup the release workflow depends on is checked by the suite rather
  than by the next release. It is authenticated by a handful of YAML lines nothing else reads:
  a `password:` restored from an older example would disable the attestations the action
  produces while still uploading successfully, a dropped `id-token: write` fails the job, and
  a renamed environment fails it in a way that reads like a misconfigured index rather than a
  typo in this repository. Both READMEs now say publishing needs no stored token and point at
  the setup each index is given once.

## [0.4.0] - 2026-09-06

### Minor
- A source can be a database table rather than a file. The connection URL names the database
  and the fragment names the table, `sqlite:///snapshots.db#customers`, because a fragment is
  not something a SQLAlchemy URL uses and so cannot collide with anything the URL already
  means. SQLite needs no driver; the `sql` extra adds SQLAlchemy, psycopg2 and PyMySQL.
- The dispatch lives in `load_frame` rather than in the CLI, so the Python API, the dashboard
  and the pull request script read databases too without any of them learning what a
  connection URL is.
- `postgres://` and a bare `mysql://` are rewritten on the way through. The first lost its
  alias in SQLAlchemy 2 and fails with "Can't load plugin", which says nothing about the
  scheme; the second resolves to MySQLdb rather than the PyMySQL the extra installs. Both are
  the URL every tutorial prints. A driver named explicitly is never rewritten.
- Passwords are removed before the source reaches a report. It is rendered into changelog
  entries, pull request comments and `--json`, and a connection string carries a password.
  The redaction has its own fallback so that a URL too malformed to parse is still reported
  without its credentials.
- Whole tables only: no views, no queries, no schema qualification. The whole table is read,
  because the profile compares row counts and column statistics and a partial read would
  describe the query instead of the dataset. Types come from the database rather than being
  inferred, so a column declared `TEXT` stays text even when every value looks numeric.

### Patch
- The coverage badge is gone, because it read `unknown`. Nothing was ever uploaded: the
  workflow passed a `CODECOV_TOKEN` that does not exist, the action logged `Token required`,
  and `fail_ci_if_error: false` turned that into a green step. A badge that claims nothing
  while looking like it claims something is worse than no badge, and a step that always
  fails quietly is worse than one that is skipped. The upload now runs only when a token is
  configured, and `CONTRIBUTING` says how to configure one. The 85% floor is enforced in
  `pyproject.toml` either way, which is where the guarantee actually lives.

## [0.3.0] - 2026-09-05

### Minor
- A project site at <https://izanvil.github.io/datasemver/>, English at the root and Spanish
  at `/es/`. It answers "what is this and why would I want it" for someone who has not
  already decided to read a README. The hero is the real terminal capture rather than a
  reconstruction of one in markup, which is both more honest and less work. Both colour
  schemes are supported, since a page that only exists in the dark meets half its readers on
  the wrong footing.
- The page is served from an orphan `gh-pages` branch rather than from `docs/` on `main`.
  A package repository should read as a package repository, and the composition of a
  marketing page in its tree works against that. The captures stay on `main` and are
  referenced by absolute URL, so nothing is duplicated and the page cannot drift from the
  documentation.
- `Homepage` in the package metadata now points at the site; `Repository` still points at
  the repository.

### Patch
- Reading a dataset is roughly twice as fast, with the report unchanged down to the byte.
  Measuring first said the cost was not where it looked: profiling every column is 8% of a
  run and comparing two profiles does not register, while `infer_types` was most of it. It
  derived the stripped values separately inside each of the three candidate converters, so a
  column of plain text paid for the same full copy three times over, once per type it was
  never going to be. They are computed once and shared now.
- A column that cannot convert is rejected on a sample rather than on all of it. The check
  only ever rejects: a sample that passes proves nothing and the full check still runs, so
  the answer is identical to testing every value. A million rows of free text no longer have
  to be parsed as numbers before anyone can say they are not numbers. Two tests pin the
  soundness by putting the disqualifying value past the sample, where a check that trusted a
  passing sample would convert the column and lose it.
- On a pair of 60 MB files that is 18.1s to 8.5s end to end, and 7.2 MB/s to 15.2 MB/s.
- The suite runs on macOS and Windows as well as Linux. The matrix covered five versions of
  Python and one operating system, which made the supported-platform claim a claim rather
  than a check: this library reads files, sniffs line endings to choose a CSV delimiter, and
  shells out to git. Linux keeps the full version range and the other two take its ends,
  which is where a platform difference would surface. Nothing was broken, and now that is
  known rather than assumed.
- `.gitattributes` pins text files to LF, so a Windows checkout no longer rewrites the CSV
  and JSON fixtures to CRLF and leave the suite measuring the clone instead of the library.
  Reading CRLF was already correct and is verified rather than trusted.
- Releases publish through Trusted Publishing instead of an API token. The workflow mints a
  short-lived OIDC credential naming the repository, workflow file and environment it came
  from, and the index verifies that, so there is no long-lived publishing secret in the
  repository to leak, rotate or scope. PyPI had been saying as much in the release logs:
  the `attestations` the action produces were being discarded silently because an explicit
  password disables them. `id-token: write` is granted to the two publish jobs only.
- The dashboard reports an upload under the name it arrived with. It said
  `old.csv → new.csv` for every comparison, whatever the reader had actually sent, because
  the server names the file on disk and the report took its source from that path. The name
  travels alongside now rather than through the filesystem: nothing a caller sends reaches a
  path, the name has its directory components dropped and its length capped, and it is only
  ever rendered.
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

[Unreleased]: https://github.com/IzanVil/datasemver/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/IzanVil/datasemver/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/IzanVil/datasemver/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/IzanVil/datasemver/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/IzanVil/datasemver/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/IzanVil/datasemver/compare/v0.2.5...v0.3.0
[0.2.5]: https://github.com/IzanVil/datasemver/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/IzanVil/datasemver/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/IzanVil/datasemver/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/IzanVil/datasemver/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/IzanVil/datasemver/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/IzanVil/datasemver/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/IzanVil/datasemver/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/IzanVil/datasemver/releases/tag/v0.0.1
