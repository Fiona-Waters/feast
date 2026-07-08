from fastapi import APIRouter, Response

from feast import FeatureStore
from feast.api.catalog.errors import (
    NamespaceNotFoundException,
    VolumeAlreadyExistsException,
    VolumeNotFoundException,
)
from feast.api.catalog.mapping import (
    CATALOG_MANAGED_TAG,
    saved_dataset_to_volume_info,
)
from feast.api.catalog.models import (
    CreateVolumeRequest,
    ListVolumesResponse,
    UpdateVolumeRequest,
    VolumeInfo,
)
from feast.api.catalog.namespaces import resolve_namespace
from feast.errors import FeastObjectNotFoundException
from feast.saved_dataset import SavedDataset

VOLUME_ASSET_TYPE = "volume"


def _is_volume(ds: SavedDataset) -> bool:
    return ds.tags.get("asset_type") == VOLUME_ASSET_TYPE


def get_volume_router(store: FeatureStore) -> APIRouter:
    router = APIRouter(tags=["iceberg-catalog-volumes"])

    def _ensure_namespace_exists(namespace: str) -> None:
        try:
            store.registry.get_project(namespace, allow_cache=True)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)

    @router.get("/namespaces/{namespace}/namespaces/{schema}/volumes")
    def list_volumes(namespace: str, schema: str) -> ListVolumesResponse:
        project = resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        datasets = store.registry.list_saved_datasets(
            project=project,
            allow_cache=False,
            tags={CATALOG_MANAGED_TAG: "true", "asset_type": VOLUME_ASSET_TYPE},
            namespace=schema,
        )
        return ListVolumesResponse(
            volumes=[saved_dataset_to_volume_info(ds, namespace) for ds in datasets]
        )

    @router.post("/namespaces/{namespace}/namespaces/{schema}/volumes", status_code=200)
    def create_volume(
        namespace: str, schema: str, request: CreateVolumeRequest
    ) -> VolumeInfo:
        project = resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)

        try:
            existing = store.registry.get_saved_dataset(
                request.name, project=project, allow_cache=False, namespace=schema
            )
            if _is_volume(existing):
                raise VolumeAlreadyExistsException(namespace, request.name)
        except FeastObjectNotFoundException:
            pass

        tags = dict(request.properties) if request.properties else {}
        tags[CATALOG_MANAGED_TAG] = "true"
        tags["asset_type"] = VOLUME_ASSET_TYPE
        tags["volume_type"] = request.volume_type
        tags["location"] = request.storage_location
        if request.comment:
            tags["comment"] = request.comment

        ds = SavedDataset(
            name=request.name,
            tags=tags,
            namespace=schema,
            data_source_ref=request.data_source_ref or "",
        )
        store.registry.apply_saved_dataset(ds, project=project, commit=True)
        return saved_dataset_to_volume_info(ds, namespace)

    @router.get("/namespaces/{namespace}/namespaces/{schema}/volumes/{volume}")
    def get_volume(namespace: str, schema: str, volume: str) -> VolumeInfo:
        project = resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            ds = store.registry.get_saved_dataset(
                volume, project=project, allow_cache=True, namespace=schema
            )
        except FeastObjectNotFoundException:
            raise VolumeNotFoundException(namespace, volume)
        if not _is_volume(ds):
            raise VolumeNotFoundException(namespace, volume)
        return saved_dataset_to_volume_info(ds, namespace)

    @router.head("/namespaces/{namespace}/namespaces/{schema}/volumes/{volume}")
    def volume_exists(namespace: str, schema: str, volume: str) -> Response:
        project = resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            ds = store.registry.get_saved_dataset(
                volume, project=project, allow_cache=True, namespace=schema
            )
        except FeastObjectNotFoundException:
            raise VolumeNotFoundException(namespace, volume)
        if not _is_volume(ds):
            raise VolumeNotFoundException(namespace, volume)
        return Response(status_code=204)

    @router.delete(
        "/namespaces/{namespace}/namespaces/{schema}/volumes/{volume}", status_code=204
    )
    def delete_volume(namespace: str, schema: str, volume: str) -> Response:
        project = resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            ds = store.registry.get_saved_dataset(
                volume, project=project, allow_cache=False, namespace=schema
            )
        except FeastObjectNotFoundException:
            raise VolumeNotFoundException(namespace, volume)
        if not _is_volume(ds):
            raise VolumeNotFoundException(namespace, volume)
        store.registry.delete_saved_dataset(
            volume, project=project, commit=True, namespace=schema
        )
        return Response(status_code=204)

    @router.put("/namespaces/{namespace}/namespaces/{schema}/volumes/{volume}")
    def update_volume(
        namespace: str, schema: str, volume: str, request: UpdateVolumeRequest
    ) -> VolumeInfo:
        project = resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            ds = store.registry.get_saved_dataset(
                volume, project=project, allow_cache=False, namespace=schema
            )
        except FeastObjectNotFoundException:
            raise VolumeNotFoundException(namespace, volume)
        if not _is_volume(ds):
            raise VolumeNotFoundException(namespace, volume)

        tags = dict(ds.tags)
        if request.comment is not None:
            tags["comment"] = request.comment
        if request.properties:
            tags.update(request.properties)
        if request.storage_location is not None:
            tags["location"] = request.storage_location

        data_source_ref = ds.data_source_ref
        if request.data_source_ref is not None:
            data_source_ref = request.data_source_ref

        updated = SavedDataset(
            name=ds.name,
            tags=tags,
            namespace=schema,
            data_source_ref=data_source_ref,
        )
        updated.created_timestamp = ds.created_timestamp
        store.registry.apply_saved_dataset(updated, project=project, commit=True)
        return saved_dataset_to_volume_info(updated, namespace)

    return router
