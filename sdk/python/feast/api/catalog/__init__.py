from fastapi import FastAPI

from feast import FeatureStore
from feast.api.catalog.errors import register_iceberg_exception_handlers
from feast.api.catalog.models import CatalogConfig
from feast.api.catalog.namespaces import get_namespace_router
from feast.api.catalog.search import get_search_router
from feast.api.catalog.tables import get_table_router
from feast.api.catalog.views import get_view_router
from feast.api.catalog.volumes import get_volume_router


def add_catalog_routes(app: FastAPI, store: FeatureStore) -> None:
    register_iceberg_exception_handlers(app)

    prefix = "/v1"

    @app.get(f"{prefix}/config")
    def catalog_config() -> CatalogConfig:
        return CatalogConfig()

    app.include_router(get_namespace_router(store), prefix=prefix)
    app.include_router(get_table_router(store), prefix=prefix)
    app.include_router(get_view_router(store), prefix=prefix)
    app.include_router(get_volume_router(store), prefix=prefix)
    app.include_router(get_search_router(store), prefix=prefix)
