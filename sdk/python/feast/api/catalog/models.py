from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class IcebergErrorDetail(BaseModel):
    message: str
    type: str
    code: int


class IcebergErrorResponse(BaseModel):
    error: IcebergErrorDetail


# --- Namespace models ---


class CreateNamespaceRequest(BaseModel):
    namespace: List[str]
    properties: Optional[Dict[str, str]] = None


class NamespaceResponse(BaseModel):
    namespace: List[str]
    properties: Dict[str, str]


class ListNamespacesResponse(BaseModel):
    namespaces: List[List[str]]


class UpdateNamespacePropertiesRequest(BaseModel):
    removals: Optional[List[str]] = None
    updates: Optional[Dict[str, str]] = None


class UpdateNamespacePropertiesResponse(BaseModel):
    removed: List[str]
    updated: List[str]
    missing: List[str]


# --- Table models ---


class TableIdentifier(BaseModel):
    namespace: List[str]
    name: str


class IcebergField(BaseModel):
    id: int
    name: str
    required: bool
    type: str


class IcebergSchema(BaseModel):
    type: str = "struct"
    schema_id: int = Field(default=0, alias="schema-id")
    fields: List[IcebergField] = []

    model_config = {"populate_by_name": True}


class PartitionSpec(BaseModel):
    spec_id: int = Field(default=0, alias="spec-id")
    fields: List[Any] = []

    model_config = {"populate_by_name": True}


class SortOrder(BaseModel):
    order_id: int = Field(default=0, alias="order-id")
    fields: List[Any] = []

    model_config = {"populate_by_name": True}


class TableMetadata(BaseModel):
    format_version: int = Field(default=2, alias="format-version")
    table_uuid: str = Field(alias="table-uuid")
    location: str
    last_updated_ms: int = Field(alias="last-updated-ms")
    properties: Dict[str, str]
    schemas: List[IcebergSchema]
    current_schema_id: int = Field(default=0, alias="current-schema-id")
    partition_specs: List[PartitionSpec] = Field(
        default_factory=lambda: [PartitionSpec()], alias="partition-specs"
    )
    default_spec_id: int = Field(default=0, alias="default-spec-id")
    sort_orders: List[SortOrder] = Field(
        default_factory=lambda: [SortOrder()], alias="sort-orders"
    )
    default_sort_order_id: int = Field(default=0, alias="default-sort-order-id")
    last_column_id: int = Field(default=0, alias="last-column-id")
    snapshots: List[Any] = []
    current_snapshot_id: int = Field(default=-1, alias="current-snapshot-id")

    model_config = {"populate_by_name": True}


class LoadTableResponse(BaseModel):
    metadata_location: str = Field(alias="metadata-location")
    metadata: TableMetadata
    config: Dict[str, str] = {}

    model_config = {"populate_by_name": True}


class CreateTableRequest(BaseModel):
    name: str
    schema_: IcebergSchema = Field(alias="schema")
    location: Optional[str] = None
    properties: Optional[Dict[str, str]] = None
    partition_spec: Optional[PartitionSpec] = Field(
        default=None, alias="partition-spec"
    )
    sort_order: Optional[SortOrder] = Field(default=None, alias="sort-order")

    model_config = {"populate_by_name": True}


class ListTablesResponse(BaseModel):
    identifiers: List[TableIdentifier]


class RenameTableRequest(BaseModel):
    source: TableIdentifier
    destination: TableIdentifier


class UpdateTableRequest(BaseModel):
    description: Optional[str] = None
    owner: Optional[str] = None
    location: Optional[str] = None
    data_source_format: Optional[str] = None
    schema_: Optional[IcebergSchema] = Field(default=None, alias="schema")
    properties: Optional[Dict[str, str]] = None

    model_config = {"populate_by_name": True}


# --- View models ---


class ViewRepresentation(BaseModel):
    type: str
    sql: Optional[str] = None
    dialect: Optional[str] = None


class ViewVersion(BaseModel):
    version_id: int = Field(alias="version-id")
    schema_id: int = Field(alias="schema-id")
    timestamp_ms: int = Field(alias="timestamp-ms")
    summary: Dict[str, str] = {}
    representations: List[ViewRepresentation] = []
    default_namespace: List[str] = Field(default=[], alias="default-namespace")

    model_config = {"populate_by_name": True}


class ViewMetadata(BaseModel):
    format_version: int = Field(default=1, alias="format-version")
    view_uuid: str = Field(alias="view-uuid")
    location: str
    properties: Dict[str, str]
    schemas: List[IcebergSchema]
    current_version_id: int = Field(alias="current-version-id")
    versions: List[ViewVersion]

    model_config = {"populate_by_name": True}


class LoadViewResponse(BaseModel):
    metadata_location: str = Field(alias="metadata-location")
    metadata: ViewMetadata
    config: Dict[str, str] = {}

    model_config = {"populate_by_name": True}


class CreateViewRequest(BaseModel):
    name: str
    schema_: IcebergSchema = Field(alias="schema")
    location: Optional[str] = None
    properties: Optional[Dict[str, str]] = None
    view_version: Optional[ViewVersion] = Field(default=None, alias="view-version")

    model_config = {"populate_by_name": True}


# --- Config model ---


class CatalogConfig(BaseModel):
    defaults: Dict[str, str] = {}
    overrides: Dict[str, str] = {}


# --- Volume models ---


class VolumeInfo(BaseModel):
    name: str
    catalog_name: str = Field(alias="catalog-name")
    schema_name: str = Field(alias="schema-name")
    volume_type: str = Field(alias="volume-type")
    storage_location: str = Field(alias="storage-location")
    comment: Optional[str] = None
    owner: Optional[str] = None
    created_at: Optional[int] = Field(default=None, alias="created-at")
    updated_at: Optional[int] = Field(default=None, alias="updated-at")
    properties: Dict[str, str] = {}

    model_config = {"populate_by_name": True}


class CreateVolumeRequest(BaseModel):
    name: str
    volume_type: str = Field(alias="volume-type")
    storage_location: str = Field(alias="storage-location")
    comment: Optional[str] = None
    properties: Optional[Dict[str, str]] = None

    model_config = {"populate_by_name": True}


class UpdateVolumeRequest(BaseModel):
    comment: Optional[str] = None
    owner: Optional[str] = None
    storage_location: Optional[str] = Field(default=None, alias="storage_location")
    properties: Optional[Dict[str, str]] = None


class ListVolumesResponse(BaseModel):
    volumes: List[VolumeInfo]


# --- Search models ---


class SearchResult(BaseModel):
    type: str
    namespace: List[str]
    name: str
    description: Optional[str] = None
    properties: Dict[str, str] = {}


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
