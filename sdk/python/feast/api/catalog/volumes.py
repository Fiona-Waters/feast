from fastapi import APIRouter, Response

from feast import FeatureStore
from feast.api.catalog.errors import (
    NamespaceNotFoundException,
    VolumeAlreadyExistsException,
    VolumeNotFoundException,
)
from feast.api.catalog.mapping import data_source_to_volume_info
from feast.api.catalog.models import (
    CreateVolumeRequest,
    ListVolumesResponse,
    UpdateVolumeRequest,
    VolumeInfo,
)
from feast.api.catalog.namespaces import _resolve_namespace
from feast.errors import FeastObjectNotFoundException
from feast.infra.offline_stores.file_source import FileSource

VOLUME_TAG = "asset_type"
VOLUME_TAG_VALUE = "volume"


def _is_volume(ds) -> bool:
    return (ds.tags or {}).get(VOLUME_TAG) == VOLUME_TAG_VALUE


def get_volume_router(store: FeatureStore) -> APIRouter:
    router = APIRouter(tags=["iceberg-catalog-volumes"])

    def _ensure_namespace_exists(namespace: str) -> None:
        try:
            store.registry.get_project(namespace, allow_cache=True)
        except FeastObjectNotFoundException:
            raise NamespaceNotFoundException(namespace)

    @router.get("/namespaces/{namespace}/namespaces/{schema}/volumes")
    def list_volumes(namespace: str, schema: str) -> ListVolumesResponse:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        data_sources = store.registry.list_data_sources(
            project=project, allow_cache=False, tags={VOLUME_TAG: VOLUME_TAG_VALUE}
        )
        volumes = [data_source_to_volume_info(ds, namespace) for ds in data_sources]
        return ListVolumesResponse(volumes=volumes)

    @router.post("/namespaces/{namespace}/namespaces/{schema}/volumes", status_code=200)
    def create_volume(
        namespace: str, schema: str, request: CreateVolumeRequest
    ) -> VolumeInfo:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)

        existing = store.registry.list_data_sources(
            project=project, allow_cache=False, tags={VOLUME_TAG: VOLUME_TAG_VALUE}
        )
        for ds in existing:
            if ds.name == request.name:
                raise VolumeAlreadyExistsException(namespace, request.name)

        tags = dict(request.properties) if request.properties else {}
        tags[VOLUME_TAG] = VOLUME_TAG_VALUE
        tags["volume_type"] = request.volume_type
        if request.comment:
            tags["comment"] = request.comment

        source = FileSource(
            name=request.name,
            path=request.storage_location,
            timestamp_field="",
            tags=tags,
        )
        store.registry.apply_data_source(source, project=project, commit=True)
        return data_source_to_volume_info(source, namespace)

    @router.get("/namespaces/{namespace}/namespaces/{schema}/volumes/{volume}")
    def get_volume(namespace: str, schema: str, volume: str) -> VolumeInfo:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            ds = store.registry.get_data_source(
                volume, project=project, allow_cache=True
            )
        except FeastObjectNotFoundException:
            raise VolumeNotFoundException(namespace, volume)
        if not _is_volume(ds):
            raise VolumeNotFoundException(namespace, volume)
        return data_source_to_volume_info(ds, namespace)

    @router.head("/namespaces/{namespace}/namespaces/{schema}/volumes/{volume}")
    def volume_exists(namespace: str, schema: str, volume: str) -> Response:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            ds = store.registry.get_data_source(
                volume, project=project, allow_cache=True
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
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            ds = store.registry.get_data_source(
                volume, project=project, allow_cache=False
            )
        except FeastObjectNotFoundException:
            raise VolumeNotFoundException(namespace, volume)
        if not _is_volume(ds):
            raise VolumeNotFoundException(namespace, volume)
        store.registry.delete_data_source(volume, project=project, commit=True)
        return Response(status_code=204)

    @router.put("/namespaces/{namespace}/namespaces/{schema}/volumes/{volume}")
    def update_volume(
        namespace: str, schema: str, volume: str, request: UpdateVolumeRequest
    ) -> VolumeInfo:
        project = _resolve_namespace(namespace, schema)
        _ensure_namespace_exists(project)
        try:
            ds = store.registry.get_data_source(
                volume, project=project, allow_cache=False
            )
        except FeastObjectNotFoundException:
            raise VolumeNotFoundException(namespace, volume)
        if not _is_volume(ds):
            raise VolumeNotFoundException(namespace, volume)

        tags = dict(ds.tags) if ds.tags else {}
        if request.comment is not None:
            tags["comment"] = request.comment
        if request.properties:
            for k, v in request.properties.items():
                tags[k] = v

        owner = request.owner if request.owner is not None else (ds.owner or "")

        path = ds.path if hasattr(ds, "path") else ""
        if request.storage_location is not None:
            path = request.storage_location

        updated = FileSource(
            name=ds.name,
            path=path,
            timestamp_field="",
            tags=tags,
            owner=owner,
        )
        store.registry.apply_data_source(updated, project=project, commit=True)
        return data_source_to_volume_info(updated, namespace)

    return router
