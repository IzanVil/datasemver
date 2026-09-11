# DataSemver dashboard

A small web front end for DataSemver: upload two versions of a dataset, or pick two
versions already sitting in a directory, and see the suggested bump, the classified
changes, the column comparison and the changelog entry.

The backend is FastAPI and imports `datasemver` as a library — no subprocess, no
duplicated logic. The frontend is plain HTML, CSS and JavaScript with no build step, so
there is nothing to compile and no `node_modules`.

```
datasemver_web/
├── backend/
│   ├── config.py     settings read from the environment
│   ├── history.py    discovery of versioned datasets on disk
│   └── main.py       FastAPI app and endpoints
└── frontend/
    ├── index.html    compare and history views
    ├── styles.css    responsive layout, light and dark
    ├── favicon.svg   the mark, carrying its own palette
    └── app.js        fetch calls and rendering
```

## Running it

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r requirements/web.txt

uvicorn datasemver_web.backend.main:app --reload
```

Open <http://127.0.0.1:8000>. The backend serves the frontend itself, so that single
command runs the whole dashboard; the interactive API docs are at
<http://127.0.0.1:8000/docs>.

The dashboard ships inside the `datasemver` distribution, so `pip install
"datasemver[web]"` is enough to run it — the commands above are the checkout route, for
working on it. Either way the app is addressed as `datasemver_web.backend.main`.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `DATASEMVER_DATASETS_DIR` | `./datasets` | Directory scanned by the history view |
| `DATASEMVER_MAX_UPLOAD_MB` | `25` | Size limit applied to every uploaded file, and to what a compressed one becomes |
| `DATASEMVER_FRONTEND_DIR` | `datasemver_web/frontend` | Static files served at `/` |

```bash
DATASEMVER_DATASETS_DIR=/data/snapshots uvicorn datasemver_web.backend.main:app --reload
```

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/meta` | Library version, supported extensions, profile suffix and upload limit |
| `POST` | `/api/diff` | Compare two uploaded files or profiles (`multipart/form-data`) |
| `POST` | `/api/profile` | Return the profile of one uploaded dataset |
| `GET` | `/api/history` | Versioned datasets found in the datasets directory |
| `GET` | `/api/history/{dataset}/diff` | Compare two versions already on disk |
| `GET` | `/` | The dashboard itself |

`POST /api/diff` takes the fields `old` and `new` (required files), `current_version`
(optional, default `0.0.0`), `rules` (optional YAML file overriding the defaults) and `key`
(optional, one column or several separated by commas). It returns the same report the CLI
prints with `--json`:

```bash
curl -X POST http://127.0.0.1:8000/api/diff \
  -F "old=@tests/fixtures/old.csv" \
  -F "new=@tests/fixtures/new.csv" \
  -F "current_version=1.4.2"
```

```json
{
  "bump": "major",
  "current_version": "1.4.2",
  "next_version": "2.0.0",
  "diff": { "...": "..." },
  "classified": [
    {
      "change": { "type": "column_removed", "description": "Column 'legacy_code' was removed" },
      "severity": "major",
      "rule": "column_removed"
    }
  ]
}
```

`GET /api/history/{dataset}/diff?old=1&new=2` compares two versions from the datasets
directory and accepts an optional `current_version`; without it, the version is taken from
the name of the older file (`v1` becomes `1.0.0`).

## Profiles, and the upload limit

Either side of a comparison may be a stored profile instead of a dataset. A profile is a few
hundred bytes describing megabytes, so this is how a comparison here reaches a version too
large to upload — or one whose file no longer exists anywhere:

```bash
# write one from the dataset you have
curl -X POST http://127.0.0.1:8000/api/profile \
  -F "dataset=@customers_v3.parquet" -o customers_v3.profile.json

# compare against it, however large the new side is
curl -X POST http://127.0.0.1:8000/api/diff \
  -F "old=@customers_v3.profile.json" \
  -F "new=@customers_v4.parquet"
```

A compressed dataset is measured twice: the bytes that arrive, and the bytes they turn into.
The second is the number that decides what reading the file costs — ordinary data compresses
about 344:1, so a quarter of a megabyte inside every stated limit can become most of a
gigabyte of dataframe — so a `.csv.gz` whose contents exceed the limit is refused with `413`
before anything parses it. The check stops one chunk past the limit, which is what keeps the
refusal cheaper than the upload it refuses.

The **Save profile** button does the first of those from the page, for the file chosen as the
new version. Only the compound `.profile.json` marks one: a plain `.json` is a dataset format
here and is read as data, which is why the two are never guessed between.

## Comparing rows

`key` names the column that identifies a row, or several separated by commas, and turns the
comparison into a row-level one: how many rows were added, removed and changed, and which
columns account for the changes.

```bash
curl -X POST http://127.0.0.1:8000/api/diff \
  -F "old=@old.csv" -F "new=@new.csv" -F "key=id"
```

It needs rows on both sides, so a key given against a stored profile is refused rather than
guessed at — a profile keeps none, and never will.

## Errors

Invalid input answers with a status code rather than a stack trace: `400` for an
unsupported extension, an unreadable dataset, a broken rules file, a malformed version, a key
that names no column or one repeated across rows, `413` for a file over the limit, and `404`
for a dataset or version that is not on disk.

## The datasets directory

The history view groups files by name and version, so name them `<name>_v<version>.<ext>`:

```
datasets/
├── customers_v1.csv
├── customers_v2.csv
├── customers_v3.csv
├── users_v1.json
└── users_v2.json
```

`customers.v2.csv` and `customers-v2.csv` work too, and versions can have several
components (`customers_v2.1.csv`). Files that do not match the pattern, or whose extension
DataSemver does not read, are listed as ignored instead of breaking the scan. The
repository ships a `datasets/` directory with samples so the view has something to show.

## Development

```bash
pytest tests/test_web.py
```

Those tests use FastAPI's `TestClient` and skip themselves when `fastapi` or `httpx` is
not installed, so the core suite still runs in an environment without the web extras.

The frontend has no build step: edit `index.html`, `styles.css` or `app.js` and reload the
page. `uvicorn --reload` restarts only on Python changes, which is all it needs to.
