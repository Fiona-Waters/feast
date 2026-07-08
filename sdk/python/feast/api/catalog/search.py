from typing import List, Optional

from fastapi import APIRouter, Query

from feast import FeatureStore
from feast.api.catalog.mapping import CATALOG_MANAGED_TAG
from feast.api.catalog.models import SearchResponse, SearchResult
from feast.api.catalog.namespaces import DEFAULT_SCHEMA


def _fuzzy_match(query: str, text: str) -> bool:
    return query.lower() in text.lower()


def get_search_router(store: FeatureStore) -> APIRouter:
    router = APIRouter(tags=["iceberg-catalog-search"])

    @router.get("/search")
    def search_catalog(
        query: str = Query(..., description="Search query string"),
        namespaces: Optional[List[str]] = Query(
            default=None,
            description="Namespace names to search in (searches all if not specified)",
        ),
    ) -> SearchResponse:
        projects = store.registry.list_projects(allow_cache=True)
        project_names = [p.name for p in projects]

        if namespaces:
            project_names = [n for n in project_names if n in namespaces]

        results: list[SearchResult] = []

        for project_name in project_names:
            datasets = store.registry.list_saved_datasets(
                project=project_name,
                allow_cache=True,
                tags={CATALOG_MANAGED_TAG: "true"},
            )

            for ds in datasets:
                asset_type = ds.tags.get("asset_type", "table")
                description = ds.tags.get("comment") or ds.tags.get("description")

                if not (
                    _fuzzy_match(query, ds.name)
                    or _fuzzy_match(query, description or "")
                ):
                    continue

                ns = [project_name, ds.namespace or DEFAULT_SCHEMA]
                props = {
                    k: v
                    for k, v in ds.tags.items()
                    if k not in (CATALOG_MANAGED_TAG, "asset_type")
                }

                results.append(
                    SearchResult(
                        type=asset_type,
                        namespace=ns,
                        name=ds.name,
                        description=description,
                        properties=props,
                    )
                )

        return SearchResponse(query=query, results=results)

    return router
