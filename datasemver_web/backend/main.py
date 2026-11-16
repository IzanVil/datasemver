"""FastAPI application backing the DataSemver dashboard.

The dashboard is a client of the library: it uploads or locates two dataset files, calls
`datasemver.analyze()` and returns the report untouched.
"""

from __future__ import annotations

import gzip
import ipaddress
import tempfile
import zipfile
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from datasemver import __version__
from datasemver.core.analyzer import DEFAULT_VERSION, analyze_schemas
from datasemver.core.models import AnalysisReport, Change, DatasetSchema
from datasemver.core.profile import PROFILE_SUFFIX, Profile, is_profile, read_profile
from datasemver.core.rows import compare_rows
from datasemver.formats.excel import EXCEL_EXTENSIONS
from datasemver.formats.loader import (
    FEATHER_EXTENSIONS,
    PARQUET_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    dataset_suffix,
    describe_source,
    load_frame,
    schema_from_frame,
)
from datasemver.rules.engine import RuleError
from datasemver.utils.version import InvalidVersionError

from .arrow_ipc import NotArrowFile, decoded_size
from .config import ALLOWED_HOSTS_ENV_VAR, MAX_COLUMNS_ENV_VAR, Settings, get_settings
from .history import DatasetNotFoundError, History, resolve_file, scan_datasets

app = FastAPI(
    title="DataSemver dashboard",
    description="Compare two versions of a dataset and see the version bump they deserve.",
    version=__version__,
)

# The dashboard builds every node it shows from text and loads nothing from anywhere else, so
# a page that is allowed only itself loses nothing. It may be framed by itself and by nothing
# else, which is what the capture script does to see it at the width of a phone. `/docs` and
# `/redoc` are FastAPI's own and pull their scripts from a CDN, which is why they are the one
# exception.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-src 'self'; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'self'"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}
API_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def host_allowed(header: str | None, extra: frozenset[str] = frozenset()) -> bool:
    """Whether the `Host` a request names is one this dashboard should answer to.

    A page on any website can make the browser send requests to `127.0.0.1`, and a hostname
    under its control that resolves there after the page has loaded lets it read the answers
    too -- the attack is called DNS rebinding, and what gives it away is that the request
    still names the attacker's host. So `localhost` and every IP address are answered, since
    nobody can rebind a name that is not one, and any other name only when it was asked for in
    `DATASEMVER_ALLOWED_HOSTS`. A request with no `Host` at all is not a browser's.
    """
    if not header:
        return True
    host = header.strip().lower()
    if host.startswith("["):  # an IPv6 literal, with or without a port: [::1]:8000
        name = host[1 : host.find("]")] if "]" in host else host
    elif host.count(":") == 1:
        name = host.partition(":")[0]
    else:
        name = host
    if "*" in extra or name in extra or name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


@app.middleware("http")
async def guard_the_browser(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Refuse a request that arrived under a name that is not the dashboard's, and say what
    the browser may do with every answer: nothing but show it, from here."""
    if not host_allowed(request.headers.get("host"), get_settings().allowed_hosts):
        response: Response = PlainTextResponse(
            f"Invalid host header. To serve the dashboard under that name, set "
            f"{ALLOWED_HOSTS_ENV_VAR} to it.",
            status_code=400,
        )
    else:
        response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    if not request.url.path.startswith(API_DOCS_PATHS):
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    if request.url.path.startswith("/api/"):
        # A comparison is the contents of someone's datasets; none of it is for a shared cache.
        response.headers["Cache-Control"] = "no-store"
    return response


ANALYSIS_ERRORS = (ValueError, RuleError, InvalidVersionError)
CHUNK_BYTES = 1024 * 1024
MAX_NAME_CHARS = 120
# A rules file is YAML the server parses, not a dataset, and a few kilobytes is already a
# large rule set. Held far below the dataset limit so a rules upload is never a way to spend
# the whole of it on parsing -- the alias expansion a loader refuses is only one way a small
# document asks for a lot of work, and the bytes are the part the cap can see.
MAX_RULES_BYTES = 256 * 1024

# A stored profile is accepted wherever a dataset is. It is a few hundred bytes where the
# dataset is megabytes, which is what lets a comparison here reach a version far past the
# upload limit -- or one whose file no longer exists anywhere.
# The dashboard takes every format the library reads, compressed ones included. They are
# the reason the limit is enforced twice: on the bytes that arrive, and again on what they
# become, since those are different numbers for a `.gz` and only the second one decides what
# reading the file costs.
COMPRESSED_EXTENSIONS = {suffix for suffix in SUPPORTED_EXTENSIONS if suffix.endswith(".gz")}
UPLOAD_DATASET_EXTENSIONS = SUPPORTED_EXTENSIONS
UPLOAD_EXTENSIONS = UPLOAD_DATASET_EXTENSIONS | {PROFILE_SUFFIX}

# A gzip file is held to the upload limit once decompressed. The columnar formats and workbooks
# are already compressed, on purpose and by a lot, so the same ceiling would refuse ordinary
# files: they are held to a multiple of it instead. Parquet runs three to ten times smaller
# than the table it holds and a run of equal values far more, which is the point -- 200 million
# rows of one value is 850 kB of upload, accepted by every limit above and 1.6 GB of dataframe.
DECODED_FACTOR = 20
BATCH_ROWS = 64 * 1024


class Meta(BaseModel):
    """Everything the frontend needs to configure itself."""

    version: str
    supported_extensions: list[str]
    # Reported apart from the dataset formats rather than mixed into them: a profile is not a
    # format the tool reads, it is the summary the tool writes, and a frontend that offered it
    # as an option under "supported formats" would be saying something false.
    profile_suffix: str
    datasets_dir: str
    max_upload_mb: float
    default_version: str


@app.get("/api/meta", response_model=Meta, tags=["meta"])
def meta() -> Meta:
    """Report the library version and the limits the frontend should respect."""
    settings = get_settings()
    return Meta(
        version=__version__,
        supported_extensions=sorted(UPLOAD_DATASET_EXTENSIONS),
        profile_suffix=PROFILE_SUFFIX,
        datasets_dir=str(settings.datasets_dir),
        max_upload_mb=settings.max_upload_mb,
        default_version=DEFAULT_VERSION,
    )


@app.post("/api/diff", response_model=AnalysisReport, tags=["diff"])
async def diff_uploads(
    old: UploadFile = File(..., description="Previous version of the dataset."),
    new: UploadFile = File(..., description="New version of the dataset."),
    current_version: str = Form(DEFAULT_VERSION),
    rules: UploadFile | None = File(None, description="Optional YAML rules file."),
    key: str = Form("", description="Comma-separated columns identifying a row."),
) -> AnalysisReport:
    """Compare two uploaded datasets and return the full analysis report.

    Either side may be a stored profile rather than a dataset, which is what lets a
    comparison here reach a version whose file is far past the upload limit, or gone.
    """
    settings = get_settings()

    with tempfile.TemporaryDirectory() as directory:
        workdir = Path(directory)
        old_path = await store_upload(old, workdir / "old", settings)
        new_path = await store_upload(new, workdir / "new", settings)
        rules_path = None
        if rules is not None and rules.filename:
            rules_path = await store_upload(
                rules,
                workdir / "rules",
                settings,
                allowed={".yaml", ".yml"},
                limit=MAX_RULES_BYTES,
            )

        # Off the event loop: an analysis is seconds of work for a large file, and run where the
        # server listens it would leave every other request waiting for it.
        return await run_in_threadpool(
            run_analysis,
            old_path,
            new_path,
            current_version,
            rules_path,
            names=(reported_name(old), reported_name(new)),
            key=_key_columns(key),
        )


def _key_columns(raw: str) -> list[str] | None:
    """The key as a list, or None when the field was left alone.

    Written as text because that is what a form sends, and split on commas so a composite key
    is one field rather than a widget someone has to discover.
    """
    columns = [part.strip() for part in raw.split(",") if part.strip()]
    return columns or None


@app.post("/api/profile", response_model=Profile, tags=["profile"])
async def profile_upload(
    dataset: UploadFile = File(..., description="Dataset to profile."),
) -> Profile:
    """Return the profile of an uploaded dataset, as the file `datasemver profile` writes.

    A few hundred bytes describing megabytes: keep it beside the data and the next comparison
    needs only the new version. This is the dashboard's half of that, so a profile can be
    produced by someone who never touches the command line.
    """
    settings = get_settings()
    with tempfile.TemporaryDirectory() as directory:
        path = await store_upload(dataset, Path(directory) / "dataset", settings)
        return await run_in_threadpool(_profile_of, path, reported_name(dataset))


def _profile_of(path: Path, name: str) -> Profile:
    with as_http_error():
        schema, _ = _side(path, name)
    return Profile(dataset=schema)


@app.get("/api/history", response_model=History, tags=["history"])
def history() -> History:
    """List the versioned datasets found in the configured directory."""
    return scan_datasets(get_settings().datasets_dir)


@app.get("/api/history/{dataset}/diff", response_model=AnalysisReport, tags=["history"])
def diff_history(
    dataset: str,
    old: str,
    new: str,
    current_version: str | None = None,
) -> AnalysisReport:
    """Compare two versions of a dataset that already live in the datasets directory."""
    settings = get_settings()
    try:
        old_path = resolve_file(settings.datasets_dir, dataset, old)
        new_path = resolve_file(settings.datasets_dir, dataset, new)
    except DatasetNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return run_analysis(old_path, new_path, current_version or _as_semver(old), None)


async def store_upload(
    upload: UploadFile,
    destination: Path,
    settings: Settings,
    allowed: set[str] | None = None,
    limit: int | None = None,
) -> Path:
    """Persist an upload to disk, enforcing its extension and the size limit.

    `limit` lets a rules file be held to a much smaller ceiling than a dataset: it is YAML
    the server parses rather than data it loads, and a few kilobytes is already a large rule
    set, so there is no reason it should be able to spend the whole dataset budget.
    """
    allowed = allowed or UPLOAD_EXTENSIONS
    limit = settings.max_upload_bytes if limit is None else limit
    suffix = _suffix_of(upload.filename or "")
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{upload.filename or 'file'}' has an unsupported extension, "
                f"expected one of {sorted(allowed)}"
            ),
        )

    # Concatenated rather than `with_suffix`, whose rules about a compound suffix have
    # moved between the Python versions this supports.
    path = destination.with_name(destination.name + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = await run_in_threadpool(_copy_within_limit, upload, path, limit)

    if written > limit:
        raise HTTPException(
            status_code=413,
            detail=f"'{upload.filename}' is larger than {_mb(limit)} MB",
        )
    if written == 0:
        raise HTTPException(status_code=400, detail=f"'{upload.filename}' is empty")

    ceiling = _decoded_limit(suffix, limit)
    if await run_in_threadpool(
        _expands_past_limit, path, suffix, ceiling, upload.filename or "file"
    ):
        path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail=f"'{upload.filename}' holds more than {_mb(ceiling)} MB once decompressed",
        )
    return path


def _mb(byte_count: int) -> float:
    """Bytes as megabytes, rounded the way the settings report their own limit."""
    return round(byte_count / (1024 * 1024), 2)


def _suffix_of(filename: str) -> str:
    """The extension an upload is dispatched on, keeping a profile's two.

    `Path("x.profile.json").suffix` is `.json`, which is a dataset format here: a profile
    stored under the server's own name would be read back as an array of records rather than
    as a profile. The compound suffix is the whole point of the name, so it is kept.
    """
    lowered = filename.lower()
    if lowered.endswith(PROFILE_SUFFIX):
        return PROFILE_SUFFIX
    # The library's own definition, so `.csv.gz` dispatches as `.csv.gz` here as well. It
    # used to be `Path(...).suffix`, which made every compressed name arrive as `.gz` and
    # be refused -- a stopgap for the expansion the upload limit could not see, and now
    # `_expands_past_limit` sees it.
    return dataset_suffix(lowered)


def _copy_within_limit(upload: UploadFile, path: Path, limit: int) -> int:
    """Write an upload to disk, stopping as soon as it is known to be over the limit.

    Checking the size after the copy makes the limit advisory: the whole body reaches disk
    first, so a large enough upload fills the volume no matter what the limit says. Reading
    one chunk past the limit is enough to reject it, and is all that gets written.
    """
    written = 0
    with path.open("wb") as handle:
        while True:
            # never read further past the limit than the one byte that proves it was passed
            chunk = upload.file.read(min(CHUNK_BYTES, limit - written + 1))
            if not chunk:
                break
            written += len(chunk)
            handle.write(chunk)
            if written > limit:
                break
    if written > limit:
        path.unlink(missing_ok=True)
    return written


def _decoded_limit(suffix: str, limit: int) -> int:
    """What a file of this format may hold once decompressed or decoded.

    A gzip file is held to the upload limit itself. The columnar formats and workbooks are
    compressed by design, so they get `DECODED_FACTOR` times that.
    """
    return limit if suffix in COMPRESSED_EXTENSIONS else limit * DECODED_FACTOR


def _expands_past_limit(path: Path, suffix: str, limit: int, name: str) -> bool:
    """Whether an upload becomes more than `limit` bytes once decompressed or decoded.

    The size the cap counts is the size that arrives, and that is not the number that decides
    what reading the file costs: ordinary repetitive data compresses about 344:1 and a crafted
    file reaches roughly 1030:1, so a quarter of a megabyte within every limit the dashboard
    states can become most of a gigabyte of dataframe. Parquet is worse, since a run of equal
    values is stored as the value and a count: 850 kB of upload holds 200 million rows.

    Every answer is reached under the rule `_copy_within_limit` already follows -- read one
    step past the limit and no further -- so it costs one chunk, one batch or one directory
    listing of memory whatever the file claims to hold, and nothing has tried to parse it yet.
    A file one of these cannot open is left to the reader, which words that failure better.
    """
    if suffix in COMPRESSED_EXTENSIONS:
        return _gzip_expands_past(path, limit, name)
    if suffix in PARQUET_EXTENSIONS:
        return _parquet_decodes_past(path, limit)
    if suffix in FEATHER_EXTENSIONS:
        return _feather_decodes_past(path, limit)
    if suffix in EXCEL_EXTENSIONS:
        return _workbook_expands_past(path, limit)
    return False


def _gzip_expands_past(path: Path, limit: int, name: str) -> bool:
    total = 0
    try:
        with gzip.open(path, "rb") as stream:
            while chunk := stream.read(min(CHUNK_BYTES, limit - total + 1)):
                total += len(chunk)
                if total > limit:
                    return True
    except (OSError, EOFError) as error:
        raise HTTPException(
            status_code=400, detail=f"'{name}' could not be decompressed: {error}"
        ) from error
    return False


def _parquet_decodes_past(path: Path, limit: int) -> bool:
    """Decode a Parquet file a batch at a time until it is known to be past `limit`."""
    try:
        import pyarrow.parquet as parquet

        total = 0
        file = parquet.ParquetFile(path)
        try:
            for batch in file.iter_batches(batch_size=BATCH_ROWS):
                total += batch.nbytes
                if total > limit:
                    return True
        finally:
            file.close()
    except Exception:  # unreadable here is the reader's to report
        return False
    return False


def _feather_decodes_past(path: Path, limit: int) -> bool:
    """Whether a Feather file holds more than `limit` bytes once decoded.

    Read from the file's own metadata, which says how long every buffer is once decompressed,
    so nothing is decompressed to find out. Decoding a batch at a time, as Parquet is measured,
    is not enough here: a batch is the unit Arrow decodes, and a file written as one batch
    would be gigabytes of table before there was anything to compare with the limit.
    """
    try:
        return decoded_size(path, stop_after=limit) > limit
    except NotArrowFile:
        # The first Feather format, which has no compression: it is as large as it looks.
        return False
    except Exception:  # metadata this cannot follow; measure it the slower way
        return _feather_batches_decode_past(path, limit)


def _feather_batches_decode_past(path: Path, limit: int) -> bool:
    """Decode a Feather file a record batch at a time until it is known to be past `limit`."""
    try:
        import pyarrow.ipc as ipc

        total = 0
        with ipc.open_file(path) as reader:
            for index in range(reader.num_record_batches):
                total += reader.get_batch(index).nbytes
                if total > limit:
                    return True
    except Exception:  # unreadable here is the reader's to report
        return False
    return False


def _workbook_expands_past(path: Path, limit: int) -> bool:
    """Whether a workbook's parts add up to more than `limit` once inflated.

    A workbook is a zip archive of XML, and the sizes are in its directory: asking for them
    inflates nothing. They are the sizes a reader is held to as well, since it stops at what
    an entry declares.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            return sum(entry.file_size for entry in archive.infolist()) > limit
    except (zipfile.BadZipFile, OSError):
        return False


def run_analysis(
    old: Path,
    new: Path,
    current_version: str,
    rules: Path | None,
    names: tuple[str, str] | None = None,
    key: list[str] | None = None,
) -> AnalysisReport:
    """Call the library and translate its errors into HTTP responses.

    `names` reports an upload under the name it arrived with. The file on disk is named by
    the server, deliberately, so that nothing a caller sends reaches a path; without this
    the report would say `old.csv` no matter what the reader actually uploaded.
    """
    with as_http_error():
        old_schema, old_frame = _side(old, names[0] if names else None)
        new_schema, new_frame = _side(new, names[1] if names else None)
        extra = _row_changes(old_frame, new_frame, key, old_schema.source, new_schema.source)
        return analyze_schemas(
            old_schema,
            new_schema,
            rules=rules,
            current_version=current_version,
            extra_changes=extra,
        )


def _side(path: Path, name: str | None) -> tuple[DatasetSchema, Any]:
    """One side of a comparison: its profile, and its rows when it has any.

    A stored profile has no rows and never will, which is the whole reason it is small enough
    to keep. So it comes back with `None` where a dataset comes back with its frame, and the
    row comparison below reads that rather than trying to load a file that describes one.
    """
    if is_profile(path):
        return read_profile(path), None
    frame = load_frame(path)
    _refuse_a_wide_table(frame.shape[1], name or describe_source(path))
    return schema_from_frame(frame, source=name or describe_source(path)), frame


def _refuse_a_wide_table(columns: int, name: str) -> None:
    """Refuse a table too wide to profile in the time a request should take."""
    limit = get_settings().max_columns
    if columns > limit:
        raise HTTPException(
            status_code=413,
            detail=(
                f"'{name}' has {columns} columns, and the dashboard reads up to {limit} "
                f"({MAX_COLUMNS_ENV_VAR} raises that). The command line has no such limit."
            ),
        )


def _row_changes(
    old_frame: Any, new_frame: Any, key: list[str] | None, old_name: str, new_name: str
) -> list[Change]:
    """Match rows on the key, when one was given and both sides have rows to match."""
    if not key:
        return []
    if old_frame is None or new_frame is None:
        raise HTTPException(
            status_code=400,
            detail="comparing rows needs both datasets; a stored profile keeps none",
        )
    return compare_rows(old_frame, new_frame, key, old_name, new_name)


def reported_name(upload: UploadFile) -> str:
    """The name to show an upload under: never a path, never unbounded.

    `Path(...).name` drops every directory component, so a filename dressed up as a path
    reports as its last segment. The result is only ever rendered, never opened.
    """
    name = Path(upload.filename or "").name.strip()
    return name[:MAX_NAME_CHARS] or "uploaded"


@contextmanager
def as_http_error() -> Iterator[None]:
    """Turn the library's input errors into 400 responses."""
    try:
        yield
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ANALYSIS_ERRORS as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _as_semver(version: str) -> str:
    """Pad a directory version such as `2` or `2.1` into a full semantic version."""
    parts = [*version.split("."), "0", "0"][:3]
    return ".".join(parts)


def mount_frontend(application: FastAPI, settings: Settings | None = None) -> None:
    """Serve the static frontend at the root, when it is present."""
    settings = settings or get_settings()
    if not settings.frontend_dir.is_dir():
        return

    index = settings.frontend_dir / "index.html"

    @application.get("/", include_in_schema=False)
    def serve_index() -> FileResponse:
        return FileResponse(index)

    application.mount(
        "/",
        StaticFiles(directory=settings.frontend_dir, html=True),
        name="frontend",
    )


mount_frontend(app)
