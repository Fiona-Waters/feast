from fastapi import APIRouter, Response

from feast import FeatureStore
from feast.api.catalog.errors import (
    NamespaceAlreadyExistsException,
    NamespaceNotEmptyException,
    NamespaceNotFoundException,
)
from feast.api.catalog.mapping import (
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


def _resolve_namespace(parent: str, child: str) -> str:
    if child != DEFAULT_SCHEMA:
        raise NamespaceNotFoundException(f"{parent}.{child}")
    return parent


def get_namespace_router(store: FeatureStore) -> APIRouter:
    router = APIRouter(tags=["iceberg-catalog-namespaces"])

    # --- Top-level namespace operations (backed by Feast Project) ---

    @router.get("/namespaces")
    def list_namespaces() -> ListNamespacesResponse:
        projects = store.registry.list_projects(allow_cache=True)
        return ListNamespacesResponse(namespaces=[[p.name] for p in projects])

    @router.post("/namespaces", status_code=200)
    def create_namespace(request: CreateNamespaceRequest) -> NamespaceResponse:
        if len(request.namespace) == 2 and request.namespace[1] == DEFAULT_SCHEMA:
            raise NamespaceAlreadyExistsException(
                f"{request.namespace[0]}.{DEFAULT_SCHEMA}"
            )
        if len(request.namespace) == 2 and request.namespace[1] != DEFAULT_SCHEMA:
            raise NamespaceNotFoundException(request.namespace[0])
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

        feature_views = store.registry.list_feature_views(
            project=namespace, allow_cache=False
        )
        odfvs = store.registry.list_on_demand_feature_views(
            project=namespace, allow_cache=False
        )
        data_sources = store.registry.list_data_sources(
            project=namespace, allow_cache=False
        )
        volumes = [
            ds for ds in data_sources if (ds.tags or {}).get("asset_type") == "volume"
        ]
        if feature_views or odfvs or volumes:
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

    # --- Nested namespace operations (implicit "default" schema) ---

    @router.get("/namespaces/{namespace}/namespaces")
    def list_nested_namespaces(namespace: str) -> ListNamespacesResponse:
        try:
            store.registry.get_project(namespace, allow_cache=True)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)
        return ListNamespacesResponse(namespaces=[[namespace, DEFAULT_SCHEMA]])

    @router.get("/namespaces/{namespace}/namespaces/{child}")
    def get_nested_namespace(namespace: str, child: str) -> NamespaceResponse:
        _resolve_namespace(namespace, child)
        try:
            project = store.registry.get_project(namespace, allow_cache=True)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)
        resp = project_to_namespace_response(project)
        resp.namespace = [namespace, DEFAULT_SCHEMA]
        return resp

    @router.head("/namespaces/{namespace}/namespaces/{child}")
    def nested_namespace_exists(namespace: str, child: str) -> Response:
        _resolve_namespace(namespace, child)
        try:
            store.registry.get_project(namespace, allow_cache=True)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)
        return Response(status_code=204)

    return router
