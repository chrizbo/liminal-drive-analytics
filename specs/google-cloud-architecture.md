# Google Cloud Architecture

## Direction

Use Google Cloud as the first production platform. It keeps the service close to the Google APIs being indexed, fits the current FastAPI/Python implementation, and avoids adding another cloud vendor before the product shape is validated.

The hosted service should run in its own Google Cloud project, attached to the existing account or billing setup. This keeps IAM, OAuth consent, quotas, secrets, logs, and customer/research data separate from unrelated projects. See [Google Cloud Project Setup](google-cloud-project-setup.md).

## Proposed Beta Stack

| Need | Google Cloud Service | Notes |
|---|---|---|
| Web/API service | Cloud Run | Hosts FastAPI and serves the static app, or API only if the frontend is split later. |
| Indexing worker | Cloud Run Jobs or worker service | Runs Drive indexing outside request/response lifecycle. |
| Scheduled refresh | Cloud Scheduler | Triggers recurring crawl planning for active workspaces. |
| Async job dispatch | Cloud Tasks or Pub/Sub | Keeps indexing retries and concurrency controlled. |
| Secrets | Secret Manager | OAuth client secret, token encryption keys, app secrets. |
| Token and field encryption | Cloud KMS | Encrypt refresh tokens, tenant data keys, and other sensitive per-tenant fields. |
| Relational app data | Cloud SQL for PostgreSQL | Users, tenants, memberships, jobs, findings, review events. |
| Analytics/graph data | PostgreSQL first, BigQuery later | Start simple; move heavy historical analytics to BigQuery if needed. |
| Object storage | Cloud Storage | Optional storage for graph snapshots, exports, and job artifacts. |
| Observability | Cloud Logging/Error Reporting | Structured service and job logs. |

## Why PostgreSQL First

The local app already uses SQLite tables for documents, links, snapshots, findings, and briefs. PostgreSQL is the least surprising hosted migration:

- SQL schema maps cleanly from SQLite.
- Tenant isolation can be expressed with `tenant_id` and `workspace_id`.
- It supports JSON fields for evidence and deterministic brief payloads.
- It avoids over-committing to BigQuery or Firestore before query patterns stabilize.

BigQuery can be introduced later for historical activity snapshots, large aggregate queries, and trend analysis across many customers.

## Drive Access and Encryption Model

Separate Drive access authority, credential encryption, and stored data encryption. They protect different parts of the system and have different product effects.

### Drive Access Authority

Drive access controls what the crawler can read from Google:

- User OAuth for the first private beta.
- Selected Shared Drives or bounded folder roots as the crawl boundary.
- Workspace admin/domain-wide delegation as a later deployment mode.
- Access health recorded per tenant/workspace.

The crawler should never rely only on the credential's maximum possible access. It should enforce the tenant's selected Drive roots before fetching or storing data.

### Platform Encryption

Cloud SQL, Cloud Storage, backups, and logs should use Google Cloud encryption at rest. This is the baseline and should be enabled for every deployment.

### Credential Encryption

Credential encryption protects Google access secrets:

- OAuth refresh tokens.
- Connection secrets.
- Future delegated-access credentials.

Use envelope encryption backed by Cloud KMS. Deleting or revoking credential material should stop future crawls, but should not automatically delete already indexed data.

### Stored Data Encryption

Some customer data should be encrypted by the application before it reaches the database:

- Tenant data encryption keys.
- Sensitive fields such as owner emails, contributor emails, private URLs, review notes, and any future document excerpts.

The app can use envelope encryption: a tenant-level data encryption key encrypts fields, and Cloud KMS wraps that tenant key. This limits blast radius if one tenant's key material needs rotation or deletion.

Deleting tenant data key material should make encrypted stored fields unreadable or destroy them, depending on implementation. That should be treated as a data-deletion/security action, not as the same thing as disconnecting Google Drive.

### Queryable Analytics Data

Keep derived analytics queryable inside each tenant boundary:

- document IDs needed for joins and incremental updates
- link edges
- activity counts
- freshness timestamps
- severity scores
- finding status and disposition
- aggregate term frequencies

Encrypting these fields would make graph traversal, trend reporting, and scheduled indexing much harder. For beta, tenant isolation plus queryable derived metrics is more useful than encrypting every row-level fact.

Cross-tenant product reporting, if ever needed, should use anonymized aggregate data only. The private beta should not depend on cross-tenant analytics.

### Operational Separation

| Concern | Primary Storage | Used By | Deletion/Revocation Effect |
|---|---|---|---|
| Drive access grants | `google_connections` plus encrypted credentials | Crawlers | Stops future crawling. |
| Tenant crawl boundaries | `workspaces` and selected Drive root config | Crawlers and UI | Limits what can be indexed. |
| Tenant data keys | KMS-wrapped key records | API and worker encryption layer | Makes encrypted fields unreadable or deleted. |
| Queryable analytics | Tenant-scoped graph/activity tables | API, reports, crawlers | Remains usable until workspace data is deleted. |

## Service Components

### App API

Responsibilities:

- Authenticate app users.
- Resolve tenant/workspace context.
- Serve Overview, Doc Audit, graph, document detail, settings, and indexing status APIs.
- Accept review updates and configuration changes.
- Start indexing jobs.

### Indexing Worker

Responsibilities:

- Load encrypted Google credentials for a workspace.
- Crawl Drive, Docs, Slides, and Drive Activity.
- Extract links, external resources, terms, and activity snapshots.
- Write graph data and findings into tenant-scoped tables.
- Record job progress, failures, quotas, and completion metadata.

The worker should be idempotent. A retry should not duplicate documents, links, snapshots, or findings.

### Scheduler

Responsibilities:

- Trigger crawl planning for active workspaces based on tenant-level schedule configuration.
- Stagger jobs to avoid API quota spikes.
- Skip disabled, disconnected, or failing workspaces after configured thresholds.

### Crawl Planner

Responsibilities:

- Decide which crawl type a workspace needs: initial, incremental, activity refresh, link expansion, or backfill.
- Enqueue crawl jobs with priority, scheduled time, and retry policy.
- Respect tenant-level limits and Google API quota budgets.
- Read tenant cron-style cadence, timezone, quiet hours, and workspace overrides.
- Prefer change-based incremental crawls over full reindexing.
- Avoid overlapping crawls for the same workspace unless explicitly allowed.
- Record next scheduled crawl and action-required states.

The planner can start as part of the API service or scheduler target. If crawl volume grows, move it into its own small Cloud Run service.

## Crawling Lifecycle

The hosted service should move from command-driven indexing to durable, recurring crawl jobs.

### Initial Crawl

Runs immediately after a workspace connects Google Drive and chooses an allowed scope. It should index enough recent Docs and Slides to produce first-session findings, then enqueue slower expansion/backfill work as needed.

### Incremental Crawl

Runs daily by default, or on the tenant's configured cron-style schedule. It should fetch documents modified since the last successful crawl, refresh links and terms for changed files, and regenerate findings and digest inputs.

Incremental crawling is the normal operating mode. It should avoid reindexing unchanged documents except when required to repair data, backfill missing context, or respond to explicit admin action.

### Activity Refresh

Runs daily or several times per week depending on quota. Drive Activity can change even when document content does not, so activity windows should be refreshed independently from document body/link extraction.

### Link Expansion Crawl

Runs after initial and incremental crawls discover new internal Drive links. It follows links only inside the selected Shared Drive or allowed folder boundary.

### Backfill Crawl

Runs weekly or opportunistically. It fills in older documents and long-tail graph context without delaying fresh findings.

### Manual Re-Index

Remains available to admins as an override. It should enqueue a normal durable job and show progress, not run inside the web request.

## Crawl State

Add persistent state so the service can explain freshness and recover from failures:

| Field | Purpose |
|---|---|
| `last_successful_crawl_at` | Freshness marker used by the UI and scheduler. |
| `last_attempted_crawl_at` | Helps diagnose repeated failures. |
| `next_scheduled_crawl_at` | Lets admins see that the service is alive. |
| `crawl_cursor` | Stores API pagination/change tokens when available. |
| `schedule_cron` | Tenant or workspace cron-style schedule for recurring crawls. |
| `schedule_timezone` | Timezone used to interpret the cron schedule. |
| `quiet_hours` | Optional window when routine crawls should not start. |
| `incremental_since` | Timestamp or cursor used to limit scheduled crawls to changed documents. |
| `crawl_mode` | `initial`, `incremental`, `activity_refresh`, `link_expansion`, `backfill`, or `manual`. |
| `crawl_health` | `healthy`, `degraded`, `paused`, or `action_required`. |
| `failure_reason` | Human-readable current blocker when degraded or paused. |

## Crawl Job Rules

- Never run two normal crawls for the same workspace at once.
- Make crawls idempotent so retries do not duplicate graph rows.
- Scheduled crawls should query for changed documents first and skip unchanged content extraction.
- Full reindexing should require explicit admin action or a repair/backfill reason recorded on the job.
- Track per-file errors without failing the whole crawl when possible.
- Use exponential backoff for transient Google API failures.
- Keep previous successful graph data available when a crawl fails.
- Regenerate findings only after graph writes for a crawl phase commit successfully.

## Tenant Model

Minimum app-level entities:

| Entity | Purpose |
|---|---|
| `users` | A person who can log into Liminal. |
| `tenants` | A customer organization or beta team. |
| `memberships` | User role within a tenant. |
| `workspaces` | Indexed Drive scope, such as a Shared Drive or folder root. |
| `google_connections` | OAuth tokens, granted scopes, account metadata, and connection health. |
| `indexing_jobs` | Queue state, progress, errors, and run summary. |
| `crawl_schedules` | Cron-style cadence, timezone, next run time, crawl health, pause state, and per-workspace overrides. |

Minimum graph entities should mirror the existing local schema with `tenant_id` and `workspace_id` added to every customer-owned table:

- `documents`
- `persons`
- `external_resources`
- `doc_links`
- `external_links`
- `activity_snapshots`
- `person_activity`
- `doc_terms`
- `doc_alignment`
- `findings`
- `finding_review_events`
- `briefs`

Classify columns by sensitivity before migration. Sensitive text and identity fields can use application-level encryption, while graph keys and aggregate metrics stay queryable.

## Request Isolation Rule

Every API route that reads or writes customer data must derive `tenant_id` from the authenticated session and membership. The client should never be trusted to provide tenant identity by itself.

Workspace IDs may be accepted from the client only after verifying membership in the owning tenant.

## Migration From Local Prototype

### Step 1 - Abstract Storage Context

Replace the current context variable that selects a SQLite database path with a storage context that includes:

- `tenant_id`
- `workspace_id`
- database connection/session
- graph storage adapter

### Step 2 - Add Repository Layer Where Needed

The current API and analytics code reaches directly into SQLite. For the beta, add thin repository functions around the tables most affected by tenancy:

- documents
- links
- snapshots
- findings
- briefs
- jobs

This can be incremental. Avoid a large rewrite before the hosted deployment proves the model.

### Step 3 - Convert Background Thread Jobs

Replace in-process indexing threads with persistent jobs:

- API creates an `indexing_jobs` row.
- API enqueues a Cloud Task or Pub/Sub message.
- Worker claims the job and writes progress.
- UI polls job status from the database.

After this works, add `crawl_schedules` so Cloud Scheduler can trigger recurring crawl planning without manual starts.

### Step 4 - Add Web OAuth

Replace local `InstalledAppFlow` with hosted OAuth:

- `/auth/google/start`
- `/auth/google/callback`
- encrypted token persistence
- token refresh handling
- disconnect and delete

### Step 5 - Deploy Single-Tenant, Then Multi-Tenant

The fastest beta path may be one Cloud Run deployment and one database namespace for the first pilot. Multi-tenant service hardening should follow once the first hosted pilot proves that onboarding, indexing, and review workflows land.

## Open Architecture Decisions

- Use Cloud Tasks or Pub/Sub for indexing dispatch?
- Should Cloud Scheduler trigger one global planner or per-workspace scheduled jobs?
- How much cron flexibility should beta admins get versus simple presets like daily, weekdays, or weekly?
- Store graph tables in PostgreSQL only, or split activity snapshots to BigQuery early?
- Should document body text ever be stored, or should the service store only extracted links, terms, and metadata?
- Which fields should use application-level tenant encryption versus standard Cloud SQL encryption at rest?
- Should enterprise customers eventually get customer-managed encryption keys?
- Should person-level activity be retained, anonymized, or made configurable per tenant?
- Should the app use Google Identity for app login, or support email magic links/invitations separately from Drive OAuth?
