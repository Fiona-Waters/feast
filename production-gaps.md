# Production Readiness — Feast Iceberg REST Catalog API + Data Hub UI

What needs to be addressed before moving from POC to production, across all three layers: **Feast Catalog API** (Python/FastAPI), **BFF** (Go), and **Frontend** (React/PatternFly).

---

## Key Areas Requiring Design & Investigation

These are the areas that will shape architectural decisions as we move toward production. Each needs further investigation or cross-team coordination.

### 1. Authentication & RBAC

**Current state:** Catalog API endpoints have zero authentication — routes are added without auth middleware (`rest_registry_server.py:80`), unlike feature server endpoints which use `Depends(inject_user_details)`. The BFF has a binary admin/non-admin check based on OpenShift header groups (`feast_client.go:68-102`), but this only controls UI visibility — it is not enforced server-side.

**What needs to happen:** **ADR 0002** (proposed, 2026-06-24) defines an SSAR middleware approach using `SelfSubjectAccessReview` against pseudo-resources in a `datacatalog.opendatahub.io` API group — the same pattern MLflow uses in RHOAI. This was validated on a ROSA cluster on 2026-06-24. Implementation involves:
- SSAR middleware in the Catalog API (~50 lines in `auth.py`)
- Three ClusterRoles (`datacatalog-view`, `datacatalog-edit`, `datacatalog-admin`) that auto-aggregate into OCP `view`/`edit`/`admin` roles
- Per-resource granularity via `resourceNames`
- Coordination with ODH Dashboard team (ClusterRole manifests) and RHOAI Operator team (deploy roles on install)

**Open questions:**
- Row/column-level ACL is out of scope for K8s RBAC — would need JCasbin/OPA as a future layer. Is this needed for initial production?
- How should cross-namespace catalog browsing work? SSAR is namespace-scoped.
- The BFF's current admin check should be replaced by SSAR — or should it remain as a UI-only hint while SSAR enforces server-side?

### 2. Multi-Schema Support

**Current state:** Only one schema ("default") is allowed per namespace (`namespaces.py:23, 27-29`). All tables and volumes live in `[namespace, "default"]`. Non-default schemas are rejected.

**What needs to happen:** Real Iceberg catalogs and Unity Catalog both use multiple schemas to organise assets within a catalog (three-level namespace: catalog.schema.asset). Supporting this requires rethinking how Feast projects map to Iceberg namespaces — currently one Feast project = one namespace, and there's no Feast concept that naturally maps to a second-level schema.

**Open questions:**
- Should schemas map to Feast sub-projects, tagged groups, or a separate metadata layer?
- Is multi-schema actually needed for the target use cases, or is the implicit "default" schema sufficient for initial production?
- How does this interact with RBAC — should permissions be grantable at schema level?

### 3. View Implementation

**Current state:** Views are stored but non-functional. They use a placeholder schema field (`views.py:93`), a hardcoded noop UDF (`views.py:104-110`), and have no update endpoint. View representations claim type "feast-transformation" but contain no real logic.

**What needs to happen:** Decide whether views should be metadata-only (storing SQL text for documentation/lineage) or executable (actually running transformations). This is constrained by Feast's `OnDemandFeatureView` model which requires a Python UDF — there's no natural place to store SQL dialect or execute it.

**Open questions:**
- Are views a required feature for initial production, or can they be deferred?
- If metadata-only, should the SQL be stored in tags/properties and surfaced in the UI?
- If executable, this likely requires upstream Feast changes or a separate execution layer.

### 4. Concurrency Control

**Current state:** Table updates (`tables.py:154-209`) do read-modify-write without isolation. Namespace deletes (`namespaces.py:88-105`) have a check-then-delete that is not atomic. Concurrent updates silently overwrite each other (last writer wins).

**What needs to happen:** Add optimistic locking. The Iceberg REST spec supports this via `If-Match` / etag headers. The question is where to store the version — Feast objects don't have a built-in version field, so it would need to be tracked in tags or a separate metadata store.

**Open questions:**
- What is the expected concurrency model? Single-user POC vs multi-team production is a big difference.
- Should version tracking live in Feast tags, or does this point toward needing a dedicated metadata store?

### 5. Audit Logging

**Current state:** There is no record of who created, modified, or deleted resources — across any layer. This is required for compliance in regulated industries, which is the primary use case for this POC.

**What needs to happen:** Add structured audit logging on all mutating operations. K8s audit log will capture SSAR calls once ADR 0002 is implemented, but that only covers auth decisions — not the actual data changes.

**Open questions:**
- Should audit events be emitted as OpenLineage events (aligning with the lineage strategy)?
- What is the retention and query model — K8s audit log, a dedicated audit store, or both?
- Does this need to capture before/after state, or just the action and actor?

### 6. Iceberg Spec Compliance

**Current state:** Several Iceberg REST Catalog v1 capabilities are not implemented:

| Capability | Status | Notes |
|-----------|--------|-------|
| Namespace CRUD | Implemented | Single schema only |
| Table CRUD | Implemented | Needs partition/sort/snapshot support |
| View CRUD | Partial | Placeholder transformations, no update endpoint |
| Volume CRUD | Implemented | Non-standard extension (Unity Catalog concept) |
| Table snapshots | Not implemented | Always returns empty |
| Table statistics | Not implemented | Column stats and row counts needed |
| Commit transactions | Not implemented | Atomic multi-table commits needed |
| Schema evolution | Not implemented | Only full replacement via PUT |
| Partition evolution | Not implemented | Partition specs always empty |
| Sort order management | Not implemented | Sort orders always empty |
| Config endpoint | Stub | Returns empty defaults/overrides |

**Open questions:**
- What is the minimum Iceberg spec coverage needed for production? Full compliance is a large effort — which capabilities do the target use cases actually need?
- Should snapshots and statistics be real (backed by actual data) or metadata-only (tracking what was registered)?
- Column evolution (add/drop/rename) is important for real-world use — is this blocked by Feast's schema model?

### 7. Permissions UI

**Current state:** The BFF has mock/stub handlers for permissions (`catalogs_handler.go:165-176`, `permissions_handler.go:44-66`). The permissions page appears to work but returns hardcoded empty responses. SCIM users endpoint returns an empty list.

**What needs to happen:** Once ADR 0002's SSAR approach is implemented, the permissions UI needs to manage RoleBindings via the K8s API rather than a custom permission backend. This changes the data model entirely — permissions become K8s objects, not catalog metadata.

**Open questions:**
- Should the Data Hub UI manage RoleBindings directly, or should users be directed to the OCP Console for permission management?
- If the UI manages permissions, it needs ServiceAccount access to create/delete RoleBindings — what are the security implications?

---

## Quick Wins & Polish

These can be addressed within the POC or as straightforward follow-up work. No design decisions needed.

### BFF

| Item | Current State | Fix |
|------|--------------|-----|
| **HTTP client per request** | `newFeastClient()` called in every handler — no connection pooling | Create a single `http.Client` at app startup, inject via `App` struct |
| **Silent error handling** | ~25 instances of discarded `json.Unmarshal`/`io.ReadAll` errors | Check all error returns, return 502 for malformed upstream responses |
| **Request timeouts** | No Read/Write/Idle timeouts on HTTP server or client | Set server timeouts, add `context.WithTimeout` to outbound requests |
| **Health endpoint** | Only checks internal state, not Feast/K8s connectivity | Add Feast connectivity check to readiness probe |
| **Rate limiting** | No rate limiting middleware | Add per-IP or per-user token bucket middleware |

### Feast Catalog API

| Item | Current State | Fix |
|------|--------------|-----|
| **Type mapping** | Only 8 of 16+ Iceberg types mapped; unmapped default to String | Extend mapping, raise error for unsupported types |
| **Pagination** | List endpoints return all results | Add `pageToken`/`pageSize` parameters |
| **Namespace delete** | Only checks feature_views, on_demand_feature_views, volumes | Check all Feast object types before allowing delete |
| **Input validation** | No length/pattern constraints on names or storage locations | Add Pydantic validators for name patterns and URI format |
| **Cache flags** | Inconsistent `allow_cache` values across endpoints | Standardise: `False` for writes, `True` with TTL for reads |
| **Search** | Naive substring match, no result limiting | Add result cap, type/owner filters |
| **CatalogConfig** | Returns empty defaults/overrides | Return warehouse location, supported features, API version |

### Frontend

| Item | Current State | Fix |
|------|--------------|-----|
| **Silent error handling** | 5+ `.catch(() => {})` calls swallowing API errors | Replace with error state display using PatternFly Alert |
| **Hardcoded POC values** | `s3://poc-underwriting/...` default paths, "DELTA" default format | Move to configuration or remove defaults |
| **API_PREFIX inconsistency** | Some pages hardcode `/data-hub/api/v1`, others import constant | Use imported `API_PREFIX` everywhere |
| **Columns display** | Empty comments show "—" which looks like missing data | Use "No description" placeholder |
| **Request timeouts** | `fetch()` calls have no AbortController/timeout | Add AbortController with timeout |
| **Accessibility** | Some clickable elements lack ARIA roles/labels | Add semantic roles and aria-labels |

---

## Summary

| Category | Count | Status |
|----------|-------|--------|
| **Key areas requiring design** | 7 | Need investigation, ADRs, or cross-team coordination |
| **Quick wins (BFF)** | 5 | Can fix in POC |
| **Quick wins (Catalog API)** | 7 | Can fix in POC |
| **Quick wins (Frontend)** | 6 | Can fix in POC |
