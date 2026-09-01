"""Runtime configuration, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_DATASETS_DIR = "./datasets"
DEFAULT_MAX_UPLOAD_MB = 25.0


@dataclass(frozen=True)
class Settings:
    """Settings of the dashboard backend."""

    datasets_dir: Path
    max_upload_bytes: int
    frontend_dir: Path

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
    return Settings(
        datasets_dir=datasets_dir.expanduser().resolve(),
        max_upload_bytes=int(max_upload_mb * 1024 * 1024),
        frontend_dir=frontend_dir.expanduser().resolve(),
    )
