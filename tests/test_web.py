import gzip
import io
import tracemalloc

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

import datasemver_web.backend.main as main
from datasemver.core.profile import PROFILE_SUFFIX, PROFILE_VERSION, write_profile
from datasemver.formats.loader import load_schema
from datasemver_web.backend.config import Settings
from datasemver_web.backend.history import scan_datasets
from datasemver_web.backend.main import app

pytestmark = pytest.mark.web


@pytest.fixture
def client():
    with TestClient(app, base_url="http://localhost") as test_client:
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
    monkeypatch.setattr("datasemver_web.backend.main.get_settings", lambda: settings)
    return directory


@pytest.fixture
def tight(tmp_path, monkeypatch):
    """A dashboard whose limit is small enough to cross inside a test."""
    settings = Settings(
        datasets_dir=tmp_path / "datasets",
        max_upload_bytes=256 * 1024,
        frontend_dir=tmp_path / "frontend",
    )
    monkeypatch.setattr("datasemver_web.backend.main.get_settings", lambda: settings)
    return settings


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


def test_meta_offers_only_what_an_upload_is_accepted_for(client):
    """The picker is built from this list, so anything in it is an invitation.

    The dashboard takes less than the library reads while the decompressed size is
    unguarded, and an interface that offers a format it then turns away is worse than one
    that never offered it -- the reader did what it said. Held as a subset rather than as a
    literal list, so a format added to the library does not have to be added here twice.
    """
    offered = client.get("/api/meta").json()["supported_extensions"]

    assert set(offered) <= main.UPLOAD_EXTENSIONS
    assert PROFILE_SUFFIX not in offered
    assert ".csv" in offered
    assert ".csv.gz" in offered


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


def _diff_with_rules(client, old_csv, new_csv, rules_text):
    rules = io.BytesIO(rules_text.encode("utf-8"))
    with old_csv.open("rb") as old, new_csv.open("rb") as new:
        return client.post(
            "/api/diff",
            files={
                "old": (old_csv.name, old, "text/csv"),
                "new": (new_csv.name, new, "text/csv"),
                "rules": ("rules.yaml", rules, "application/yaml"),
            },
            data={"current_version": "1.0.0"},
        )


def test_a_rules_alias_bomb_is_refused_rather_than_expanded(client, old_csv, new_csv):
    """A few hundred bytes of nested anchors must not be allowed to expand to gigabytes."""
    bomb = "a: &a [x, x, x, x, x, x, x, x, x]\n"
    for level in range(1, 8):
        bomb += f"b{level}: &b{level} [" + ", ".join(["*a"] * 9) + "]\n"
    bomb += "major:\n  - [*b7]\n"

    tracemalloc.start()
    try:
        response = _diff_with_rules(client, old_csv, new_csv, bomb)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert response.status_code == 400
    assert "alias" in response.json()["detail"].lower()
    # The refusal is at parse time, so nothing is ever expanded: a handful of MB, not GB.
    assert peak < 64 * 1024 * 1024


def test_a_rules_file_is_held_to_a_tighter_limit_than_a_dataset(client, old_csv, new_csv):
    """A rules upload past its own small cap is refused even when it fits the dataset limit."""
    oversized = "minor:\n" + "  - column_removed\n" + "#" + "a" * (main.MAX_RULES_BYTES)

    response = _diff_with_rules(client, old_csv, new_csv, oversized)

    assert response.status_code == 413
    assert len(oversized.encode()) < client.get("/api/meta").json()["max_upload_mb"] * 1024 * 1024


def test_diff_rejects_unsupported_extension(client, old_csv, tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("nope", encoding="utf-8")

    response = upload(client, other, old_csv)

    assert response.status_code == 400
    assert "unsupported extension" in response.json()["detail"]


def test_a_compressed_dataset_is_compared_like_any_other(tmp_path, old_csv, new_csv, client):
    """What this test used to assert, and why it no longer does.

    #7 taught the library to read `.csv.gz`, and the dashboard went on refusing them: the
    upload limit counted the bytes that arrived, which for a compressed file says nothing
    about what reading it costs, so dispatch was pinned to `Path.suffix` and every compressed
    name arrived as `.gz` and bounced. The guard on the decompressed size (#8) is what that
    was waiting for, so the refusal is gone and the reason it existed stays here.
    """
    compressed = tmp_path / "old.csv.gz"
    with gzip.open(compressed, "wb") as stream:
        stream.write(old_csv.read_bytes())

    response = upload(client, compressed, new_csv, current_version="1.4.2")
    uncompressed = upload(client, old_csv, new_csv, current_version="1.4.2")

    assert response.status_code == 200
    assert response.json()["bump"] == uncompressed.json()["bump"] == "major"


def test_a_compressed_upload_is_measured_on_what_it_becomes(tmp_path, old_csv, client, tight):
    """A file inside every stated limit, refused for the size it turns into."""
    bomb = tmp_path / "old.csv.gz"
    with gzip.open(bomb, "wb") as stream:
        stream.write(b"id,value\n" + b"1,aaaaaaaaaa\n" * 200_000)

    response = upload(client, bomb, old_csv)

    assert bomb.stat().st_size < tight.max_upload_bytes
    assert response.status_code == 413
    assert "once decompressed" in response.json()["detail"]


def test_refusing_an_expansion_costs_a_chunk_rather_than_the_expansion(
    tmp_path, old_csv, client, tight
):
    """The refusal has to be cheaper than the attack, or it is the attack.

    Roughly 70 MB of dataframe behind 70 kB of upload. Decompressing it to find out how big
    it is would be doing exactly what the limit exists to prevent, so the reader stops one
    chunk past the limit and the peak stays near that chunk instead of near the file.
    """
    bomb = tmp_path / "old.csv.gz"
    with gzip.open(bomb, "wb") as stream:
        stream.write(b"id,value\n")
        for _ in range(64):
            stream.write(b"1,aaaaaaaa\n" * 100_000)

    tracemalloc.start()
    response = upload(client, bomb, old_csv)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert response.status_code == 413
    assert peak < 16 * 1024 * 1024


def test_a_broken_gzip_is_refused_before_anything_parses_it(tmp_path, old_csv, client):
    broken = tmp_path / "old.csv.gz"
    broken.write_bytes(b"not gzip at all")

    response = upload(client, broken, old_csv)

    assert response.status_code == 400
    assert "could not be decompressed" in response.json()["detail"]


def test_the_refusal_cannot_name_the_extension_it_is_refusing(tmp_path, old_csv, client):
    """A rejection listing the thing it rejected is how #9 announced itself.

    The list in the message and the set the upload is checked against have to be the same
    set, or the refusal reads as a bug in the server rather than as an answer. Asserted
    against the part after `expected one of` on purpose: `detail` quotes the filename too,
    so looking for `.csv.gz` in the whole string passes for the wrong reason.
    """
    refused = tmp_path / "old.csv.bz2"
    refused.write_bytes(old_csv.read_bytes())

    response = upload(client, refused, old_csv)
    offered = response.json()["detail"].split("expected one of ", 1)[1]

    assert response.status_code == 400
    assert ".bz2" not in offered


def test_diff_rejects_an_invalid_version(client, old_csv, new_csv):
    response = upload(client, old_csv, new_csv, current_version="not-a-version")

    assert response.status_code == 400


def test_history_groups_gzip_files_by_version(tmp_path):
    directory = tmp_path / "datasets"
    directory.mkdir()
    (directory / "customers_v3.csv.gz").write_bytes(b"compressed fixture")

    history = scan_datasets(directory)

    assert history.ignored == []
    assert history.datasets[0].name == "customers"
    assert history.datasets[0].versions[0].extension == ".csv.gz"


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
    monkeypatch.setattr("datasemver_web.backend.main.get_settings", lambda: settings)

    response = upload(client, old_csv, new_csv)

    assert response.status_code == 413


def test_the_report_names_the_uploaded_files(client, old_csv, new_csv, tmp_path, monkeypatch):
    """The server names the file on disk, so the report has to be told what to call it."""
    settings = Settings(
        datasets_dir=tmp_path,
        max_upload_bytes=1024 * 1024,
        frontend_dir=tmp_path / "frontend",
    )
    monkeypatch.setattr("datasemver_web.backend.main.get_settings", lambda: settings)

    with old_csv.open("rb") as old, new_csv.open("rb") as new:
        response = client.post(
            "/api/diff",
            files={
                "old": ("clientes_v1.csv", old, "text/csv"),
                "new": ("clientes_v2.csv", new, "text/csv"),
            },
            data={"current_version": "1.4.2"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["old_source"] == "clientes_v1.csv"
    assert body["new_source"] == "clientes_v2.csv"
    assert body["next_version"] == "2.0.0"


def test_a_name_dressed_as_a_path_reports_as_its_last_segment():
    """The name is rendered, never opened, but it should not look like a path either."""

    class _Upload:
        filename = "../../etc/passwd.csv"

    assert main.reported_name(_Upload()) == "passwd.csv"


def test_an_endless_name_is_capped():
    class _Upload:
        filename = "a" * 5000 + ".csv"

    assert len(main.reported_name(_Upload())) == main.MAX_NAME_CHARS


def test_a_nameless_upload_still_reports_something():
    class _Upload:
        filename = None

    assert main.reported_name(_Upload()) == "uploaded"


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
    monkeypatch.setattr("datasemver_web.backend.main.get_settings", lambda: settings)

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


def test_the_page_carries_its_mark(client):
    """The mark is inline in the page so it takes its colours from the theme tokens."""
    response = client.get("/")

    assert 'class="brand-mark"' in response.text
    assert "var(--accent)" in response.text


def test_the_favicon_is_served(client):
    """It is a frontend file, and a frontend file is exactly what gets left out of a wheel.

    The dashboard's own packaging comment records that happening once already: the extras
    installed the dependencies and none of the interface. A stylesheet missing is obvious on
    sight, a favicon missing is not, so it is checked here rather than noticed later.
    """
    response = client.get("/favicon.svg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in response.text


def test_mounting_a_missing_frontend_is_a_no_op(tmp_path):
    from fastapi import FastAPI

    from datasemver_web.backend.main import mount_frontend

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

    from datasemver_web.backend.main import as_http_error

    with pytest.raises(HTTPException) as error, as_http_error():
        raise FileNotFoundError("dataset not found: gone.csv")

    assert error.value.status_code == 404


# --- profiles, which are what let a comparison outgrow the upload limit ----------------------


def test_a_dataset_can_be_profiled_through_the_dashboard(client, old_csv):
    """The dashboard's half of `datasemver profile`, for someone who never opens a terminal."""
    with old_csv.open("rb") as handle:
        response = client.post("/api/profile", files={"dataset": ("old.csv", handle, "text/csv")})

    payload = response.json()
    assert response.status_code == 200
    assert payload["profile_version"] == PROFILE_VERSION
    assert payload["dataset"]["source"] == "old.csv"
    assert payload["dataset"]["columns"]["score"]["quantiles"]


def test_a_profile_is_accepted_in_place_of_a_dataset(client, old_csv, new_csv, tmp_path):
    """The point of accepting one: the previous version never has to be uploaded, or exist."""
    stored = write_profile(load_schema(old_csv), tmp_path / f"old{PROFILE_SUFFIX}")

    with stored.open("rb") as profile, new_csv.open("rb") as new:
        response = client.post(
            "/api/diff",
            files={
                "old": (f"customers{PROFILE_SUFFIX}", profile, "application/json"),
                "new": ("new.csv", new, "text/csv"),
            },
            data={"current_version": "1.0.0"},
        )

    assert response.status_code == 200
    assert response.json()["bump"] == "major"


def test_a_plain_json_upload_is_still_read_as_data(client, old_json, new_json):
    """`.json` is a format this reads; only the compound suffix means a profile."""
    with old_json.open("rb") as old, new_json.open("rb") as new:
        response = client.post(
            "/api/diff",
            files={
                "old": ("old.json", old, "application/json"),
                "new": ("new.json", new, "application/json"),
            },
        )

    assert response.status_code == 200
    assert response.json()["diff"]["new"]["row_count"] == 5


def test_the_frontend_is_told_what_marks_a_profile(client):
    """Reported apart from the formats, because a profile is not one of them."""
    payload = client.get("/api/meta").json()

    assert payload["profile_suffix"] == PROFILE_SUFFIX
    assert PROFILE_SUFFIX not in payload["supported_extensions"]


# --- comparing rows -----------------------------------------------------------------------------


def test_a_key_compares_the_rows(client, old_csv, new_csv):
    with old_csv.open("rb") as old, new_csv.open("rb") as new:
        response = client.post(
            "/api/diff",
            files={"old": ("old.csv", old, "text/csv"), "new": ("new.csv", new, "text/csv")},
            data={"key": "id"},
        )

    types = {change["type"] for change in response.json()["diff"]["changes"]}
    assert "rows_modified" in types


def test_no_key_leaves_the_rows_alone(client, old_csv, new_csv):
    with old_csv.open("rb") as old, new_csv.open("rb") as new:
        response = client.post(
            "/api/diff",
            files={"old": ("old.csv", old, "text/csv"), "new": ("new.csv", new, "text/csv")},
        )

    types = {change["type"] for change in response.json()["diff"]["changes"]}
    assert "rows_modified" not in types


def test_a_key_against_a_profile_is_refused_with_the_reason(client, old_csv, new_csv, tmp_path):
    """A profile keeps no rows, so there is nothing to match; saying so beats a stack trace."""
    stored = write_profile(load_schema(old_csv), tmp_path / f"old{PROFILE_SUFFIX}")

    with stored.open("rb") as profile, new_csv.open("rb") as new:
        response = client.post(
            "/api/diff",
            files={
                "old": (f"old{PROFILE_SUFFIX}", profile, "application/json"),
                "new": ("new.csv", new, "text/csv"),
            },
            data={"key": "id"},
        )

    assert response.status_code == 400
    assert "keeps none" in response.json()["detail"]


def test_a_key_naming_no_column_is_refused(client, old_csv, new_csv):
    with old_csv.open("rb") as old, new_csv.open("rb") as new:
        response = client.post(
            "/api/diff",
            files={"old": ("old.csv", old, "text/csv"), "new": ("new.csv", new, "text/csv")},
            data={"key": "nope"},
        )

    assert response.status_code == 400
    assert "no column 'nope'" in response.json()["detail"]


def test_a_blank_key_is_the_same_as_none(client, old_csv, new_csv):
    """An untouched text field sends an empty string, which must not become a key of one."""
    with old_csv.open("rb") as old, new_csv.open("rb") as new:
        response = client.post(
            "/api/diff",
            files={"old": ("old.csv", old, "text/csv"), "new": ("new.csv", new, "text/csv")},
            data={"key": "  ,  "},
        )

    assert response.status_code == 200


# --- what an upload becomes ----------------------------------------------------------------------


def _parquet_of_one_value(path, rows):
    """A Parquet file whose rows are one repeated value, so it is tiny whatever `rows` is."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    block = pa.array([0] * 100_000, type=pa.int64())
    with pq.ParquetWriter(path, pa.schema([("value", pa.int64())]), compression="zstd") as writer:
        for _ in range(rows // 100_000):
            writer.write_table(pa.table({"value": block}), row_group_size=100_000)


def test_a_parquet_upload_is_measured_on_what_it_becomes(tmp_path, old_csv, client, tight):
    """Hundreds of kilobytes of limit, megabytes of table, a few kilobytes of upload."""
    bomb = tmp_path / "old.parquet"
    _parquet_of_one_value(bomb, 8_000_000)  # 64 MB decoded, against a 5 MB ceiling

    response = upload(client, bomb, old_csv)

    assert bomb.stat().st_size < tight.max_upload_bytes
    assert response.status_code == 413
    assert "once decompressed" in response.json()["detail"]


def test_an_ordinary_parquet_file_is_still_read_past_the_upload_limit_once_decoded(
    tmp_path, old_csv, client, tight
):
    """The multiple exists so that a real file, which compresses, is not refused for it."""
    small = tmp_path / "old.parquet"
    _parquet_of_one_value(small, 400_000)  # 3.2 MB decoded: past the limit, under the ceiling

    response = upload(client, small, old_csv)

    assert small.stat().st_size < tight.max_upload_bytes
    assert response.status_code != 413


def test_a_feather_upload_is_measured_on_what_it_becomes(tmp_path, old_csv, client, tight):
    import pyarrow as pa
    import pyarrow.ipc as ipc

    batch = pa.record_batch([pa.array([0] * 65_536, type=pa.int64())], names=["value"])
    bomb = tmp_path / "old.feather"
    options = ipc.IpcWriteOptions(compression="zstd")
    with ipc.new_file(bomb, batch.schema, options=options) as writer:
        for _ in range(100):  # 52 MB decoded, against a 5 MB ceiling
            writer.write_batch(batch)

    response = upload(client, bomb, old_csv)

    assert bomb.stat().st_size < tight.max_upload_bytes
    assert response.status_code == 413
    assert "once decompressed" in response.json()["detail"]


def test_a_workbook_upload_is_measured_on_what_it_becomes(tmp_path, old_csv, client, tight):
    import zipfile

    bomb = tmp_path / "old.xlsx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"<row/>" * 4_000_000)  # 24 MB inflated

    response = upload(client, bomb, old_csv)

    assert bomb.stat().st_size < tight.max_upload_bytes
    assert response.status_code == 413
    assert "once decompressed" in response.json()["detail"]


# --- who may ask, and what the browser is told to do with the answer -----------------------------


@pytest.mark.parametrize(
    "header",
    [
        None,
        "localhost",
        "localhost:8000",
        "app.localhost",
        "127.0.0.1:8000",
        "[::1]:8000",
        "[::1]",
        "::1",
        "192.168.1.20:8000",
        "LOCALHOST",
    ],
)
def test_the_hosts_a_local_dashboard_answers_to(header):
    assert main.host_allowed(header)


@pytest.mark.parametrize(
    "header",
    [
        "evil.example",
        "evil.example:8000",
        "localhost.evil.example",
        "127.0.0.1.evil.example",
        "evil.example:80:8000",
        "[evil",
        "",
    ],
)
def test_the_hosts_it_refuses_are_names_someone_else_controls(header):
    # An empty header is a missing one, which is not a browser's.
    assert main.host_allowed(header) is (header == "")


def test_a_rebound_name_is_refused_and_an_asked_for_one_is_not(client, tmp_path, monkeypatch):
    """DNS rebinding keeps the attacker's name in `Host`, which is what gives it away."""
    refused = client.get("/api/meta", headers={"Host": "evil.example"})
    assert refused.status_code == 400
    assert "DATASEMVER_ALLOWED_HOSTS" in refused.text

    settings = Settings(
        datasets_dir=tmp_path,
        max_upload_bytes=1024,
        frontend_dir=tmp_path,
        allowed_hosts=frozenset({"dash.internal"}),
    )
    monkeypatch.setattr("datasemver_web.backend.main.get_settings", lambda: settings)
    assert client.get("/api/meta", headers={"Host": "dash.internal:8000"}).status_code == 200
    assert client.get("/api/meta", headers={"Host": "evil.example"}).status_code == 400


def test_the_hosts_variable_is_read_from_the_environment(monkeypatch):
    from datasemver_web.backend.config import ALLOWED_HOSTS_ENV_VAR, get_settings

    monkeypatch.setenv(ALLOWED_HOSTS_ENV_VAR, " Dash.Internal , ,other.example ")
    get_settings.cache_clear()
    try:
        assert get_settings().allowed_hosts == {"dash.internal", "other.example"}
    finally:
        get_settings.cache_clear()


def test_every_answer_carries_the_headers_that_stop_the_browser_doing_more(client):
    page = client.get("/")
    api = client.get("/api/meta")

    for response in (page, api):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "SAMEORIGIN"
        assert response.headers["referrer-policy"] == "no-referrer"
        policy = response.headers["content-security-policy"]
        assert "default-src 'none'" in policy
        assert "frame-ancestors 'self'" in policy
        assert "unsafe" not in policy
    assert api.headers["cache-control"] == "no-store"
    assert "cache-control" not in page.headers or "no-store" not in page.headers["cache-control"]


def test_the_api_docs_keep_the_cdn_they_load_from(client):
    docs = client.get("/docs")

    assert docs.status_code == 200
    assert "content-security-policy" not in docs.headers
    assert docs.headers["x-content-type-options"] == "nosniff"


# --- how wide a table may be, and whether the server stays up while it is read -------------------


def _wide_csv(path, columns):
    path.write_text(
        ",".join(f"c{i}" for i in range(columns)) + "\n" + ",".join("1" for _ in range(columns)),
        encoding="utf-8",
    )


def test_a_table_wider_than_the_limit_is_refused_before_it_is_profiled(
    tmp_path, old_csv, client, monkeypatch
):
    """A few kilobytes of header are thousands of columns, and each one costs milliseconds."""
    settings = Settings(
        datasets_dir=tmp_path, max_upload_bytes=1024 * 1024, frontend_dir=tmp_path, max_columns=50
    )
    monkeypatch.setattr("datasemver_web.backend.main.get_settings", lambda: settings)
    wide = tmp_path / "old.csv"
    _wide_csv(wide, 51)

    response = upload(client, wide, old_csv)

    assert wide.stat().st_size < 1024
    assert response.status_code == 413
    detail = response.json()["detail"]
    assert "51 columns" in detail and "up to 50" in detail
    assert "DATASEMVER_MAX_COLUMNS" in detail


def test_a_table_at_the_limit_is_still_read(tmp_path, client, monkeypatch):
    settings = Settings(
        datasets_dir=tmp_path, max_upload_bytes=1024 * 1024, frontend_dir=tmp_path, max_columns=50
    )
    monkeypatch.setattr("datasemver_web.backend.main.get_settings", lambda: settings)
    wide = tmp_path / "old.csv"
    _wide_csv(wide, 50)
    other = tmp_path / "new.csv"
    _wide_csv(other, 50)

    assert upload(client, wide, other).status_code == 200


def test_the_column_limit_is_read_from_the_environment(monkeypatch):
    from datasemver_web.backend.config import MAX_COLUMNS_ENV_VAR, get_settings

    monkeypatch.setenv(MAX_COLUMNS_ENV_VAR, "123")
    get_settings.cache_clear()
    try:
        assert get_settings().max_columns == 123
    finally:
        get_settings.cache_clear()


def test_an_analysis_does_not_stop_the_server_answering_others(
    tmp_path, old_csv, new_csv, client, monkeypatch
):
    """Work run on the event loop would hold every other request until it finished."""
    import threading

    started, release = threading.Event(), threading.Event()
    real = main.run_analysis

    def slow(*args, **kwargs):
        started.set()
        assert release.wait(timeout=20)
        return real(*args, **kwargs)

    monkeypatch.setattr(main, "run_analysis", slow)
    outcome = {}

    def post():
        outcome["response"] = upload(client, old_csv, new_csv)

    worker = threading.Thread(target=post)
    worker.start()
    try:
        assert started.wait(timeout=20)
        # the analysis is held; a second request still gets its answer
        assert client.get("/api/meta").status_code == 200
    finally:
        release.set()
        worker.join(timeout=30)

    assert outcome["response"].status_code == 200


def test_a_feather_upload_of_one_enormous_batch_is_refused_without_decoding_it(
    tmp_path, old_csv, client, tight
):
    """Measured a batch at a time, this one was read whole first: it has one batch."""
    import pyarrow as pa
    import pyarrow.ipc as ipc

    block = pa.record_batch([pa.array([0] * 1_000_000, type=pa.int64())], names=["value"])
    table = pa.Table.from_batches([block] * 8).combine_chunks()  # 64 MB, against a 5 MB ceiling
    bomb = tmp_path / "old.feather"
    with ipc.new_file(bomb, table.schema, options=ipc.IpcWriteOptions(compression="zstd")) as w:
        w.write_table(table)

    with ipc.open_file(bomb) as reader:
        assert reader.num_record_batches == 1
    monkeypatch_target = "datasemver_web.backend.main._feather_batches_decode_past"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(monkeypatch_target, lambda *_: pytest.fail("decoded the batch to measure it"))
        response = upload(client, bomb, old_csv)

    assert bomb.stat().st_size < tight.max_upload_bytes
    assert response.status_code == 413
    assert "once decompressed" in response.json()["detail"]
