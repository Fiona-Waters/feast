from fastapi import APIRouter, Response

from feast import FeatureStore
from feast.api.catalog.errors import (
    NamespaceNotFoundException,
    ViewAlreadyExistsException,
    ViewNotFoundException,
)
from feast.api.catalog.mapping import odfv_to_load_view_response
from feast.api.catalog.models import (
    CreateViewRequest,
    ListTablesResponse,
    LoadViewResponse,
    RenameTableRequest,
    TableIdentifier,
)
from feast.api.catalog.namespaces import DEFAULT_SCHEMA, _resolve_namespace
from feast.data_source import RequestSource
from feast.errors import FeastObjectNotFoundException
from feast.field import Field
from feast.on_demand_feature_view import OnDemandFeatureView
from feast.transformation.python_transformation import PythonTransformation
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


def get_view_router(store: FeatureStore) -> APIRouter:
    router = APIRouter(tags=["iceberg-catalog-views"])

    def _ensure_namespace_exists(namespace: str) -> None:
        try:
            store.registry.get_project(namespace, allow_cache=True)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)

    @router.get("/namespaces/{namespace}/namespaces/{schema}/views")
    def list_views(namespace: str, schema: str) -> ListTablesResponse:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        odfvs = store.registry.list_on_demand_feature_views(
            project=project, allow_cache=True
        )
        return ListTablesResponse(
            identifiers=[
                TableIdentifier(namespace=[namespace, DEFAULT_SCHEMA], name=odfv.name)
                for odfv in odfvs
            ]
        )

    @router.post("/namespaces/{namespace}/namespaces/{schema}/views", status_code=200)
    def create_view(
        namespace: str, schema: str, request: CreateViewRequest
    ) -> LoadViewResponse:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)

        try:
            store.registry.get_on_demand_feature_view(
                request.name, project=project, allow_cache=False
            )
            raise ViewAlreadyExistsException(
                f"{namespace}.{DEFAULT_SCHEMA}", request.name
            )
        except FeastObjectNotFoundException:
            pass

        schema_fields = []
        if request.schema_ and request.schema_.fields:
            for field in request.schema_.fields:
                feast_type = ICEBERG_TYPE_TO_FEAST.get(field.type, String)
                schema_fields.append(Field(name=field.name, dtype=feast_type))

        if not schema_fields:
            schema_fields = [Field(name="placeholder", dtype=String)]

        properties = request.properties or {}
        description = properties.pop("description", "")
        owner = properties.pop("owner", "")

        request_source = RequestSource(
            name=f"{request.name}_request",
            schema=schema_fields,
        )

        def _noop_udf(features_df):
            return features_df

        noop_transformation = PythonTransformation(
            udf=_noop_udf,
            udf_string="def _noop_udf(features_df):\n    return features_df\n",
        )

        odfv = OnDemandFeatureView(
            name=request.name,
            schema=schema_fields,
            sources=[request_source],
            feature_transformation=noop_transformation,
            mode="python",
            description=description,
            owner=owner,
            tags=properties,
        )
        store.registry.apply_feature_view(odfv, project=project, commit=True)
        return odfv_to_load_view_response(odfv, namespace)

    @router.get("/namespaces/{namespace}/namespaces/{schema}/views/{view}")
    def load_view(namespace: str, schema: str, view: str) -> LoadViewResponse:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            odfv = store.registry.get_on_demand_feature_view(
                view, project=project, allow_cache=True
            )
        except FeastObjectNotFoundException:
            raise ViewNotFoundException(f"{namespace}.{DEFAULT_SCHEMA}", view)
        return odfv_to_load_view_response(odfv, namespace)

    @router.head("/namespaces/{namespace}/namespaces/{schema}/views/{view}")
    def view_exists(namespace: str, schema: str, view: str) -> Response:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            store.registry.get_on_demand_feature_view(
                view, project=project, allow_cache=True
            )
        except FeastObjectNotFoundException:
            raise ViewNotFoundException(f"{namespace}.{DEFAULT_SCHEMA}", view)
        return Response(status_code=204)

    @router.delete(
        "/namespaces/{namespace}/namespaces/{schema}/views/{view}", status_code=204
    )
    def drop_view(namespace: str, schema: str, view: str) -> Response:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            store.registry.get_on_demand_feature_view(
                view, project=project, allow_cache=False
            )
        except FeastObjectNotFoundException:
            raise ViewNotFoundException(f"{namespace}.{DEFAULT_SCHEMA}", view)
        store.registry.delete_feature_view(view, project=project, commit=True)
        return Response(status_code=204)

    @router.post("/views/rename", status_code=200)
    def rename_view(request: RenameTableRequest) -> None:
        src_ns = request.source.namespace[0] if request.source.namespace else ""
        dst_ns = (
            request.destination.namespace[0] if request.destination.namespace else ""
        )

        _ensure_namespace_exists(src_ns)
        if dst_ns != src_ns:
            _ensure_namespace_exists(dst_ns)

        try:
            src_odfv = store.registry.get_on_demand_feature_view(
                request.source.name, project=src_ns, allow_cache=False
            )
        except FeastObjectNotFoundException:
            raise ViewNotFoundException(src_ns, request.source.name)

        try:
            store.registry.get_on_demand_feature_view(
                request.destination.name, project=dst_ns, allow_cache=False
            )
            raise ViewAlreadyExistsException(dst_ns, request.destination.name)
        except FeastObjectNotFoundException:
            pass

        schema_fields = src_odfv.features or [Field(name="placeholder", dtype=String)]
        request_source = RequestSource(
            name=f"{request.destination.name}_request",
            schema=schema_fields,
        )

        def _noop_udf(features_df):
            return features_df

        noop_transformation = PythonTransformation(
            udf=_noop_udf,
            udf_string="def _noop_udf(features_df):\n    return features_df\n",
        )

        new_odfv = OnDemandFeatureView(
            name=request.destination.name,
            schema=schema_fields,
            sources=[request_source],
            feature_transformation=noop_transformation,
            mode=getattr(src_odfv, "mode", "python"),
            description=src_odfv.description or "",
            owner=src_odfv.owner or "",
            tags=dict(src_odfv.tags) if src_odfv.tags else {},
        )
        store.registry.apply_feature_view(new_odfv, project=dst_ns, commit=True)
        store.registry.delete_feature_view(
            request.source.name, project=src_ns, commit=True
        )

    return router
