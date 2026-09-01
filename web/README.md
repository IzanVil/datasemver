# DataSemver dashboard

A small web front end for DataSemver: upload two versions of a dataset, or pick two
versions already sitting in a directory, and see the suggested bump, the classified
changes, the column comparison and the changelog entry.

The backend is FastAPI and imports `datasemver` as a library — no subprocess, no
duplicated logic. The frontend is plain HTML, CSS and JavaScript with no build step, so
there is nothing to compile and no `node_modules`.

```
web/
├── backend/
│   ├── config.py     settings read from the environment
│   ├── history.py    discovery of versioned datasets on disk
│   └── main.py       FastAPI app and endpoints
└── frontend/
    ├── index.html    compare and history views
    ├── styles.css    responsive layout, light and dark
    └── app.js        fetch calls and rendering
```

## Running it

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r requirements-web.txt

uvicorn web.backend.main:app --reload
```

Open <http://127.0.0.1:8000>. The backend serves the frontend itself, so that single
command runs the whole dashboard; the interactive API docs are at
<http://127.0.0.1:8000/docs>.

Run it from the repository root, not from `web/backend/`: the app is a package
(`web.backend.main`) and its imports resolve from there.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `DATASEMVER_DATASETS_DIR` | `./datasets` | Directory scanned by the history view |
| `DATASEMVER_MAX_UPLOAD_MB` | `25` | Size limit applied to every uploaded file |
| `DATASEMVER_FRONTEND_DIR` | `web/frontend` | Static files served at `/` |

```bash
DATASEMVER_DATASETS_DIR=/data/snapshots uvicorn web.backend.main:app --reload
```

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/meta` | Library version, supported extensions and upload limit |
| `POST` | `/api/diff` | Compare two uploaded files (`multipart/form-data`) |
| `GET` | `/api/history` | Versioned datasets found in the datasets directory |
| `GET` | `/api/history/{dataset}/diff` | Compare two versions already on disk |
| `GET` | `/` | The dashboard itself |

`POST /api/diff` takes the fields `old` and `new` (required files), `current_version`
(optional, default `0.0.0`) and `rules` (optional YAML file overriding the defaults). It
returns the same report the CLI prints with `--json`:

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

Invalid input answers with a status code rather than a stack trace: `400` for an
unsupported extension, an unreadable dataset, a broken rules file or a malformed version,
`413` for a file over the limit, and `404` for a dataset or version that is not on disk.

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
