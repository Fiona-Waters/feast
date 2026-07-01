# Iceberg REST Catalog API for Feast

## Overview

This document describes the implementation of an Iceberg REST Catalog API layer within the Feast registry REST server. The API exposes Feast resources through endpoints that conform to the [Apache Iceberg REST Catalog specification](https://github.com/apache/iceberg), enabling a separate catalog UI to interact with Feast without any awareness of the underlying Feast infrastructure.

The design is informed by the concept mapping document *"Feast Registry x Iceberg REST Catalog x Unity Catalog OSS"*, which defines a phased migration path from Feast-backed catalog (phase 3.6) to a real catalog backend such as Unity Catalog OSS or Apache Polaris (phase 3.7).

## Motivation

We need a catalog interface that:

1. Presents data assets (namespaces, tables, views, volumes) through a well-known, standardised API — the Iceberg REST Catalog spec.
2. Uses Feast's existing registry as the backend, requiring no new database or infrastructure.
3. Keeps the Feast layer invisible to end users — they see Iceberg concepts only.
4. Produces asset paths (`catalog.schema.asset`) that will not change when the backend is swapped from Feast to a real catalog in phase 3.7.
5. Is portable — the API contract can later be backed by a real Iceberg catalog (e.g., Apache Polaris, AWS Glue, Nessie) or Unity Catalog OSS without changing the UI or any client.

## Architecture

```
Catalog UI  -->  /v1/* endpoints (Iceberg REST spec)  -->  Feast Registry
                 Port 6572 (registry REST server)
```

The catalog API is a set of FastAPI routers mounted on the existing Feast **registry REST server** (port 6572). Catalog endpoints live under `/v1/*`, coexisting with the Feast registry API at `/api/v1/*`. There is no separate server process, no gRPC intermediary, and no new storage layer. Each endpoint translates between Iceberg request/response shapes and direct calls to `store.registry`.

### Why the registry REST server (port 6572)?

The concept mapping document assigns catalog endpoints to port 6572, alongside `/api/v1/*` (Feast registry) and `/mcp/*` (MCP tools). The feature server (port 6566) is reserved for online/offline feature serving. Mounting on the registry server means:

- Catalog and registry share the same process and `FeatureStore` instance.
- Direct in-process access to the Feast registry (no network hop).
- The `/v1/*` routes coexist cleanly with `/api/v1/*` — no path conflicts.
- The catalog module is self-contained and can be split out later if needed.

### Why `/v1/` (not `/catalog/v1/`)?

The Iceberg REST spec uses `/v1/` as its base path. Clients and catalog UIs expect this convention. Using `/v1/` directly ensures compatibility without requiring clients to configure a custom prefix. The Feast registry API uses `/api/v1/`, so there is no path collision.

## Concept Mapping

| Iceberg / UC Concept | Feast Resource | Rationale |
|----------------------|---------------|-----------|
| **Namespace** (top-level) | **Project** | Both are the top-level organisational grouping with a name and key-value properties. 1:1 mapping. |
| **Namespace** (schema-level) | *Virtual `"default"`* | Implicit second level. No Feast object — the API layer injects/strips it transparently. |
| **Table** | **Feature View** | An Iceberg table has a typed schema and a data location. A Feature View provides both: typed `Field` objects with `dtype` for the schema, and a `DataSource` for the location. |
| **View** | **On-Demand Feature View** | Both are virtual/computed rather than materialised. An Iceberg view is defined by a query; an ODFV is defined by a transformation over other sources. |
| **Volume** | **DataSource** (tagged `asset_type=volume`) | Dedicated `/volumes/` endpoints backed by Feast DataSource. Storage location in `FileSource.path`. Volume type and metadata in tags. |

### Why Feature View for tables (not Data Source)?

We initially considered Data Source, since it directly represents "here is data, here is where it lives." However, Data Source's `field_mapping` is an untyped `Dict[str, str]` — it maps column names but carries no type information. This means all table schema fields would default to `"string"` in the Iceberg response, which makes the catalog UI look broken.

Feature View solves this because its `Field` objects have a `dtype` (e.g., `Int64`, `Float32`, `String`), which maps naturally to Iceberg column types (`long`, `float`, `string`). A Feature View also carries an optional `DataSource` for the data location, so we get both typed schema and location in one resource.

The trade-off is that Feature Views include ML-specific fields (entities, TTL, materialisation) that have no Iceberg equivalent. But these are all optional and default to sensible values (no entities, no TTL, online=False). Since the customer never sees the Feast side, the unused fields are irrelevant.

### Why On-Demand Feature View for views (not a regular Feature View)?

Regular Feature Views point at stored data — they are closer to tables than views. On-Demand Feature Views are computed from transformations, making them the natural analogue for the Iceberg view concept (defined by a query, not by stored data).

## Two-Level Namespaces

### Problem

Unity Catalog and most catalog systems use three-level naming: `catalog.schema.asset`. The Iceberg REST spec supports hierarchical namespaces. Feast projects are flat (single-level). For phase 3.7 migration, asset paths must already follow the two-level namespace convention (`project.default.asset`) so they don't break when the backend is swapped.

### Constraint

Feast project names cannot contain dots — the validation regex rejects `[^\w-]+`. This rules out encoding the schema level in the project name (e.g., `underwriting.default`).

### Solution: Convention-Based Implicit `default` Schema

The API layer injects/strips a virtual `"default"` second level transparently. No Feast changes are required.

- A Feast Project `"underwriting"` is exposed as namespace `["underwriting"]` (top-level) with an implicit child `["underwriting", "default"]`.
- Tables, views, and volumes live under the two-level path: `/v1/namespaces/{project}/namespaces/default/tables/{t}`
- Only `"default"` is valid as the second-level namespace. Requests for any other value return 404.
- The `default` sub-namespace is virtual — no second Feast project is created.
- `GET /v1/namespaces` returns top-level namespaces: `[["underwriting"], ["claims"]]`
- `GET /v1/namespaces/underwriting/namespaces` returns `[["underwriting", "default"]]`

### Implementation

A helper function in `namespaces.py` validates and resolves the two-level namespace:

```python
DEFAULT_SCHEMA = "default"

def _resolve_namespace(parent: str, child: str) -> str:
    if child != DEFAULT_SCHEMA:
        raise NamespaceNotFoundException(f"{parent}.{child}")
    return parent  # Feast project name
```

All table, view, and volume routes use two-level namespace URL paths:
```
/v1/namespaces/{namespace}/namespaces/{schema}/tables/{table}
/v1/namespaces/{namespace}/namespaces/{schema}/views/{view}
/v1/namespaces/{namespace}/namespaces/{schema}/volumes/{volume}
```

Three nested namespace endpoints support discovery. The Iceberg REST spec defines hierarchical namespaces with this URL pattern (`/namespaces/{parent}/namespaces/{child}`), so these are spec-compliant. The reason we use them is UC migration: Unity Catalog requires three-level naming (`catalog.schema.table`), and baking in the `default` schema level now means asset paths won't break when the backend is swapped in phase 3.7.

- `GET /v1/namespaces/{ns}/namespaces` — lists `[["ns", "default"]]`
- `GET /v1/namespaces/{ns}/namespaces/{child}` — returns namespace details (only `default`)
- `HEAD /v1/namespaces/{ns}/namespaces/{child}` — existence check (only `default`)

## Volume Support

### Problem

Scenario B (P&C Underwriting Knowledge Assistant) manages collections of unstructured documents — underwriting guidelines, ISO forms, rating manuals, regulatory bulletins (~17,500 PDFs/DOCX across S3/MinIO). The Data Hub UI must let users create, browse, and manage these document collections from phase 3.6. Neither Feast nor Iceberg has a concept for unstructured data.

### Where volumes come from

The concept comes from Unity Catalog OSS, which defines **Volumes** as pointers to storage locations (S3/GCS/ABFSS paths) holding arbitrary files, registered in the catalog alongside tables. A Phase 2 POC validated this model: 5 PDF volumes registered in MinIO, each with `storage_location`, `volume_type` (MANAGED/EXTERNAL), `name`, `comment`, `owner`, and timestamps.

In our Kubernetes deployment, volumes point to S3/MinIO storage locations where document collections live. The catalog tracks the metadata (what exists, where it is, who owns it); the storage system holds the actual files.

### Design choice: dedicated endpoints vs. overloaded tables

Two options were evaluated in the concept mapping document:

- **Option A (chosen): Volume extension endpoints.** Add `/v1/.../namespaces/{ns}/volumes/{v}` with its own CRUD operations. Clean semantics — a volume is clearly not a table. Maps directly to UC's volume API, simplifying the phase 3.7 backend swap. Trade-off: it's a custom extension to the Iceberg REST spec.

- **Option B (rejected): Table with `asset_type` property.** Use standard Iceberg table endpoints with a property flag. No spec extension, but semantically misleading — a "table" with no columns. Engines like Spark/Trino would try to read it as tabular data. The phase 3.7 migration would need to translate table-with-property back to a UC Volume.

Option A was chosen for semantic clarity and direct UC alignment.

### Feast Backend

Volumes are stored as Feast **DataSources** with a tag `asset_type=volume`. This requires no registry schema extension:

- Storage location → `FileSource.path`
- Volume type (MANAGED/EXTERNAL) → `tags["volume_type"]`
- Comment/description → `tags["comment"]`
- Additional metadata → remaining `tags`

The `_is_volume(ds)` helper checks for the `asset_type=volume` tag to distinguish volumes from regular data sources.

### Endpoints

Six endpoints following the Iceberg REST URL convention under the two-level namespace path:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/namespaces/{ns}/namespaces/{s}/volumes` | List volumes |
| POST | `/v1/namespaces/{ns}/namespaces/{s}/volumes` | Create a volume |
| GET | `/v1/namespaces/{ns}/namespaces/{s}/volumes/{v}` | Get volume details |
| HEAD | `/v1/namespaces/{ns}/namespaces/{s}/volumes/{v}` | Check if volume exists |
| DELETE | `/v1/namespaces/{ns}/namespaces/{s}/volumes/{v}` | Delete a volume |
| PUT | `/v1/namespaces/{ns}/namespaces/{s}/volumes/{v}` | Update a volume |

### Namespace Integration

The `drop_namespace` endpoint checks for volumes (DataSources with `asset_type=volume`) in addition to tables and views before allowing deletion.

## Search Proxy

A search endpoint provides fuzzy text search across all catalog assets:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/search` | Search tables, views, and volumes by name or description |

Query parameters:
- `query` (required) — search string, matched case-insensitively as a substring
- `namespaces` (optional) — list of namespace names to restrict the search

The search scans Feature Views (→ table), On-Demand Feature Views (→ view), and DataSources with `asset_type=volume` (→ volume) across all projects (or filtered projects). Results include type, namespace, name, description, and properties.

## File Structure

```
sdk/python/feast/api/catalog/
    __init__.py      # Mounts all routers, registers error handlers
    models.py        # Pydantic models matching Iceberg REST Catalog spec
    errors.py        # Iceberg-format exceptions and FastAPI error handler
    mapping.py       # Translation between Feast objects and Iceberg responses
    namespaces.py    # Namespace endpoints (backed by Feast Project)
    tables.py        # Table endpoints (backed by Feast Feature View)
    views.py         # View endpoints (backed by Feast On-Demand Feature View)
    volumes.py       # Volume endpoints (backed by Feast DataSource)
    search.py        # Search proxy endpoint
    DESIGN.md        # This document
```

The only change to existing Feast code is three lines in `rest_registry_server.py` to call `add_catalog_routes(self.app, self.store)`.

## Key Design Decisions

### Iceberg field aliases (hyphenated JSON keys)

The Iceberg spec uses hyphenated field names (`format-version`, `table-uuid`, `schema-id`, etc.). Pydantic models use `Field(alias="format-version")` with `populate_by_name=True` so that:
- JSON responses use the hyphenated names (spec-compliant).
- Python code uses snake_case internally.

### Deterministic UUIDs

The Iceberg spec expects tables and views to have stable UUIDs. We generate these deterministically using `uuid.uuid5(NAMESPACE, "project.name")` so the same resource always produces the same UUID across reads. Random UUIDs would change on every GET, breaking clients that rely on UUID stability.

### Stubbed Iceberg metadata

Several Iceberg table metadata concepts have no Feast equivalent:

| Field | What we return | Why |
|-------|---------------|-----|
| `format-version` | Always `2` | Iceberg format v2 is current; hardcoding avoids unnecessary complexity. |
| `partition-specs` | Empty spec (`spec-id: 0`, no fields) | Feast Feature Views do not have partition specs. An empty spec is valid per the Iceberg spec. |
| `sort-orders` | Empty order (`order-id: 0`, no fields) | Same reasoning as partition specs. |
| `snapshots` | Empty list, `current-snapshot-id: -1` | Snapshots are the core of Iceberg's time-travel capability. We do not support this; -1 indicates no snapshots. |
| `metadata-location` | Synthetic `feast://` URI | There are no real Iceberg metadata files. The synthetic URI makes this explicit. |
| `location` | Extracted from the Feature View's batch source | `FileSource.path`, `BigQuerySource.table`, `KafkaSource.topic`, etc. Falls back to a synthetic `feast://` URI. |

### View creation uses a minimal ODFV

Creating a view via the Iceberg API produces a minimal On-Demand Feature View with:
- Schema fields mapped from the Iceberg request.
- A `RequestSource` as the input (the simplest valid source for an ODFV).
- Mode set to `"python"`.
- No actual transformation function.

This is a structural placeholder — the ODFV is valid in the registry but does not perform real computation. For the POC, the goal is to store and retrieve view metadata, not to execute transformations.

### Error format

The Iceberg REST spec requires errors in a specific JSON structure:

```json
{
  "error": {
    "message": "Namespace does not exist: my_project",
    "type": "NoSuchNamespaceException",
    "code": 404
  }
}
```

We define custom exception classes (`NamespaceNotFoundException`, `TableAlreadyExistsException`, `VolumeNotFoundException`, etc.) and a single FastAPI exception handler that catches the base `IcebergCatalogException` and formats the response. Route handlers catch Feast exceptions (e.g., `FeastObjectNotFoundException`) and re-raise as the appropriate Iceberg exception.

### Direct registry calls (no gRPC)

Catalog endpoints call `store.registry` directly rather than going through Feast's internal gRPC handler, because the Iceberg spec is REST/JSON-only and there is no benefit to serialising to protobuf and back within the same process.

### Deletions are permanent

The Feast registry performs hard deletes — there is no soft delete, recycle bin, or undo. When a user calls `DELETE` on a table, view, or volume, the underlying Feast object is permanently removed from the registry database. Deleting a namespace (project) cascades to delete everything under it: all feature views, data sources, entities, permissions, and related objects in a single transaction.

Feature views have a `feature_view_version_history` table that tracks past versions, but even that history is purged when the feature view is deleted.

This means the catalog API's DELETE endpoints are destructive and unrecoverable without external database backups. For production use, consider adding confirmation mechanisms, audit logging, or soft-delete support at the registry level.

### No auth

Authentication and authorisation are out of scope for the POC. The Iceberg spec includes an OAuth2 token endpoint (`POST /v1/oauth/tokens`), but the spec itself marks this endpoint as **deprecated for removal** due to security concerns. The recommended approach is to use an external identity provider (e.g., Keycloak, Auth0) rather than implementing token issuance within the catalog server. When auth is needed, it can be added as FastAPI middleware or dependencies without changing the endpoint logic.

### No prefix

The Iceberg spec supports a `{prefix}` path parameter for running multiple catalogs on the same server (e.g., `/v1/production/namespaces` vs `/v1/staging/namespaces`). We skip this — there is one catalog, and all endpoints live under `/v1/`.

## Endpoints

### Config (1)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/config` | Returns static catalog configuration |

### Namespaces — Top-Level (6)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/namespaces` | List all namespaces |
| POST | `/v1/namespaces` | Create a namespace |
| GET | `/v1/namespaces/{ns}` | Get namespace details |
| HEAD | `/v1/namespaces/{ns}` | Check if namespace exists (204/404) |
| DELETE | `/v1/namespaces/{ns}` | Drop namespace (must be empty) |
| POST | `/v1/namespaces/{ns}/properties` | Update namespace properties |

### Namespaces — Nested (3)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/namespaces/{ns}/namespaces` | List child namespaces (returns `["ns", "default"]`) |
| GET | `/v1/namespaces/{ns}/namespaces/{child}` | Get nested namespace details |
| HEAD | `/v1/namespaces/{ns}/namespaces/{child}` | Check if nested namespace exists |

### Tables (6)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/namespaces/{ns}/namespaces/{s}/tables` | List tables in namespace |
| POST | `/v1/namespaces/{ns}/namespaces/{s}/tables` | Create a table |
| GET | `/v1/namespaces/{ns}/namespaces/{s}/tables/{t}` | Load table metadata |
| HEAD | `/v1/namespaces/{ns}/namespaces/{s}/tables/{t}` | Check if table exists |
| DELETE | `/v1/namespaces/{ns}/namespaces/{s}/tables/{t}` | Drop a table |
| POST | `/v1/tables/rename` | Rename a table |

### Views (6)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/namespaces/{ns}/namespaces/{s}/views` | List views in namespace |
| POST | `/v1/namespaces/{ns}/namespaces/{s}/views` | Create a view |
| GET | `/v1/namespaces/{ns}/namespaces/{s}/views/{v}` | Load view metadata |
| HEAD | `/v1/namespaces/{ns}/namespaces/{s}/views/{v}` | Check if view exists |
| DELETE | `/v1/namespaces/{ns}/namespaces/{s}/views/{v}` | Drop a view |
| POST | `/v1/views/rename` | Rename a view |

### Volumes (6)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/namespaces/{ns}/namespaces/{s}/volumes` | List volumes in namespace |
| POST | `/v1/namespaces/{ns}/namespaces/{s}/volumes` | Create a volume |
| GET | `/v1/namespaces/{ns}/namespaces/{s}/volumes/{v}` | Get volume details |
| HEAD | `/v1/namespaces/{ns}/namespaces/{s}/volumes/{v}` | Check if volume exists |
| DELETE | `/v1/namespaces/{ns}/namespaces/{s}/volumes/{v}` | Delete a volume |
| PUT | `/v1/namespaces/{ns}/namespaces/{s}/volumes/{v}` | Update a volume |

### Search (1)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/search` | Fuzzy search across tables, views, and volumes |

**Total: 29 endpoints**

## Future Considerations

These align with the concept mapping document's phase 3.7 roadmap:

- **Real catalog backend**: The API contract is the Iceberg REST spec plus UC-aligned volume endpoints. Swapping Feast for Unity Catalog OSS, Apache Polaris, or AWS Glue requires changing only the route handler implementations — no client or UI changes. The two-level namespace convention ensures asset paths (`project.default.asset`) remain stable across the migration.
- **SSAR authentication**: The concept mapping document specifies Service-to-Service Auth with Row-level security. When auth is needed, it can be added as FastAPI middleware or dependencies without changing the endpoint logic. The Iceberg spec's built-in OAuth endpoint is deprecated; use an external identity provider.
- **Credential vending**: `POST /v1/namespaces/{ns}/namespaces/{s}/tables/{t}/credentials` for temporary S3/GCS credentials. The concept mapping document includes this as a 3.6 extension.
- **Lineage endpoints**: `GET /v1/lineage/table/{t}` for upstream/downstream dependency tracking. Listed in the concept mapping document as a 3.6 extension.
- **Table metrics reporting**: `POST /v1/namespaces/{ns}/namespaces/{s}/tables/{t}/metrics` for reporting table-level statistics (row counts, file counts, sizes). Part of the Iceberg REST spec but not needed for the POC.
- **Table registration**: `POST /v1/namespaces/{ns}/namespaces/{s}/register` for registering an existing table from a metadata file location without creating a new resource. Part of the Iceberg REST spec but not needed for the POC.
- **Multi-schema support**: Currently only `"default"` is supported as the second-level namespace. If real multi-schema support is needed before migrating to a real catalog backend, this could be implemented by encoding the schema in Feast project tags or by using a naming convention (e.g., project `underwriting__analytics`).
- **Snapshot support**: If time-travel or versioning is needed, this would require either extending the Feast registry or switching to a real Iceberg catalog backend.
