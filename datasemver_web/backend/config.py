"""Runtime configuration, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_DATASETS_DIR = "./datasets"
DEFAULT_MAX_UPLOAD_MB = 25.0
# Profiling a column costs a few milliseconds whatever it holds, so the width of a file is the
# one number its size says nothing about: 165 kB of header is twenty thousand columns and a
# minute of work. The dashboard stops at this many; the command line does not.
DEFAULT_MAX_COLUMNS = 2000
MAX_COLUMNS_ENV_VAR = "DATASEMVER_MAX_COLUMNS"
# Extra host names the dashboard answers to, comma separated, or `*` for any. See
# `datasemver_web.backend.main.host_allowed` for what it answers to without being told.
ALLOWED_HOSTS_ENV_VAR = "DATASEMVER_ALLOWED_HOSTS"


@dataclass(frozen=True)
class Settings:
    """Settings of the dashboard backend."""

    datasets_dir: Path
    max_upload_bytes: int
    frontend_dir: Path
    allowed_hosts: frozenset[str] = frozenset()
    max_columns: int = DEFAULT_MAX_COLUMNS

    @property
    def max_upload_mb(self) -> float:
        return round(self.max_upload_bytes / (1024 * 1024), 2)


@lru_cache
def get_settings() -> Settings:
    """Build the settings once per process."""
    datasets_dir = Path(os.environ.get("DATASEMVER_DATASETS_DIR", DEFAULT_DATASETS_DIR))
    max_upload_mb = float(os.environ.get("DATASEMVER_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB))
    frontend_dir = Path(
        os.environ.get("DATASEMVER_FRONTEND_DIR", Path(__file__).resolve().parents[1] / "frontend")
    )
    allowed_hosts = frozenset(
        name.strip().lower()
        for name in os.environ.get(ALLOWED_HOSTS_ENV_VAR, "").split(",")
        if name.strip()
    )
    return Settings(
        datasets_dir=datasets_dir.expanduser().resolve(),
        max_upload_bytes=int(max_upload_mb * 1024 * 1024),
        frontend_dir=frontend_dir.expanduser().resolve(),
        allowed_hosts=allowed_hosts,
        max_columns=int(os.environ.get(MAX_COLUMNS_ENV_VAR, DEFAULT_MAX_COLUMNS)),
    )
