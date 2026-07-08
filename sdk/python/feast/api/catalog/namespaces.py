from fastapi import APIRouter, Response

from feast import FeatureStore
from feast.api.catalog.errors import (
    NamespaceAlreadyExistsException,
    NamespaceNotEmptyException,
    NamespaceNotFoundException,
)
from feast.api.catalog.mapping import (
    CATALOG_MANAGED_TAG,
    namespace_properties_to_project_kwargs,
    project_to_namespace_response,
)
from feast.api.catalog.models import (
    CreateNamespaceRequest,
    ListNamespacesResponse,
    NamespaceResponse,
    UpdateNamespacePropertiesRequest,
    UpdateNamespacePropertiesResponse,
)
from feast.errors import FeastObjectNotFoundException
from feast.project import Project

DEFAULT_SCHEMA = "default"


def resolve_namespace(parent: str, child: str) -> str:
    """Resolve a two-level namespace to a Feast project name.

    The child level is passed through as the SavedDataset namespace field
    rather than being restricted to 'default'.
    """
    return parent


def get_namespace_router(store: FeatureStore) -> APIRouter:
    router = APIRouter(tags=["iceberg-catalog-namespaces"])

    # --- Top-level namespace operations (backed by Feast Project) ---

    @router.get("/namespaces")
    def list_namespaces() -> ListNamespacesResponse:
        projects = store.registry.list_projects(allow_cache=False)
        return ListNamespacesResponse(namespaces=[[p.name] for p in projects])

    @router.post("/namespaces", status_code=200)
    def create_namespace(request: CreateNamespaceRequest) -> NamespaceResponse:
        if len(request.namespace) == 2:
            raise NamespaceAlreadyExistsException(".".join(request.namespace))
        if len(request.namespace) != 1:
            raise NamespaceNotFoundException(".".join(request.namespace))

        kwargs = namespace_properties_to_project_kwargs(
            request.namespace, request.properties or {}
        )
        try:
            store.registry.get_project(kwargs["name"], allow_cache=False)
            raise NamespaceAlreadyExistsException(kwargs["name"])
        except FeastObjectNotFoundException:
            pass

        project = Project(**kwargs)
        store.registry.apply_project(project, commit=True)
        return project_to_namespace_response(project)

    @router.get("/namespaces/{namespace}")
    def get_namespace(namespace: str) -> NamespaceResponse:
        try:
            project = store.registry.get_project(namespace, allow_cache=True)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)
        return project_to_namespace_response(project)

    @router.head("/namespaces/{namespace}")
    def namespace_exists(namespace: str) -> Response:
        try:
            store.registry.get_project(namespace, allow_cache=True)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)
        return Response(status_code=204)

    @router.delete("/namespaces/{namespace}", status_code=204)
    def drop_namespace(namespace: str) -> Response:
        try:
            store.registry.get_project(namespace, allow_cache=False)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)

        catalog_datasets = store.registry.list_saved_datasets(
            project=namespace,
            allow_cache=False,
            tags={CATALOG_MANAGED_TAG: "true"},
        )
        if catalog_datasets:
            raise NamespaceNotEmptyException(namespace)

        store.registry.delete_project(namespace, commit=True)
        return Response(status_code=204)

    @router.post("/namespaces/{namespace}/properties")
    def update_namespace_properties(
        namespace: str, request: UpdateNamespacePropertiesRequest
    ) -> UpdateNamespacePropertiesResponse:
        try:
            project = store.registry.get_project(namespace, allow_cache=False)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)

        current_tags = dict(project.tags) if project.tags else {}
        removed = []
        missing = []
        updated = []

        if request.removals:
            for key in request.removals:
                if key in current_tags:
                    del current_tags[key]
                    removed.append(key)
                else:
                    missing.append(key)

        if request.updates:
            for key, value in request.updates.items():
                current_tags[key] = value
                updated.append(key)

        project.tags = current_tags
        store.registry.apply_project(project, commit=True)

        return UpdateNamespacePropertiesResponse(
            removed=removed,
            updated=updated,
            missing=missing,
        )

    # --- Nested namespace operations ---

    @router.get("/namespaces/{namespace}/namespaces")
    def list_nested_namespaces(namespace: str) -> ListNamespacesResponse:
        try:
            store.registry.get_project(namespace, allow_cache=True)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)

        catalog_datasets = store.registry.list_saved_datasets(
            project=namespace,
            allow_cache=True,
            tags={CATALOG_MANAGED_TAG: "true"},
        )
        seen = set()
        for ds in catalog_datasets:
            seen.add(ds.namespace or DEFAULT_SCHEMA)
        if not seen:
            seen.add(DEFAULT_SCHEMA)
        return ListNamespacesResponse(
            namespaces=[[namespace, ns] for ns in sorted(seen)]
        )

    @router.get("/namespaces/{namespace}/namespaces/{child}")
    def get_nested_namespace(namespace: str, child: str) -> NamespaceResponse:
        try:
            project = store.registry.get_project(namespace, allow_cache=True)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)
        resp = project_to_namespace_response(project)
        resp.namespace = [namespace, child]
        return resp

    @router.head("/namespaces/{namespace}/namespaces/{child}")
    def nested_namespace_exists(namespace: str, child: str) -> Response:
        try:
            store.registry.get_project(namespace, allow_cache=True)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)
        return Response(status_code=204)

    return router
