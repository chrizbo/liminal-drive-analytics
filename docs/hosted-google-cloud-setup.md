# Hosted Google Cloud Setup

This records the Google Cloud state for the hosted Liminal service so future
work uses the same project and service boundaries.

## Project

- Account: `chrizbo@gmail.com`
- Project ID: `liminal-drive-analytics`
- Project number: `793753803919`
- Default region: `us-central1`
- Billing account: `Liminal Practice` (`016BAC-ED371D-71192C`)

The project was created on 2026-08-15 for the hosted Liminal service. Keep
hosted runtime resources in this dedicated project instead of the generated
`gen-lang-client-0754444896` project or another sandbox project.

Local Cloud SDK defaults:

```bash
gcloud config set project liminal-drive-analytics
gcloud config set run/region us-central1
```

## Current Setup State

Created:

- Google Cloud project `liminal-drive-analytics`
- Artifact Registry Docker repository:
  - `us-central1-docker.pkg.dev/liminal-drive-analytics/liminal`
- KMS keyring and key:
  - keyring: `projects/liminal-drive-analytics/locations/us-central1/keyRings/liminal`
  - key: `projects/liminal-drive-analytics/locations/us-central1/keyRings/liminal/cryptoKeys/credential-encryption`
  - rotation: 90 days
- Cloud Tasks queue:
  - `projects/liminal-drive-analytics/locations/us-central1/queues/liminal-crawl`
- Cloud SQL PostgreSQL instance:
  - instance: `liminal-postgres`
  - connection name: `liminal-drive-analytics:us-central1:liminal-postgres`
  - database version: PostgreSQL 16
  - edition/tier: Enterprise `db-f1-micro`
  - zone: `us-central1-a`
  - storage: 10 GB SSD, auto-resize enabled
  - backups: enabled, 09:00 UTC start, 7 retained backups
  - deletion protection: enabled
  - app database: `liminal`
  - app user: `liminal_app`
- Secret Manager secrets:
  - `liminal-db-password`
  - `liminal-database-url`
  - `liminal-app-session-secret`
  - `liminal-write-token`
  - `liminal-google-oauth-client-config`
- Cloud Run service:
  - service: `liminal-api`
  - URL: `https://liminal-api-bkcwct2l6a-uc.a.run.app`
  - alternate URL: `https://liminal-api-793753803919.us-central1.run.app`
  - image: tagged per deploy by short commit hash, e.g.
    `us-central1-docker.pkg.dev/liminal-drive-analytics/liminal/api:fb9b91b`
    (see `git log` for what each tag corresponds to)
  - revision: `liminal-api-00031-md7` (as of 2026-09-23; redeploys create a new
    `liminal-api-<n>-<suffix>` revision each time — check
    `gcloud run services describe liminal-api --region us-central1` for the
    current one rather than trusting this file)
  - access: **public** (`allUsers` has `roles/run.invoker`) — opened
    2026-09-22 so the browser-redirect OAuth callback could reach the
    service; see "Access Model" below before changing this back
  - CPU allocation: **always allocated**
    (`run.googleapis.com/cpu-throttling=false`, set 2026-09-23) — required
    for the background indexing thread to get CPU outside of an in-flight
    request; see "Incident: background indexing hung the whole service"
  - maxScale: 2, minScale: unset (still scales to zero when idle)
  - resources: 1 vCPU, 512Mi memory
  - service account: `liminal-api@liminal-drive-analytics.iam.gserviceaccount.com`
  - Cloud SQL connection: `liminal-drive-analytics:us-central1:liminal-postgres`
- Runtime service accounts:
  - `liminal-api@liminal-drive-analytics.iam.gserviceaccount.com`
  - `liminal-worker@liminal-drive-analytics.iam.gserviceaccount.com`
  - `liminal-scheduler@liminal-drive-analytics.iam.gserviceaccount.com`
  - `liminal-deployer@liminal-drive-analytics.iam.gserviceaccount.com`

Enabled hosted-service APIs:

- Cloud Run API: `run.googleapis.com`
- Cloud Build API: `cloudbuild.googleapis.com`
- Artifact Registry API: `artifactregistry.googleapis.com`
- Cloud SQL Admin API: `sqladmin.googleapis.com`
- Secret Manager API: `secretmanager.googleapis.com`
- Cloud KMS API: `cloudkms.googleapis.com`
- Cloud Scheduler API: `cloudscheduler.googleapis.com`
- Cloud Tasks API: `cloudtasks.googleapis.com`
- Cloud Logging API: `logging.googleapis.com`
- Error Reporting API: `clouderrorreporting.googleapis.com`

Enabled Workspace APIs:

- Google Drive API: `drive.googleapis.com`
- Google Docs API: `docs.googleapis.com`
- Google Slides API: `slides.googleapis.com`
- Drive Activity API: `driveactivity.googleapis.com`
- People API: `people.googleapis.com`

## IAM State

Granted:

- `liminal-api`: `roles/cloudsql.client`
- `liminal-worker`: `roles/cloudsql.client`
- `liminal-api`: `roles/secretmanager.secretAccessor`
- `liminal-worker`: `roles/secretmanager.secretAccessor`
- `liminal-api`: `roles/cloudkms.cryptoKeyEncrypterDecrypter` on `credential-encryption`
- `liminal-worker`: `roles/cloudkms.cryptoKeyEncrypterDecrypter` on `credential-encryption`
- `liminal-scheduler`: `roles/cloudtasks.enqueuer`
- `chrizbo@gmail.com`: `roles/run.invoker` on the `liminal-api` Cloud Run service
- `chrizbo@gmail.com`: `roles/iam.serviceAccountTokenCreator` on `liminal-api` for private smoke tests
- `liminal-api`: `roles/run.invoker` on the `liminal-api` Cloud Run service for service-account-token smoke tests
- `allUsers`: `roles/run.invoker` on the `liminal-api` Cloud Run service (added
  2026-09-22 — see "Access Model" below)

Do not grant broad deployer roles until the deployment path is defined.

## Access Model

The service was originally deployed **private** (only `chrizbo@gmail.com` and
the service's own service account could invoke it). It was made **public**
during hosted-OAuth testing because Google's redirect back to
`/google-connection/oauth/callback` is a plain, unauthenticated browser
navigation — it cannot carry a bearer token, so a private Cloud Run service
rejects it before the app code ever runs. Cloud Run has no per-path IAM, so
"let the OAuth callback through" means "let everything through" at the
infrastructure layer.

This is safe for now because every mutating endpoint is still gated by
`X-Admin-Token` (`DRIVE_ANALYTICS_WRITE_TOKEN`) at the application layer —
making the service public only exposed read endpoints and the callback, not
write access. Revisit before inviting anyone beyond `chrizbo@gmail.com`:
either move to the real invite/access-control flow (see
`specs/pre-build-checklist.md`), or front the service with a load balancer
that can route `/google-connection/oauth/callback` through unauthenticated
while keeping everything else IAM-gated.

## Container Packaging

The repo includes a `Dockerfile` for the FastAPI/static web service. It starts:

```bash
uvicorn src.api:app --host 0.0.0.0 --port ${PORT}
```

`/health` is a liveness check only — it must never depend on Postgres (see
the incident below for why), so it always returns `{"ok": true}` regardless
of database state. `/configuration` reports service mode, e.g.:

```json
{"write_token_required": true, "database_backend": "postgresql"}
```

`POST /google-connection/oauth/start` reaches the app and returns a Google
authorization URL for client
`793753803919-iqf8b03592tqsn7sm7d5c3fjgldvcskm.apps.googleusercontent.com`
with callback
`https://liminal-api-bkcwct2l6a-uc.a.run.app/google-connection/oauth/callback`.
The full connect flow (start → Google consent → callback → stored, encrypted
credential) is confirmed working end-to-end as of 2026-09-22.

## Deploy Process

Runtime env vars are already wired on the service (`DRIVE_ANALYTICS_DATABASE_URL`,
`DRIVE_ANALYTICS_WRITE_TOKEN`, `DRIVE_ANALYTICS_APP_SESSION_SECRET`,
`DRIVE_ANALYTICS_BASE_URL`, `DRIVE_ANALYTICS_KMS_KEY_NAME`,
`DRIVE_ANALYTICS_GOOGLE_OAUTH_CLIENT_CONFIG`), the Cloud SQL connection, and the
`liminal-api` service account — a normal deploy doesn't need to repeat any of
that. The established pattern for shipping a change:

```bash
git commit -m "..."                      # tag the image by commit hash
gcloud builds submit --project liminal-drive-analytics \
  --tag us-central1-docker.pkg.dev/liminal-drive-analytics/liminal/api:$(git rev-parse --short HEAD) .
gcloud run deploy liminal-api --project liminal-drive-analytics \
  --region us-central1 \
  --image us-central1-docker.pkg.dev/liminal-drive-analytics/liminal/api:$(git rev-parse --short HEAD)
```

`gcloud run deploy --image` without other flags preserves the existing
service configuration (env vars, secrets, Cloud SQL connection, CPU
allocation, IAM) — it only swaps the container image. Verify after every
deploy with `curl .../health` and `curl .../google-connection?workspace=live`
to confirm the existing Drive connection survived.

## Hosted OAuth

The API includes:

- `POST /google-connection/oauth/start`
- `GET /google-connection/oauth/callback`

The start endpoint returns a Google authorization URL with signed stateless
OAuth state. The callback exchanges the code, verifies state, encrypts the
credential JSON with KMS, and stores it in `google_connections`. Confirmed
working end-to-end (real consent screen, real stored credential) as of
2026-09-22, after fixing two bugs:

- **PKCE mismatch** — `/oauth/start` and `/oauth/callback` build separate
  `Flow` objects (the API is stateless across requests). `google-auth-oauthlib`
  auto-generates a PKCE verifier when building the authorization URL, but that
  verifier only lives on the `Flow` instance that created it, so the
  callback's fresh `Flow` had nothing to send back and Google rejected the
  token exchange with `invalid_grant: Missing code verifier`. Fixed by
  disabling `autogenerate_code_verifier` in `auth.build_web_oauth_flow` —
  this is a confidential "web" client that already sends `client_secret`
  during token exchange, so PKCE was redundant here rather than something to
  thread through the state token.
- **Google account not a test user** — while the OAuth consent screen is in
  "Testing" publishing status, only explicitly-added test users can complete
  consent, including the project owner. Add testers at
  `console.cloud.google.com/apis/credentials/consent?project=liminal-drive-analytics`.

The Google connection is **tenant-wide, not per-workspace**: connecting once
(from any workspace) makes every workspace under that tenant — Live Drive and
any Shared Drive workspaces added later — usable immediately, with no
separate OAuth round-trip per workspace. Rows are always stored under a fixed
sentinel `workspace_id` of `"live"` regardless of which workspace initiated
the connect (see `_tenant_connection_scope` in `src/api.py`), which happens to
match the AAD already used for the first connection, so this required no
migration or reconnect.

Hosted OAuth client state:

- Web client ID:
  `793753803919-iqf8b03592tqsn7sm7d5c3fjgldvcskm.apps.googleusercontent.com`
- Authorized redirect URI:
  `https://liminal-api-bkcwct2l6a-uc.a.run.app/google-connection/oauth/callback`
- Secret Manager secret: `liminal-google-oauth-client-config`
- Secret version 1 contained an older desktop client and is disabled.
- Secret version 2 contains the correct hosted web client.
- `chrizbo@gmail.com` is added as a test user on the consent screen.

Secret hygiene note: `liminal-write-token` version 2 was rotated without a
trailing newline so it can be used reliably in `X-Admin-Token` headers.

## Shared Drive Workspaces

A tenant can add a Shared Drive as its own bounded workspace (`POST
/workspaces/shared-drive`, resolved via `GET
/workspaces/shared-drive/candidates` which lists Shared Drives the tenant's
connected account can see and hasn't already added). Each becomes a
`kind='shared'` row in the hosted `workspaces` table with its own indexed
data, crawl schedule, and job history — isolated from other workspaces so
terminology-drift and hub/stale detection stay meaningful within one team's
graph instead of being diluted across unrelated teams. Workspaces added this
way can be renamed or deleted entirely (`PATCH`/`DELETE /workspace`); Live
Drive and the demo workspace can't, since they're hardcoded entries in
`available_workspaces()` rather than rows.

Deliberately not built: indexing "everything the account can see" in one
pool. Researched 2026-09-22 how larger orgs would connect at scale — see
`specs/future-considerations.md` for the comparison (per-user OAuth vs. a
per-tenant service account added to specific Shared Drives vs. domain-wide
delegation) and which to prefer later.

## Incident: background indexing hung the whole service (2026-09-23)

**Symptom:** a Shared Drive re-index appeared stuck mid-progress, then the
entire app stopped responding — including `/health`, and including on a
brand-new Cloud Run instance that had never served a request before.

**Root cause, in order of discovery:**

1. `index_file()` committed once per file, after both link extraction and the
   activity fetch. An unrelated SQL bug (`increment_person_activity`'s
   `ON CONFLICT DO UPDATE SET count=count+1` is ambiguous in Postgres —
   `excluded` also has a `count` column, and SQLite tolerates the bare
   reference where Postgres doesn't) aborted the transaction inside the
   activity-fetch's `except Exception: print(warning)`, which never rolled
   back. The next `conn.commit()` on an aborted transaction is treated by
   Postgres as a rollback — silently discarding that file's already-inserted
   document row, for every file in the run. **Fixed**: commit the document
   and its links immediately, before the activity fetch runs; roll back (not
   just log) on activity-fetch failure.
2. A Google People API call inside the same background thread hung with no
   timeout (`people_svc.people().getBatchGet(...).execute()`), holding a
   Postgres connection open indefinitely. **Fixed**: `auth.build_services()`
   now uses an `AuthorizedHttp` with a 30s socket timeout on every Google API
   client.
3. `db-f1-micro`'s connection budget is tiny, and the `select_workspace`
   middleware queried Postgres (to list hosted Shared Drive workspaces) on
   *every* request, including `/health` — so once the pool was exhausted by
   (2), even a fresh instance's first health check hung, and Cloud Run had no
   working liveness signal to cycle the bad instance. **Fixed**: `/health`
   now bypasses the middleware entirely; it must never depend on the
   database.
4. Root architecture issue: Cloud Run's default CPU allocation is
   **request-scoped** — a container is only guaranteed CPU while actively
   handling an HTTP request. This app spawns the actual crawl as a
   `threading.Thread` that keeps running *after* the triggering
   `POST /indexing/jobs` request already returned. With CPU throttled, that
   background thread (and everything else in the process, including
   unrelated requests) can stall unpredictably whenever no request happens to
   be in flight. This is why point-fixing (1)-(3) still weren't enough — the
   service hung a second and third time after each was deployed.
   **Fixed**: enabled `run.googleapis.com/cpu-throttling=false` ("CPU always
   allocated") — the documented Cloud Run remediation for background work
   outside request scope. Cost impact is small at this scale (~$0.09/hour
   while an instance is warm; the service still scales to zero when idle
   since `minScale` is unset) — real numbers are worth re-checking against
   current Cloud Run pricing if usage grows.

**Recovery steps used during the incident** (for next time): force a fresh
Cloud Run revision (`gcloud run deploy` with the current image restarts
instances and clears a stuck one); if `/health` itself won't respond even on
a brand-new instance, the Postgres connection pool is likely exhausted —
`gcloud sql instances restart liminal-postgres` force-closes every open
connection cluster-wide. Both are disruptive to a shared resource; confirm
with the account owner before running either (the auto-mode safety layer
blocks the Cloud SQL restart specifically, and correctly so).

**Also fixed while investigating**: `stamp_workspace_rows()` — a broad
`UPDATE` across every customer table meant only to backfill legacy
pre-multi-tenant local SQLite rows — was running on every hosted request too
(same middleware path), and concurrent transactions racing that write caused
a separate `psycopg.errors.DeadlockDetected` failure before this incident.
It now only runs for local SQLite, never hosted Postgres.
