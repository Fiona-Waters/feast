from fastapi import APIRouter, Response

from feast import FeatureStore
from feast.api.catalog.errors import (
    NamespaceNotFoundException,
    TableAlreadyExistsException,
    TableNotFoundException,
)
from feast.api.catalog.mapping import feature_view_to_load_table_response
from feast.api.catalog.models import (
    CreateTableRequest,
    ListTablesResponse,
    LoadTableResponse,
    RenameTableRequest,
    TableIdentifier,
    UpdateTableRequest,
)
from feast.api.catalog.namespaces import DEFAULT_SCHEMA, _resolve_namespace
from feast.errors import FeastObjectNotFoundException
from feast.feature_view import FeatureView
from feast.field import Field
from feast.infra.offline_stores.file_source import FileSource
from feast.types import (
    Bool,
    Bytes,
    Float32,
    Float64,
    Int32,
    Int64,
    String,
    UnixTimestamp,
)

ICEBERG_TYPE_TO_FEAST = {
    "int": Int32,
    "long": Int64,
    "float": Float32,
    "double": Float64,
    "string": String,
    "binary": Bytes,
    "boolean": Bool,
    "timestamptz": UnixTimestamp,
}


def get_table_router(store: FeatureStore) -> APIRouter:
    router = APIRouter(tags=["iceberg-catalog-tables"])

    def _ensure_namespace_exists(namespace: str) -> None:
        try:
            store.registry.get_project(namespace, allow_cache=True)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)

    @router.get("/namespaces/{namespace}/namespaces/{schema}/tables")
    def list_tables(namespace: str, schema: str) -> ListTablesResponse:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        feature_views = store.registry.list_feature_views(
            project=project, allow_cache=False
        )
        return ListTablesResponse(
            identifiers=[
                TableIdentifier(namespace=[namespace, DEFAULT_SCHEMA], name=fv.name)
                for fv in feature_views
            ]
        )

    @router.post("/namespaces/{namespace}/namespaces/{schema}/tables", status_code=200)
    def create_table(
        namespace: str, schema: str, request: CreateTableRequest
    ) -> LoadTableResponse:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)

        try:
            store.registry.get_feature_view(
                request.name, project=project, allow_cache=False
            )
            raise TableAlreadyExistsException(
                f"{namespace}.{DEFAULT_SCHEMA}", request.name
            )
        except FeastObjectNotFoundException:
            pass

        schema_fields = []
        if request.schema_ and request.schema_.fields:
            for field in request.schema_.fields:
                feast_type = ICEBERG_TYPE_TO_FEAST.get(field.type, String)
                schema_fields.append(Field(name=field.name, dtype=feast_type))

        location = (
            request.location
            or f"feast://{namespace}/{DEFAULT_SCHEMA}/tables/{request.name}"
        )
        properties = request.properties or {}
        description = properties.pop("description", "")
        owner = properties.pop("owner", "")

        source = FileSource(
            name=f"{request.name}_source",
            path=location,
            timestamp_field="",
        )

        fv = FeatureView(
            name=request.name,
            source=source,
            schema=schema_fields or None,
            ttl=None,
            online=False,
            description=description,
            owner=owner,
            tags=properties,
        )
        store.registry.apply_feature_view(fv, project=project, commit=True)
        return feature_view_to_load_table_response(fv, namespace)

    @router.get("/namespaces/{namespace}/namespaces/{schema}/tables/{table}")
    def load_table(namespace: str, schema: str, table: str) -> LoadTableResponse:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            fv = store.registry.get_feature_view(
                table, project=project, allow_cache=True
            )
        except FeastObjectNotFoundException:
            raise TableNotFoundException(f"{namespace}.{DEFAULT_SCHEMA}", table)
        return feature_view_to_load_table_response(fv, namespace)

    @router.head("/namespaces/{namespace}/namespaces/{schema}/tables/{table}")
    def table_exists(namespace: str, schema: str, table: str) -> Response:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            store.registry.get_feature_view(table, project=project, allow_cache=True)
        except FeastObjectNotFoundException:
            raise TableNotFoundException(f"{namespace}.{DEFAULT_SCHEMA}", table)
        return Response(status_code=204)

    @router.delete(
        "/namespaces/{namespace}/namespaces/{schema}/tables/{table}", status_code=204
    )
    def drop_table(namespace: str, schema: str, table: str) -> Response:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            store.registry.get_feature_view(table, project=project, allow_cache=False)
        except FeastObjectNotFoundException:
            raise TableNotFoundException(f"{namespace}.{DEFAULT_SCHEMA}", table)
        store.registry.delete_feature_view(table, project=project, commit=True)
        return Response(status_code=204)

    @router.put("/namespaces/{namespace}/namespaces/{schema}/tables/{table}")
    def update_table(
        namespace: str, schema: str, table: str, request: UpdateTableRequest
    ) -> LoadTableResponse:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            fv = store.registry.get_feature_view(
                table, project=project, allow_cache=False
            )
        except FeastObjectNotFoundException:
            raise TableNotFoundException(f"{namespace}.{DEFAULT_SCHEMA}", table)

        description = (
            request.description if request.description is not None else fv.description
        )
        owner = request.owner if request.owner is not None else fv.owner
        tags = dict(fv.tags) if fv.tags else {}
        if request.properties:
            for k, v in request.properties.items():
                tags[k] = v
        if request.data_source_format is not None:
            tags["format"] = request.data_source_format

        location = request.location
        if location is None:
            location = (
                fv.batch_source.path
                if fv.batch_source and hasattr(fv.batch_source, "path")
                else f"feast://{namespace}/{DEFAULT_SCHEMA}/tables/{table}"
            )
        source = FileSource(
            name=f"{table}_source",
            path=location,
            timestamp_field="",
        )

        schema_fields = fv.features or None
        if request.schema_ and request.schema_.fields:
            schema_fields = []
            for field in request.schema_.fields:
                feast_type = ICEBERG_TYPE_TO_FEAST.get(field.type, String)
                schema_fields.append(Field(name=field.name, dtype=feast_type))

        updated_fv = FeatureView(
            name=table,
            source=source,
            schema=schema_fields,
            ttl=None,
            online=False,
            description=description or "",
            owner=owner or "",
            tags=tags,
        )
        store.registry.apply_feature_view(updated_fv, project=project, commit=True)
        return feature_view_to_load_table_response(updated_fv, namespace)

    @router.post("/tables/rename", status_code=200)
    def rename_table(request: RenameTableRequest) -> None:
        src_ns = request.source.namespace[0] if request.source.namespace else ""
        dst_ns = (
            request.destination.namespace[0] if request.destination.namespace else ""
        )

        _ensure_namespace_exists(src_ns)
        if dst_ns != src_ns:
            _ensure_namespace_exists(dst_ns)

        try:
            src_fv = store.registry.get_feature_view(
                request.source.name, project=src_ns, allow_cache=False
            )
        except FeastObjectNotFoundException:
            raise TableNotFoundException(src_ns, request.source.name)

        try:
            store.registry.get_feature_view(
                request.destination.name, project=dst_ns, allow_cache=False
            )
            raise TableAlreadyExistsException(dst_ns, request.destination.name)
        except FeastObjectNotFoundException:
            pass

        location = (
            f"feast://{dst_ns}/{DEFAULT_SCHEMA}/tables/{request.destination.name}"
        )
        if src_fv.batch_source and hasattr(src_fv.batch_source, "path"):
            location = src_fv.batch_source.path

        source = FileSource(
            name=f"{request.destination.name}_source",
            path=location,
            timestamp_field="",
        )

        new_fv = FeatureView(
            name=request.destination.name,
            source=source,
            schema=src_fv.features or None,
            ttl=None,
            online=False,
            description=src_fv.description or "",
            owner=src_fv.owner or "",
            tags=dict(src_fv.tags) if src_fv.tags else {},
        )
        store.registry.apply_feature_view(new_fv, project=dst_ns, commit=True)
        store.registry.delete_feature_view(
            request.source.name, project=src_ns, commit=True
        )

    return router
