import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from feast import FeatureStore
from feast.api.registry.rest.rest_registry_server import RestRegistryServer
from feast.repo_config import RepoConfig


@pytest.fixture
def catalog_test_app():
    tmp_dir = tempfile.TemporaryDirectory()
    registry_path = os.path.join(tmp_dir.name, "registry.db")

    config = {
        "registry": registry_path,
        "project": "test_project",
        "provider": "local",
        "offline_store": {"type": "file"},
        "online_store": {"type": "sqlite", "path": ":memory:"},
    }
    store = FeatureStore(config=RepoConfig.model_validate(config))

    rest_server = RestRegistryServer(store)
    client = TestClient(rest_server.app)

    yield client, store

    tmp_dir.cleanup()


# ---- Config ----


def test_catalog_config(catalog_test_app):
    client, _ = catalog_test_app
    resp = client.get("/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "defaults" in data
    assert "overrides" in data


# ---- Namespace CRUD ----


def test_create_and_get_namespace(catalog_test_app):
    client, _ = catalog_test_app
    resp = client.post(
        "/v1/namespaces",
        json={"namespace": ["my_catalog"], "properties": {"owner": "test"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["namespace"] == ["my_catalog"]
    assert data["properties"]["owner"] == "test"

    resp = client.get("/v1/namespaces/my_catalog")
    assert resp.status_code == 200
    assert resp.json()["namespace"] == ["my_catalog"]


def test_create_duplicate_namespace(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["dup_ns"]})
    resp = client.post("/v1/namespaces", json={"namespace": ["dup_ns"]})
    assert resp.status_code == 409


def test_list_namespaces(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["ns_a"]})
    client.post("/v1/namespaces", json={"namespace": ["ns_b"]})
    resp = client.get("/v1/namespaces")
    assert resp.status_code == 200
    names = resp.json()["namespaces"]
    flat = [n[0] for n in names]
    assert "ns_a" in flat
    assert "ns_b" in flat


def test_namespace_exists(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["exist_ns"]})
    resp = client.head("/v1/namespaces/exist_ns")
    assert resp.status_code == 204

    resp = client.head("/v1/namespaces/no_such_ns")
    assert resp.status_code == 404


def test_drop_empty_namespace(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["drop_me"]})
    resp = client.delete("/v1/namespaces/drop_me")
    assert resp.status_code == 204

    resp = client.get("/v1/namespaces/drop_me")
    assert resp.status_code == 404


def test_drop_nonempty_namespace_fails(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["nonempty_ns"]})
    client.post(
        "/v1/namespaces/nonempty_ns/namespaces/default/tables",
        json={
            "name": "blocker_table",
            "schema": {"type": "struct", "schema-id": 0, "fields": []},
        },
    )
    resp = client.delete("/v1/namespaces/nonempty_ns")
    assert resp.status_code == 409


def test_update_namespace_properties(catalog_test_app):
    client, _ = catalog_test_app
    client.post(
        "/v1/namespaces",
        json={"namespace": ["props_ns"], "properties": {"key1": "val1"}},
    )
    resp = client.post(
        "/v1/namespaces/props_ns/properties",
        json={"updates": {"key2": "val2"}, "removals": ["key1"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "key1" in data["removed"]
    assert "key2" in data["updated"]


# ---- Nested namespaces ----


def test_nested_namespace_listing(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["nested_ns"]})
    resp = client.get("/v1/namespaces/nested_ns/namespaces")
    assert resp.status_code == 200
    namespaces = resp.json()["namespaces"]
    assert ["nested_ns", "default"] in namespaces


def test_get_nested_namespace(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["parent_ns"]})
    resp = client.get("/v1/namespaces/parent_ns/namespaces/my_schema")
    assert resp.status_code == 200
    assert resp.json()["namespace"] == ["parent_ns", "my_schema"]


# ---- Table CRUD ----


def test_create_and_load_table(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["tbl_ns"]})

    create_resp = client.post(
        "/v1/namespaces/tbl_ns/namespaces/default/tables",
        json={
            "name": "users",
            "schema": {
                "type": "struct",
                "schema-id": 0,
                "fields": [
                    {"id": 1, "name": "user_id", "required": True, "type": "long"},
                    {"id": 2, "name": "name", "required": False, "type": "string"},
                ],
            },
        },
    )
    assert create_resp.status_code == 200
    data = create_resp.json()
    assert "metadata" in data
    assert "metadata-location" in data
    metadata = data["metadata"]
    assert len(metadata["schemas"]) == 1
    assert len(metadata["schemas"][0]["fields"]) == 2

    load_resp = client.get("/v1/namespaces/tbl_ns/namespaces/default/tables/users")
    assert load_resp.status_code == 200
    assert load_resp.json()["metadata"]["schemas"][0]["fields"][0]["name"] == "user_id"


def test_create_duplicate_table(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["dup_tbl_ns"]})
    client.post(
        "/v1/namespaces/dup_tbl_ns/namespaces/default/tables",
        json={
            "name": "t1",
            "schema": {"type": "struct", "schema-id": 0, "fields": []},
        },
    )
    resp = client.post(
        "/v1/namespaces/dup_tbl_ns/namespaces/default/tables",
        json={
            "name": "t1",
            "schema": {"type": "struct", "schema-id": 0, "fields": []},
        },
    )
    assert resp.status_code == 409


def test_list_tables(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["list_tbl_ns"]})
    for name in ["t1", "t2"]:
        client.post(
            "/v1/namespaces/list_tbl_ns/namespaces/default/tables",
            json={
                "name": name,
                "schema": {"type": "struct", "schema-id": 0, "fields": []},
            },
        )
    resp = client.get("/v1/namespaces/list_tbl_ns/namespaces/default/tables")
    assert resp.status_code == 200
    identifiers = resp.json()["identifiers"]
    names = [i["name"] for i in identifiers]
    assert "t1" in names
    assert "t2" in names


def test_table_exists(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["head_tbl_ns"]})
    client.post(
        "/v1/namespaces/head_tbl_ns/namespaces/default/tables",
        json={
            "name": "check_me",
            "schema": {"type": "struct", "schema-id": 0, "fields": []},
        },
    )
    resp = client.head("/v1/namespaces/head_tbl_ns/namespaces/default/tables/check_me")
    assert resp.status_code == 204

    resp = client.head("/v1/namespaces/head_tbl_ns/namespaces/default/tables/nope")
    assert resp.status_code == 404


def test_drop_table(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["drop_tbl_ns"]})
    client.post(
        "/v1/namespaces/drop_tbl_ns/namespaces/default/tables",
        json={
            "name": "gone",
            "schema": {"type": "struct", "schema-id": 0, "fields": []},
        },
    )
    resp = client.delete("/v1/namespaces/drop_tbl_ns/namespaces/default/tables/gone")
    assert resp.status_code == 204

    resp = client.get("/v1/namespaces/drop_tbl_ns/namespaces/default/tables/gone")
    assert resp.status_code == 404


def test_update_table(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["upd_tbl_ns"]})
    client.post(
        "/v1/namespaces/upd_tbl_ns/namespaces/default/tables",
        json={
            "name": "evolve",
            "schema": {
                "type": "struct",
                "schema-id": 0,
                "fields": [
                    {"id": 1, "name": "col_a", "required": True, "type": "string"},
                ],
            },
        },
    )

    resp = client.put(
        "/v1/namespaces/upd_tbl_ns/namespaces/default/tables/evolve",
        json={
            "schema": {
                "type": "struct",
                "schema-id": 1,
                "fields": [
                    {"id": 1, "name": "col_a", "required": True, "type": "string"},
                    {"id": 2, "name": "col_b", "required": False, "type": "int"},
                ],
            },
            "properties": {"format": "parquet"},
        },
    )
    assert resp.status_code == 200
    metadata = resp.json()["metadata"]
    assert len(metadata["schemas"][0]["fields"]) == 2


def test_rename_table(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["rename_ns"]})
    client.post(
        "/v1/namespaces/rename_ns/namespaces/default/tables",
        json={
            "name": "old_name",
            "schema": {"type": "struct", "schema-id": 0, "fields": []},
        },
    )
    resp = client.post(
        "/v1/tables/rename",
        json={
            "source": {"namespace": ["rename_ns", "default"], "name": "old_name"},
            "destination": {"namespace": ["rename_ns", "default"], "name": "new_name"},
        },
    )
    assert resp.status_code == 200

    resp = client.head("/v1/namespaces/rename_ns/namespaces/default/tables/old_name")
    assert resp.status_code == 404

    resp = client.head("/v1/namespaces/rename_ns/namespaces/default/tables/new_name")
    assert resp.status_code == 204


def test_table_in_nonexistent_namespace(catalog_test_app):
    client, _ = catalog_test_app
    resp = client.get("/v1/namespaces/ghost/namespaces/default/tables")
    assert resp.status_code == 404


# ---- Volume CRUD ----


def test_create_and_get_volume(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["vol_ns"]})
    resp = client.post(
        "/v1/namespaces/vol_ns/namespaces/default/volumes",
        json={
            "name": "my_vol",
            "volume-type": "EXTERNAL",
            "storage-location": "s3://bucket/path",
            "comment": "test volume",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "my_vol"
    assert data["storage-location"] == "s3://bucket/path"

    resp = client.get("/v1/namespaces/vol_ns/namespaces/default/volumes/my_vol")
    assert resp.status_code == 200
    assert resp.json()["name"] == "my_vol"


def test_create_duplicate_volume(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["dup_vol_ns"]})
    client.post(
        "/v1/namespaces/dup_vol_ns/namespaces/default/volumes",
        json={
            "name": "v1",
            "volume-type": "EXTERNAL",
            "storage-location": "s3://a",
        },
    )
    resp = client.post(
        "/v1/namespaces/dup_vol_ns/namespaces/default/volumes",
        json={
            "name": "v1",
            "volume-type": "EXTERNAL",
            "storage-location": "s3://a",
        },
    )
    assert resp.status_code == 409


def test_list_volumes(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["list_vol_ns"]})
    for name in ["v1", "v2"]:
        client.post(
            "/v1/namespaces/list_vol_ns/namespaces/default/volumes",
            json={
                "name": name,
                "volume-type": "EXTERNAL",
                "storage-location": f"s3://bucket/{name}",
            },
        )
    resp = client.get("/v1/namespaces/list_vol_ns/namespaces/default/volumes")
    assert resp.status_code == 200
    names = [v["name"] for v in resp.json()["volumes"]]
    assert "v1" in names
    assert "v2" in names


def test_volume_exists(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["head_vol_ns"]})
    client.post(
        "/v1/namespaces/head_vol_ns/namespaces/default/volumes",
        json={
            "name": "check_vol",
            "volume-type": "EXTERNAL",
            "storage-location": "s3://b",
        },
    )
    resp = client.head(
        "/v1/namespaces/head_vol_ns/namespaces/default/volumes/check_vol"
    )
    assert resp.status_code == 204

    resp = client.head("/v1/namespaces/head_vol_ns/namespaces/default/volumes/nope")
    assert resp.status_code == 404


def test_delete_volume(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["del_vol_ns"]})
    client.post(
        "/v1/namespaces/del_vol_ns/namespaces/default/volumes",
        json={
            "name": "bye_vol",
            "volume-type": "EXTERNAL",
            "storage-location": "s3://c",
        },
    )
    resp = client.delete(
        "/v1/namespaces/del_vol_ns/namespaces/default/volumes/bye_vol"
    )
    assert resp.status_code == 204

    resp = client.get("/v1/namespaces/del_vol_ns/namespaces/default/volumes/bye_vol")
    assert resp.status_code == 404


def test_update_volume(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["upd_vol_ns"]})
    client.post(
        "/v1/namespaces/upd_vol_ns/namespaces/default/volumes",
        json={
            "name": "upd_vol",
            "volume-type": "EXTERNAL",
            "storage-location": "s3://old",
        },
    )
    resp = client.put(
        "/v1/namespaces/upd_vol_ns/namespaces/default/volumes/upd_vol",
        json={"comment": "updated comment", "storage_location": "s3://new"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["storage-location"] == "s3://new"


# ---- Search ----


def test_search_catalog(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["search_ns"]})
    client.post(
        "/v1/namespaces/search_ns/namespaces/default/tables",
        json={
            "name": "customers",
            "schema": {"type": "struct", "schema-id": 0, "fields": []},
        },
    )
    client.post(
        "/v1/namespaces/search_ns/namespaces/default/volumes",
        json={
            "name": "customer_data",
            "volume-type": "EXTERNAL",
            "storage-location": "s3://data",
        },
    )

    resp = client.get("/v1/search", params={"query": "customer"})
    assert resp.status_code == 200
    results = resp.json()["results"]
    names = [r["name"] for r in results]
    assert "customers" in names
    assert "customer_data" in names

    types = {r["name"]: r["type"] for r in results}
    assert types["customers"] == "table"
    assert types["customer_data"] == "volume"


def test_search_no_results(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["empty_search_ns"]})
    resp = client.get("/v1/search", params={"query": "nonexistent_xyz"})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


# ---- Schema namespace isolation ----


def test_tables_in_different_schemas(catalog_test_app):
    client, _ = catalog_test_app
    client.post("/v1/namespaces", json={"namespace": ["iso_ns"]})

    client.post(
        "/v1/namespaces/iso_ns/namespaces/schema_a/tables",
        json={
            "name": "tbl_a",
            "schema": {"type": "struct", "schema-id": 0, "fields": []},
        },
    )
    client.post(
        "/v1/namespaces/iso_ns/namespaces/schema_b/tables",
        json={
            "name": "tbl_b",
            "schema": {"type": "struct", "schema-id": 0, "fields": []},
        },
    )

    resp_a = client.get("/v1/namespaces/iso_ns/namespaces/schema_a/tables")
    resp_b = client.get("/v1/namespaces/iso_ns/namespaces/schema_b/tables")
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    names_a = [i["name"] for i in resp_a.json()["identifiers"]]
    names_b = [i["name"] for i in resp_b.json()["identifiers"]]
    assert "tbl_a" in names_a
    assert "tbl_b" in names_b
    assert "tbl_b" not in names_a
    assert "tbl_a" not in names_b

    resp = client.get("/v1/namespaces/iso_ns/namespaces")
    schemas = [ns[1] for ns in resp.json()["namespaces"]]
    assert "schema_a" in schemas
    assert "schema_b" in schemas
