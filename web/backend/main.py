"""FastAPI application backing the DataSemver dashboard.

The dashboard is a client of the library: it uploads or locates two dataset files, calls
`datasemver.analyze()` and returns the report untouched.
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from datasemver import __version__, analyze
from datasemver.core.analyzer import DEFAULT_VERSION
from datasemver.core.models import AnalysisReport
from datasemver.formats.loader import SUPPORTED_EXTENSIONS
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


class Meta(BaseModel):
    """Everything the frontend needs to configure itself."""

    version: str
    supported_extensions: list[str]
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
) -> AnalysisReport:
    """Compare two uploaded datasets and return the full analysis report."""
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

        return run_analysis(old_path, new_path, current_version, rules_path)


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
    allowed = allowed or SUPPORTED_EXTENSIONS
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{upload.filename or 'file'}' has an unsupported extension, "
                f"expected one of {sorted(allowed)}"
            ),
        )

    path = destination.with_suffix(suffix)
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
) -> AnalysisReport:
    """Call the library and translate its errors into HTTP responses."""
    with as_http_error():
        return analyze(old, new, rules=rules, current_version=current_version)


@contextmanager
def as_http_error():
    """Turn the library's input errors into 400 responses."""
    try:
        yield
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ANALYSIS_ERRORS as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _as_semver(version: str) -> str:
    """Pad a directory version such as `2` or `2.1` into a full semantic version."""
    parts = (version.split(".") + ["0", "0"])[:3]
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
