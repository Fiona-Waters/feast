from typing import List, Optional

from fastapi import APIRouter, Query

from feast import FeatureStore
from feast.api.catalog.models import SearchResponse, SearchResult
from feast.api.catalog.namespaces import DEFAULT_SCHEMA
from feast.api.catalog.volumes import _is_volume

CATALOG_ASSET_TYPES = {"table", "view", "volume"}


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
            ns = [project_name, DEFAULT_SCHEMA]

            feature_views = store.registry.list_feature_views(
                project=project_name, allow_cache=True
            )
            for fv in feature_views:
                if _fuzzy_match(query, fv.name) or _fuzzy_match(
                    query, fv.description or ""
                ):
                    props = dict(fv.tags) if fv.tags else {}
                    if fv.owner:
                        props["owner"] = fv.owner
                    results.append(
                        SearchResult(
                            type="table",
                            namespace=ns,
                            name=fv.name,
                            description=fv.description,
                            properties=props,
                        )
                    )

            odfvs = store.registry.list_on_demand_feature_views(
                project=project_name, allow_cache=True
            )
            for odfv in odfvs:
                if _fuzzy_match(query, odfv.name) or _fuzzy_match(
                    query, odfv.description or ""
                ):
                    props = dict(odfv.tags) if odfv.tags else {}
                    if odfv.owner:
                        props["owner"] = odfv.owner
                    results.append(
                        SearchResult(
                            type="view",
                            namespace=ns,
                            name=odfv.name,
                            description=odfv.description,
                            properties=props,
                        )
                    )

            data_sources = store.registry.list_data_sources(
                project=project_name, allow_cache=True
            )
            for ds in data_sources:
                if not _is_volume(ds):
                    continue
                if _fuzzy_match(query, ds.name) or _fuzzy_match(
                    query, (ds.tags or {}).get("comment", "")
                ):
                    props = dict(ds.tags) if ds.tags else {}
                    results.append(
                        SearchResult(
                            type="volume",
                            namespace=ns,
                            name=ds.name,
                            description=props.get("comment"),
                            properties=props,
                        )
                    )

        return SearchResponse(query=query, results=results)

    return router
