import io

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

import web.backend.main as main
from web.backend.config import Settings
from web.backend.history import scan_datasets
from web.backend.main import app

pytestmark = pytest.mark.web


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def datasets_dir(tmp_path, old_csv, new_csv, monkeypatch):
    directory = tmp_path / "datasets"
    directory.mkdir()
    (directory / "customers_v1.csv").write_bytes(old_csv.read_bytes())
    (directory / "customers_v2.csv").write_bytes(new_csv.read_bytes())
    (directory / "notes.txt").write_text("ignored", encoding="utf-8")

    settings = Settings(
        datasets_dir=directory,
        max_upload_bytes=1024 * 1024,
        frontend_dir=tmp_path / "frontend",
    )
    monkeypatch.setattr("web.backend.main.get_settings", lambda: settings)
    return directory


def upload(client, old_path, new_path, **data):
    with old_path.open("rb") as old, new_path.open("rb") as new:
        return client.post(
            "/api/diff",
            files={
                "old": (old_path.name, old, "text/csv"),
                "new": (new_path.name, new, "text/csv"),
            },
            data=data,
        )


def test_meta_reports_supported_extensions(client):
    payload = client.get("/api/meta").json()

    assert ".csv" in payload["supported_extensions"]
    assert ".parquet" in payload["supported_extensions"]
    assert payload["default_version"] == "0.0.0"


def test_diff_uploads_returns_the_report(client, old_csv, new_csv):
    response = upload(client, old_csv, new_csv, current_version="1.4.2")
    payload = response.json()

    assert response.status_code == 200
    assert payload["bump"] == "major"
    assert payload["next_version"] == "2.0.0"
    assert payload["diff"]["new"]["row_count"] == 10
    rules = {item["rule"] for item in payload["classified"]}
    assert {"column_removed", "type_changed_incompatible"} <= rules


def test_diff_uploads_accepts_json_and_parquet(client, old_json, new_json, old_parquet):
    assert upload(client, old_json, new_json).status_code == 200
    assert upload(client, old_parquet, old_parquet).json()["bump"] is None


def test_diff_uploads_with_custom_rules(client, old_csv, new_csv, tmp_path):
    rules = tmp_path / "custom.yaml"
    rules.write_text("minor:\n  - column_removed\n", encoding="utf-8")

    with old_csv.open("rb") as old, new_csv.open("rb") as new, rules.open("rb") as rule_file:
        response = client.post(
            "/api/diff",
            files={
                "old": (old_csv.name, old, "text/csv"),
                "new": (new_csv.name, new, "text/csv"),
                "rules": (rules.name, rule_file, "application/yaml"),
            },
            data={"current_version": "1.0.0"},
        )

    assert response.json()["bump"] == "minor"


def test_diff_rejects_unsupported_extension(client, old_csv, tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("nope", encoding="utf-8")

    response = upload(client, other, old_csv)

    assert response.status_code == 400
    assert "unsupported extension" in response.json()["detail"]


def test_diff_rejects_an_invalid_version(client, old_csv, new_csv):
    response = upload(client, old_csv, new_csv, current_version="not-a-version")

    assert response.status_code == 400


def test_history_groups_files_by_version(client, datasets_dir):
    payload = client.get("/api/history").json()

    assert payload["exists"] is True
    assert [group["name"] for group in payload["datasets"]] == ["customers"]
    assert [item["version"] for item in payload["datasets"][0]["versions"]] == ["1", "2"]
    assert payload["ignored"] == ["notes.txt"]


def test_history_of_a_missing_directory(tmp_path):
    history = scan_datasets(tmp_path / "absent")

    assert history.exists is False
    assert history.datasets == []


def test_history_diff_compares_two_versions(client, datasets_dir):
    payload = client.get("/api/history/customers/diff?old=1&new=2").json()

    assert payload["bump"] == "major"
    assert payload["current_version"] == "1.0.0"
    assert payload["next_version"] == "2.0.0"


def test_history_diff_reports_unknown_dataset(client, datasets_dir):
    assert client.get("/api/history/absent/diff?old=1&new=2").status_code == 404
    assert client.get("/api/history/customers/diff?old=1&new=9").status_code == 404


def test_history_diff_refuses_path_traversal(client, datasets_dir):
    response = client.get("/api/history/..%2F..%2Fetc/diff?old=1&new=2")

    assert response.status_code == 404


def test_upload_over_the_size_limit(client, old_csv, new_csv, tmp_path, monkeypatch):
    settings = Settings(
        datasets_dir=tmp_path,
        max_upload_bytes=10,
        frontend_dir=tmp_path / "frontend",
    )
    monkeypatch.setattr("web.backend.main.get_settings", lambda: settings)

    response = upload(client, old_csv, new_csv)

    assert response.status_code == 413


def test_an_oversized_upload_stops_at_the_limit(client, tmp_path, monkeypatch):
    """The limit has to bound what reaches disk, not just what is accepted afterwards.

    Checking the size once the copy finished made it advisory: the whole body landed first,
    so a large enough upload filled the volume whatever the limit said.
    """
    limit = 64 * 1024
    settings = Settings(
        datasets_dir=tmp_path,
        max_upload_bytes=limit,
        frontend_dir=tmp_path / "frontend",
    )
    monkeypatch.setattr("web.backend.main.get_settings", lambda: settings)

    written = []
    original = main._copy_within_limit
    monkeypatch.setattr(
        main,
        "_copy_within_limit",
        lambda upload, path, cap: written.append(original(upload, path, cap)) or written[-1],
    )

    oversized = tmp_path / "big.csv"
    oversized.write_bytes(b"id,name\n" + b"1,x\n" * (limit // 2))

    response = upload(client, oversized, oversized)

    assert response.status_code == 413
    assert written, "the upload never reached the copy"
    # a single byte past the limit is all it takes to know it was passed
    assert max(written) == limit + 1
    assert max(written) < oversized.stat().st_size


def test_an_oversized_upload_leaves_nothing_behind(tmp_path):
    """The partial write is removed, so a rejected upload costs no disk."""
    target = tmp_path / "partial.csv"

    class _Upload:
        file = io.BytesIO(b"x" * 4096)

    written = main._copy_within_limit(_Upload(), target, limit=1024)

    assert written > 1024
    assert not target.exists()


def test_empty_upload_is_rejected(client, old_csv, tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")

    response = upload(client, empty, old_csv)

    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_broken_rules_file_is_rejected(client, old_csv, new_csv, tmp_path):
    rules = tmp_path / "broken.yaml"
    rules.write_text("major:\n  - column_exploded\n", encoding="utf-8")

    with old_csv.open("rb") as old, new_csv.open("rb") as new, rules.open("rb") as rule_file:
        response = client.post(
            "/api/diff",
            files={
                "old": (old_csv.name, old, "text/csv"),
                "new": (new_csv.name, new, "text/csv"),
                "rules": (rules.name, rule_file, "application/yaml"),
            },
        )

    assert response.status_code == 400


def test_rules_upload_must_be_yaml(client, old_csv, new_csv):
    with old_csv.open("rb") as old, new_csv.open("rb") as new, new_csv.open("rb") as rule_file:
        response = client.post(
            "/api/diff",
            files={
                "old": (old_csv.name, old, "text/csv"),
                "new": (new_csv.name, new, "text/csv"),
                "rules": ("rules.csv", rule_file, "text/csv"),
            },
        )

    assert response.status_code == 400


def test_corrupt_upload_is_rejected(client, old_csv, tmp_path):
    broken = tmp_path / "broken.parquet"
    broken.write_bytes(b"not a parquet file")

    response = upload(client, broken, old_csv)

    assert response.status_code == 400


def test_history_ignores_directories_and_hidden_files(tmp_path, old_csv):
    directory = tmp_path / "datasets"
    (directory / "nested").mkdir(parents=True)
    (directory / ".hidden_v1.csv").write_bytes(old_csv.read_bytes())
    (directory / "customers_v1.csv").write_bytes(old_csv.read_bytes())

    history = scan_datasets(directory)

    assert [group["name"] for group in history.model_dump()["datasets"]] == ["customers"]
    assert history.ignored == []


def test_history_sorts_versions_numerically(tmp_path, old_csv):
    directory = tmp_path / "datasets"
    directory.mkdir()
    for version in ("1", "2", "10"):
        (directory / f"customers_v{version}.csv").write_bytes(old_csv.read_bytes())

    versions = [item.version for item in scan_datasets(directory).datasets[0].versions]

    assert versions == ["1", "2", "10"]


def test_history_reads_dotted_and_dashed_names(tmp_path, old_csv):
    directory = tmp_path / "datasets"
    directory.mkdir()
    (directory / "sales.v2.1.csv").write_bytes(old_csv.read_bytes())
    (directory / "sales-v2.2.csv").write_bytes(old_csv.read_bytes())

    group = scan_datasets(directory).datasets[0]

    assert group.name == "sales"
    assert [item.version for item in group.versions] == ["2.1", "2.2"]
    assert group.latest.version == "2.2"


def test_history_diff_pads_the_version_from_the_filename(client, datasets_dir):
    payload = client.get("/api/history/customers/diff?old=1&new=2&current_version=3.4.5").json()

    assert payload["current_version"] == "3.4.5"
    assert payload["next_version"] == "4.0.0"


def test_frontend_is_served(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "DataSemver" in response.text


def test_mounting_a_missing_frontend_is_a_no_op(tmp_path):
    from fastapi import FastAPI

    from web.backend.main import mount_frontend

    application = FastAPI()
    mount_frontend(
        application,
        Settings(
            datasets_dir=tmp_path,
            max_upload_bytes=1024,
            frontend_dir=tmp_path / "absent",
        ),
    )

    assert [route.path for route in application.routes if route.path == "/"] == []


def test_history_ignores_files_without_a_version(tmp_path, old_csv):
    directory = tmp_path / "datasets"
    directory.mkdir()
    (directory / "customers.csv").write_bytes(old_csv.read_bytes())
    (directory / "customers_v1.csv").write_bytes(old_csv.read_bytes())

    history = scan_datasets(directory)

    assert [group.name for group in history.datasets] == ["customers"]
    assert history.ignored == ["customers.csv"]


def test_a_missing_file_becomes_a_404():
    from fastapi import HTTPException

    from web.backend.main import as_http_error

    with pytest.raises(HTTPException) as error, as_http_error():
        raise FileNotFoundError("dataset not found: gone.csv")

    assert error.value.status_code == 404
