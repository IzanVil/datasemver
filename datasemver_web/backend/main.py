"""FastAPI application backing the DataSemver dashboard.

The dashboard is a client of the library: it uploads or locates two dataset files, calls
`datasemver.analyze()` and returns the report untouched.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from datasemver import __version__
from datasemver.core.analyzer import DEFAULT_VERSION, analyze_schemas
from datasemver.core.models import AnalysisReport, Change, DatasetSchema
from datasemver.core.profile import PROFILE_SUFFIX, Profile, is_profile, read_profile
from datasemver.core.rows import compare_rows
from datasemver.formats.loader import (
    SUPPORTED_EXTENSIONS,
    describe_source,
    load_frame,
    schema_from_frame,
)
from datasemver.rules.engine import RuleError
from datasemver.utils.version import InvalidVersionError

from .config import Settings, get_settings
from .history import DatasetNotFoundError, History, resolve_file, scan_datasets

app = FastAPI(
    title="DataSemver dashboard",
    description="Compare two versions of a dataset and see the version bump they deserve.",
    version=__version__,
)

ANALYSIS_ERRORS = (ValueError, RuleError, InvalidVersionError)
CHUNK_BYTES = 1024 * 1024
MAX_NAME_CHARS = 120

# A stored profile is accepted wherever a dataset is. It is a few hundred bytes where the
# dataset is megabytes, which is what lets a comparison here reach a version far past the
# upload limit -- or one whose file no longer exists anywhere.
UPLOAD_EXTENSIONS = SUPPORTED_EXTENSIONS | {PROFILE_SUFFIX}


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
        supported_extensions=sorted(SUPPORTED_EXTENSIONS),
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
                rules, workdir / "rules", settings, allowed={".yaml", ".yml"}
            )

        return run_analysis(
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
        with as_http_error():
            schema, _ = _side(path, reported_name(dataset))
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
) -> Path:
    """Persist an upload to disk, enforcing its extension and the size limit."""
    allowed = allowed or UPLOAD_EXTENSIONS
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
    written = _copy_within_limit(upload, path, settings.max_upload_bytes)

    if written > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"'{upload.filename}' is larger than {settings.max_upload_mb} MB",
        )
    if written == 0:
        raise HTTPException(status_code=400, detail=f"'{upload.filename}' is empty")
    return path


def _suffix_of(filename: str) -> str:
    """The extension an upload is dispatched on, keeping a profile's two.

    `Path("x.profile.json").suffix` is `.json`, which is a dataset format here: a profile
    stored under the server's own name would be read back as an array of records rather than
    as a profile. The compound suffix is the whole point of the name, so it is kept.
    """
    lowered = filename.lower()
    if lowered.endswith(PROFILE_SUFFIX):
        return PROFILE_SUFFIX
    return Path(lowered).suffix


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
    return schema_from_frame(frame, source=name or describe_source(path)), frame


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
