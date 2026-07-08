# Data Hub UI — Setup Guide

## Repositories

| Component | Repository | Description |
|-----------|------------|-------------|
| **Feast + Catalog API** | [Fiona-Waters/feast @ catalog-api](https://github.com/Fiona-Waters/feast/tree/catalog-api) | Feast registry + Iceberg REST Catalog API (Python/FastAPI) |
| **Data Hub UI + BFF** | [Fiona-Waters/odh-dashboard @ data-hub-ui-midstream](https://github.com/Fiona-Waters/odh-dashboard/tree/data-hub-ui-midstream) | React frontend + Go BFF, under `packages/data-hub/` |

## Architecture

```
Browser
  |
  v
Data Hub UI (React / PatternFly)
  |  port 4000
  v
BFF (Go / httprouter)
  |  proxies to Feast via HTTP
  v
Feast Registry REST Server (Python / FastAPI)
  |  port 6572
  |  /v1/*  = Iceberg REST Catalog API (namespaces, tables, views, volumes)
  |  /api/v1/* = Feast Registry API
  v
Feast Registry (SQLAlchemy — SQLite or PostgreSQL)
```

The BFF acts as a passthrough proxy. It translates frontend routes (`/data-hub/api/v1/catalogs/...`) into Feast Catalog API calls (`/v1/namespaces/...`), handles identity injection from OpenShift headers, and serves the static React bundle.

### RHOAI Dashboard Integration

The Data Hub UI is injected into the RHOAI (Red Hat OpenShift AI) dashboard as a plugin extension. The extension system registers:

- A **nav section** ("Data Hub") in the left sidebar under group `4_data_hub`
- A **nav item** ("Browse collections") linking to `/data-hub/main-view`
- **Routes** for `/data-hub/main-view/*`, `/data-hub/permissions/*`, and `/data-hub/apps/*`

These are defined in `packages/data-hub/frontend/src/odh/extensions.ts`. The dashboard loads the Data Hub plugin and renders it within the existing RHOAI shell (header, sidebar, auth).

For the POC deployment, the RHOAI operator must be scaled down to prevent it from reverting manual changes:

```bash
# Scale down (required for POC)
kubectl scale deployment rhods-operator -n redhat-ods-operator --replicas=0
```

> **IMPORTANT:** The operator must be scaled back up when the POC is complete:
> ```bash
> kubectl scale deployment rhods-operator -n redhat-ods-operator --replicas=1
> ```

## Container Images

Two images need to be built and deployed:

| Image | Source | Dockerfile | Ports | Pre-built |
|-------|--------|------------|-------|-----------|
| `feast-server` | Feast repo root | `sdk/python/feast/infra/feature_servers/multicloud/Dockerfile.dev` | 6566 (features), 6572 (registry + catalog API) | `quay.io/rh_ee_fwaters/feast-server:v0.4` |
| `data-hub-ui` | `packages/data-hub/` in odh-dashboard | `packages/data-hub/Dockerfile.prebuilt` | 4000 (BFF + static UI) | `quay.io/rh_ee_fwaters/data-hub-ui:v0.7` |

## Prerequisites

- Node.js 22+
- Go 1.22+
- Python 3.12+
- Docker (with `--platform linux/amd64` for cross-architecture builds)
- `oc` or `kubectl` CLI (for deployment)

## Building

### Feast Server Image

From the **feast repo root**:

```bash
docker build --platform linux/amd64 --progress=plain \
  -t quay.io/<your-registry>/feast-server:<tag> \
  -f sdk/python/feast/infra/feature_servers/multicloud/Dockerfile.dev .

docker push quay.io/<your-registry>/feast-server:<tag>
```

This builds Feast from source including the Catalog API. The Dockerfile installs all Python dependencies and builds the Feast UI.

### Data Hub UI Image

From `packages/data-hub/` in the **odh-dashboard repo**:

**Step 1 — Cross-compile the Go BFF binary:**

```bash
cd packages/data-hub/bff
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o ../bff-linux-amd64 ./cmd/
```

**Step 2 — Build the container image:**

```bash
cd packages/data-hub
docker build --platform linux/amd64 \
  -t quay.io/<your-registry>/data-hub-ui:<tag> \
  -f Dockerfile.prebuilt .

docker push quay.io/<your-registry>/data-hub-ui:<tag>
```

The `Dockerfile.prebuilt` builds the React frontend via `npm run build:prod`, then combines it with the pre-compiled Go binary into a distroless image.

> **Important:** Never reuse image tags when deploying to Kubernetes. Nodes cache images by tag, so a reused tag will serve the old image. Always increment (v0.1 -> v0.2 -> v0.3).

## Deploying to OpenShift / Kubernetes

A sample deployment manifest is at `packages/data-hub/deploy/data-hub-ui.yaml`. Update the `image` field to match your built image before applying:

```bash
kubectl apply -f packages/data-hub/deploy/data-hub-ui.yaml
```

The Feast server needs its own deployment (not included in this repo — typically deployed via Helm or a custom manifest).

### Environment Variables

The BFF container accepts the following environment variables:

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `PORT` | Yes | Port the BFF listens on | `4000` |
| `FEAST_CATALOG_URL` | Yes | Internal URL of the Feast registry REST server | `http://feast-server.option2-poc.svc:6572` |
| `DEPLOYMENT_MODE` | Yes | Set to `federated` to skip BFF auth (auth handled by OpenShift proxy) | `federated` |
| `ADMIN_GROUP` | No | OpenShift group name for admin users (enables create/edit/delete UI) | `rhods-admins` |
| `MILVUS_URL` | No | Milvus endpoint for volume provenance stats | `http://milvus.ns.svc:19530` |
| `MILVUS_COLLECTION` | No | Default Milvus collection name | `underwriting_guidelines` |
| `MARQUEZ_URL` | No | Marquez UI URL (for table lineage links) | `https://marquez.example.com` |
| `MARQUEZ_API_URL` | No | Marquez API URL (for table version history) | `http://marquez-api.ns.svc:5000` |
| `MLFLOW_URL` | No | MLflow tracking server URL (for experiment traces) | `https://mlflow.example.com` |
| `MLFLOW_EXPERIMENT_ID` | No | Default MLflow experiment ID | `59` |
| `MLFLOW_WORKSPACE` | No | MLflow workspace/namespace | `fwaters` |

## Key Source Files

### Feast Catalog API (`sdk/python/feast/api/catalog/`)

| File | Purpose |
|------|---------|
| `__init__.py` | Mounts all routers on the FastAPI app under `/v1/` |
| `models.py` | Pydantic request/response models (Iceberg REST spec shapes) |
| `errors.py` | Iceberg-format error exceptions and FastAPI error handler |
| `mapping.py` | Translation between Feast objects and Iceberg responses |
| `namespaces.py` | Namespace CRUD (backed by Feast Project) |
| `tables.py` | Table CRUD (backed by Feast FeatureView) |
| `views.py` | View CRUD (backed by Feast OnDemandFeatureView) |
| `volumes.py` | Volume CRUD (backed by Feast DataSource with `asset_type=volume` tag) |
| `search.py` | Fuzzy search across all asset types |

### BFF (`packages/data-hub/bff/internal/api/`)

| File | Purpose |
|------|---------|
| `app.go` | Route registration, middleware stack, mux setup |
| `feast_client.go` | HTTP client for proxying requests to Feast |
| `schema_handler.go` | Table/volume list, create, delete, and update handlers |
| `catalogs_handler.go` | Collection (namespace) list, create, delete, detail handlers |
| `catalog_detail_handler.go` | Fetches and assembles full catalog detail (schemas, tables, volumes) |
| `provenance_handler.go` | Milvus stats proxy for volume provenance |
| `table_versions_handler.go` | Marquez proxy for table version history |
| `traces_handler.go` | MLflow traces proxy |
| `config_handler.go` | Returns UI configuration (Marquez/MLflow URLs) |

### Frontend (`packages/data-hub/frontend/src/app/pages/`)

| File | Purpose |
|------|---------|
| `MainPage.tsx` | Collection gallery with create, edit, delete |
| `CatalogDetailPage.tsx` | Collection detail — lists schemas, tabs for tables/volumes |
| `SchemaDetailPage.tsx` | Table and volume cards with create, edit, delete modals |
| `VolumeProvenancePage.tsx` | Milvus stats display for a volume |
| `TableProvenancePage.tsx` | Marquez version history for a table |
| `AdminPage.tsx` | Admin settings page |
| `PermissionsPage.tsx` | Collection-level permissions management |
| `AppsPage.tsx` | Registered applications page |

## API Routes

The BFF proxies frontend requests to Feast. Key route mappings:

| Frontend (BFF) | Feast Catalog API | Method |
|----------------|-------------------|--------|
| `/data-hub/api/v1/catalogs` | `GET /v1/namespaces` | GET (list) |
| `/data-hub/api/v1/catalogs` | `POST /v1/namespaces` | POST (create) |
| `/data-hub/api/v1/catalogs/:name` | `DELETE /v1/namespaces/:ns` | DELETE |
| `/data-hub/api/v1/catalogs/:name/properties` | `POST /v1/namespaces/:ns/properties` | POST (update) |
| `.../schemas/:schema/tables` | `GET /v1/namespaces/:ns/namespaces/:s/tables` | GET (list) |
| `.../schemas/:schema/tables` | `POST /v1/namespaces/:ns/namespaces/:s/tables` | POST (create) |
| `.../tables/:table` | `DELETE /v1/namespaces/:ns/namespaces/:s/tables/:t` | DELETE |
| `.../tables/:table/update` | `PUT /v1/namespaces/:ns/namespaces/:s/tables/:t` | POST→PUT |
| `.../schemas/:schema/volumes` | `GET /v1/namespaces/:ns/namespaces/:s/volumes` | GET (list) |
| `.../schemas/:schema/volumes` | `POST /v1/namespaces/:ns/namespaces/:s/volumes` | POST (create) |
| `.../volumes/:volume` | `DELETE /v1/namespaces/:ns/namespaces/:s/volumes/:v` | DELETE |
| `.../volumes/:volume/update` | `PUT /v1/namespaces/:ns/namespaces/:s/volumes/:v` | POST→PUT |

Note: the BFF accepts POST for table/volume updates (with `/update` suffix) and forwards them as PUT to Feast. This works around OpenShift gateway proxies that block PUT requests.

## Local Development

### Frontend only (against a remote BFF)

```bash
cd packages/data-hub/frontend
npm install
npm run start:dev
```

This starts a webpack dev server. Configure the proxy target in `webpack.config.js` to point at your BFF instance.

### BFF only

```bash
cd packages/data-hub/bff
export FEAST_CATALOG_URL=http://localhost:6572
export DEPLOYMENT_MODE=federated
export PORT=4000
go run ./cmd/
```

### Feast server (for local Catalog API)

Requires a `feature_store.yaml` in the working directory configuring the registry backend (SQLite, PostgreSQL, etc.).

```bash
cd <feast-repo>
pip install -e ".[minimal]"
cd <directory-with-feature_store.yaml>
feast serve_registry  # starts gRPC + REST on port 6572
```

Or use the pre-built Docker image.

## Current State & Known Issues

**Working:**
- Create, view, delete collections (namespaces)
- Create, view, delete tables and volumes
- Edit collection descriptions
- Delete with error message for non-empty collections
- Search (basic fuzzy match)
- Volume provenance (Milvus stats)
- Table version history (Marquez integration)
- MLflow traces display

**Known issues:**
- Edit table/volume — save button does nothing (error silently swallowed; fix is coded but not yet deployed)
- Tables/volumes require manual page refresh after creation to appear
- Table columns display shows "id int -" (dash looks like something is missing)
- Table format is hardcoded to "ICEBERG" in `catalog_detail_handler.go` instead of reading from properties

## Design Overview

- The Catalog API implements the [Iceberg REST Catalog spec](https://github.com/apache/iceberg) (29 endpoints)
- Feast resources are mapped to Iceberg concepts: Project → Namespace, FeatureView → Table, OnDemandFeatureView → View, DataSource → Volume
- Two-level namespaces with an implicit `default` schema (for future Unity Catalog migration)
- The API is designed to be backend-swappable — the same contract can be backed by Apache Polaris, AWS Glue, or Unity Catalog OSS
