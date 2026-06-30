from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from feast.api.catalog import add_catalog_routes
from feast.errors import FeastObjectNotFoundException
from feast.feature_store import FeatureStore
from feast.project import Project


@pytest.fixture
def mock_store():
    store = MagicMock(spec=FeatureStore)
    store.registry = MagicMock()
    return store


@pytest.fixture
def client(mock_store):
    app = FastAPI()
    add_catalog_routes(app, mock_store)
    return TestClient(app)


# --- Config ---


def test_get_config(client):
    resp = client.get("/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "defaults" in data
    assert "overrides" in data


# --- Namespace endpoints ---


def test_list_namespaces(client, mock_store):
    mock_store.registry.list_projects.return_value = [
        Project(name="underwriting"),
        Project(name="claims"),
    ]
    resp = client.get("/v1/namespaces")
    assert resp.status_code == 200
    data = resp.json()
    assert data["namespaces"] == [["underwriting"], ["claims"]]


def test_create_namespace(client, mock_store):
    mock_store.registry.get_project.side_effect = FeastObjectNotFoundException(
        "not found"
    )
    mock_store.registry.apply_project.return_value = None
    resp = client.post(
        "/v1/namespaces",
        json={"namespace": ["test_project"], "properties": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["namespace"] == ["test_project"]


def test_create_namespace_already_exists(client, mock_store):
    mock_store.registry.get_project.return_value = Project(name="existing")
    resp = client.post(
        "/v1/namespaces",
        json={"namespace": ["existing"]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["type"] == "AlreadyExistsException"


def test_create_namespace_two_level_default_rejected(client, mock_store):
    resp = client.post(
        "/v1/namespaces",
        json={"namespace": ["project", "default"]},
    )
    assert resp.status_code == 409


def test_create_namespace_two_level_non_default_rejected(client, mock_store):
    resp = client.post(
        "/v1/namespaces",
        json={"namespace": ["project", "other"]},
    )
    assert resp.status_code == 404


def test_get_namespace(client, mock_store):
    mock_store.registry.get_project.return_value = Project(
        name="underwriting", tags={"env": "prod"}
    )
    resp = client.get("/v1/namespaces/underwriting")
    assert resp.status_code == 200
    data = resp.json()
    assert data["namespace"] == ["underwriting"]
    assert data["properties"]["env"] == "prod"


def test_get_namespace_not_found(client, mock_store):
    mock_store.registry.get_project.side_effect = FeastObjectNotFoundException(
        "not found"
    )
    resp = client.get("/v1/namespaces/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["error"]["type"] == "NoSuchNamespaceException"


def test_head_namespace(client, mock_store):
    mock_store.registry.get_project.return_value = Project(name="underwriting")
    resp = client.head("/v1/namespaces/underwriting")
    assert resp.status_code == 204


def test_head_namespace_not_found(client, mock_store):
    mock_store.registry.get_project.side_effect = FeastObjectNotFoundException(
        "not found"
    )
    resp = client.head("/v1/namespaces/nonexistent")
    assert resp.status_code == 404


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_drop_namespace_empty(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_drop_namespace_not_empty(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_update_namespace_properties(client, mock_store):
    pass


# --- Nested namespace endpoints ---


def test_list_nested_namespaces(client, mock_store):
    mock_store.registry.get_project.return_value = Project(name="underwriting")
    resp = client.get("/v1/namespaces/underwriting/namespaces")
    assert resp.status_code == 200
    data = resp.json()
    assert data["namespaces"] == [["underwriting", "default"]]


def test_get_nested_namespace(client, mock_store):
    mock_store.registry.get_project.return_value = Project(name="underwriting")
    resp = client.get("/v1/namespaces/underwriting/namespaces/default")
    assert resp.status_code == 200
    data = resp.json()
    assert data["namespace"] == ["underwriting", "default"]


def test_nested_namespace_bad_schema(client, mock_store):
    resp = client.get("/v1/namespaces/underwriting/namespaces/analytics")
    assert resp.status_code == 404


def test_head_nested_namespace(client, mock_store):
    mock_store.registry.get_project.return_value = Project(name="underwriting")
    resp = client.head("/v1/namespaces/underwriting/namespaces/default")
    assert resp.status_code == 204


def test_head_nested_namespace_bad_schema(client, mock_store):
    resp = client.head("/v1/namespaces/underwriting/namespaces/other")
    assert resp.status_code == 404


# --- Table endpoints ---


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_list_tables(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_create_table(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_load_table(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_table_exists(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_drop_table(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_rename_table(client, mock_store):
    pass


# --- View endpoints ---


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_list_views(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_create_view(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_load_view(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_view_exists(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_drop_view(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_rename_view(client, mock_store):
    pass


# --- Volume endpoints ---


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_list_volumes(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_create_volume(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_get_volume(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_volume_exists(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_delete_volume(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_update_volume(client, mock_store):
    pass


# --- Search endpoints ---


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_search_tables(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_search_views(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_search_volumes(client, mock_store):
    pass


@pytest.mark.skip(reason="Stub — implement when test coverage is prioritised")
def test_search_with_namespace_filter(client, mock_store):
    pass


# --- Error format ---


def test_404_error_format(client, mock_store):
    mock_store.registry.get_project.side_effect = FeastObjectNotFoundException(
        "not found"
    )
    resp = client.get("/v1/namespaces/nonexistent")
    assert resp.status_code == 404
    error = resp.json()["error"]
    assert "message" in error
    assert "type" in error
    assert "code" in error
    assert error["code"] == 404


def test_409_error_format(client, mock_store):
    mock_store.registry.get_project.return_value = Project(name="existing")
    resp = client.post(
        "/v1/namespaces",
        json={"namespace": ["existing"]},
    )
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == 409
    assert error["type"] == "AlreadyExistsException"
