import uuid
from typing import Dict, List

from feast.api.catalog.models import (
    IcebergField,
    IcebergSchema,
    LoadTableResponse,
    LoadViewResponse,
    NamespaceResponse,
    TableMetadata,
    ViewMetadata,
    ViewRepresentation,
    ViewVersion,
    VolumeInfo,
)
from feast.data_source import DataSource
from feast.feature_view import FeatureView
from feast.field import Field
from feast.on_demand_feature_view import OnDemandFeatureView
from feast.project import Project
from feast.types import PrimitiveFeastType

CATALOG_UUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

FEAST_TYPE_TO_ICEBERG = {
    PrimitiveFeastType.INT32: "int",
    PrimitiveFeastType.INT64: "long",
    PrimitiveFeastType.FLOAT32: "float",
    PrimitiveFeastType.FLOAT64: "double",
    PrimitiveFeastType.STRING: "string",
    PrimitiveFeastType.BYTES: "binary",
    PrimitiveFeastType.BOOL: "boolean",
    PrimitiveFeastType.UNIX_TIMESTAMP: "timestamptz",
}


def _make_uuid(namespace: str, name: str) -> str:
    return str(uuid.uuid5(CATALOG_UUID_NAMESPACE, f"{namespace}.{name}"))


def _timestamp_ms(dt) -> int:
    if dt is None:
        return 0
    return int(dt.timestamp() * 1000)


def _get_data_source_location(ds: DataSource) -> str:
    if hasattr(ds, "path"):
        return ds.path
    if hasattr(ds, "table") and ds.table:
        return ds.table
    if hasattr(ds, "query") and ds.query:
        return ds.query
    if hasattr(ds, "topic") and ds.topic:
        return ds.topic
    return f"feast://{ds.name}"


def _feast_type_to_iceberg(feast_type) -> str:
    if isinstance(feast_type, PrimitiveFeastType):
        return FEAST_TYPE_TO_ICEBERG.get(feast_type, "string")
    return "string"


def _fields_to_iceberg_schema(fields: List[Field], schema_id: int = 0) -> IcebergSchema:
    iceberg_fields = []
    for i, field in enumerate(fields):
        iceberg_fields.append(
            IcebergField(
                id=i + 1,
                name=field.name,
                required=False,
                type=_feast_type_to_iceberg(field.dtype),
            )
        )
    return IcebergSchema(
        type="struct",
        schema_id=schema_id,
        fields=iceberg_fields,
    )


# --- Project <-> Namespace ---


def project_to_namespace_response(project: Project) -> NamespaceResponse:
    properties = dict(project.tags) if project.tags else {}
    if project.description:
        properties["description"] = project.description
    if project.owner:
        properties["owner"] = project.owner
    created_ms = _timestamp_ms(getattr(project, "created_timestamp", None))
    if created_ms:
        properties["created_at"] = str(created_ms)
    updated_ms = _timestamp_ms(getattr(project, "last_updated_timestamp", None))
    if updated_ms:
        properties["updated_at"] = str(updated_ms)
    return NamespaceResponse(
        namespace=[project.name],
        properties=properties,
    )


def namespace_properties_to_project_kwargs(
    namespace: List[str], properties: Dict[str, str]
) -> dict:
    name = ".".join(namespace)
    props = dict(properties) if properties else {}
    description = props.pop("description", "")
    owner = props.pop("owner", "")
    return {
        "name": name,
        "description": description,
        "owner": owner,
        "tags": props,
    }


# --- FeatureView <-> Table ---


def feature_view_to_load_table_response(
    fv: FeatureView, namespace: str
) -> LoadTableResponse:
    location = f"feast://{namespace}/tables/{fv.name}"
    if fv.batch_source:
        location = _get_data_source_location(fv.batch_source)

    schema = _fields_to_iceberg_schema(fv.features or [])
    properties = dict(fv.tags) if fv.tags else {}
    if fv.description:
        properties["description"] = fv.description
    if fv.owner:
        properties["owner"] = fv.owner

    metadata = TableMetadata(
        **{
            "format-version": 2,
            "table-uuid": _make_uuid(namespace, fv.name),
            "location": location,
            "last-updated-ms": _timestamp_ms(
                getattr(fv, "last_updated_timestamp", None)
            ),
            "properties": properties,
            "schemas": [schema],
            "current-schema-id": 0,
            "last-column-id": len(schema.fields),
        }
    )

    return LoadTableResponse(
        **{
            "metadata-location": f"feast://{namespace}/tables/{fv.name}/metadata",
            "metadata": metadata,
        }
    )


# --- OnDemandFeatureView <-> View ---


def odfv_to_load_view_response(
    odfv: OnDemandFeatureView, namespace: str
) -> LoadViewResponse:
    schema = _fields_to_iceberg_schema(odfv.features or [])
    properties = dict(odfv.tags) if odfv.tags else {}
    if odfv.description:
        properties["description"] = odfv.description
    if odfv.owner:
        properties["owner"] = odfv.owner

    mode = getattr(odfv, "mode", "unknown")
    timestamp_ms = _timestamp_ms(getattr(odfv, "last_updated_timestamp", None))

    version = ViewVersion(
        **{
            "version-id": 1,
            "schema-id": 0,
            "timestamp-ms": timestamp_ms,
            "summary": {"mode": mode},
            "representations": [
                ViewRepresentation(type="feast-transformation", dialect=mode)
            ],
            "default-namespace": [namespace],
        }
    )

    metadata = ViewMetadata(
        **{
            "format-version": 1,
            "view-uuid": _make_uuid(namespace, odfv.name),
            "location": f"feast://{namespace}/views/{odfv.name}",
            "properties": properties,
            "schemas": [schema],
            "current-version-id": 1,
            "versions": [version],
        }
    )

    return LoadViewResponse(
        **{
            "metadata-location": f"feast://{namespace}/views/{odfv.name}/metadata",
            "metadata": metadata,
        }
    )


# --- DataSource <-> Volume ---


def data_source_to_volume_info(ds: DataSource, namespace: str) -> VolumeInfo:
    tags = dict(ds.tags) if ds.tags else {}
    volume_type = tags.pop("volume_type", "EXTERNAL")
    comment = tags.pop("comment", None)
    tags.pop("asset_type", None)

    location = _get_data_source_location(ds)

    return VolumeInfo(
        **{
            "name": ds.name,
            "catalog-name": namespace,
            "schema-name": "default",
            "volume-type": volume_type,
            "storage-location": location,
            "comment": comment,
            "owner": ds.owner if hasattr(ds, "owner") else None,
            "created-at": _timestamp_ms(getattr(ds, "created_timestamp", None)),
            "updated-at": _timestamp_ms(getattr(ds, "last_updated_timestamp", None)),
            "properties": tags,
        }
    )
