import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from web.backend.config import Settings  # noqa: E402
from web.backend.history import scan_datasets  # noqa: E402
from web.backend.main import app  # noqa: E402


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
            files={"old": (old_path.name, old, "text/csv"), "new": (new_path.name, new, "text/csv")},
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
