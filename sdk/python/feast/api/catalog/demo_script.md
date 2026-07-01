# Data Hub UI Demo Script

## Browse Catalogs page — two cards

"This is the Data Hub UI, running as a plugin in the RHOAI dashboard. What you're seeing here are catalogs — we have 'underwriting' and 'claims'. Behind the scenes, each of these is a Feast Project. The UI doesn't know that — it's talking to an Iceberg REST Catalog API, which translates everything to and from Feast automatically."

## Click on 'claims'

"Inside a catalog we see schemas. There's one called 'default' — this is a virtual schema that the API injects to follow the three-level naming convention that catalog systems like Unity Catalog use: catalog dot schema dot asset. There's no Feast object behind it — it's just a convention so that when we swap the backend to a real catalog later, all the asset paths stay the same."

## Click on 'default'

"Now we see the actual data assets — tables and volumes. The tables here, 'claims_history' and 'fraud_indicators', are backed by Feast Feature Views. Feature Views give us typed schemas — each column has a name and a data type — which is why the catalog can show proper column information. We chose Feature Views over Data Sources because Data Sources don't carry type information."

## Click on a table to show columns

"These columns — claim_id, policy_id, loss_type, claim_amount — these are the Fields defined on the Feature View, with their Feast types mapped to Iceberg types. So a Feast Int64 becomes an Iceberg 'long', Float32 becomes 'float', and so on."

## Back to schema view, point at volumes

"The volumes are the interesting part. These represent collections of unstructured documents — adjuster reports, policy documents. In Feast, each volume is stored as a Data Source with a special tag, 'asset_type equals volume'. The storage location points to an S3 bucket where the actual files live. The catalog just tracks the metadata — what exists, where it is, who owns it."

## Optionally show Add Table / Add Volume

"You can also create new assets directly from the UI. When you add a table, the UI sends a request to the catalog API, which creates a Feature View in Feast. When you add a volume, it creates a tagged Data Source. The user never interacts with Feast directly — everything goes through the standard catalog API."

## Wrap up

"The key point is that all of this is backed by Feast's existing registry — a single SQLite database. There's no separate catalog infrastructure. But the API contract follows the Iceberg REST spec, so when we're ready to migrate to a real catalog backend like Unity Catalog or Apache Polaris, we swap the implementation and nothing changes for the user — same API, same UI, same asset paths."
