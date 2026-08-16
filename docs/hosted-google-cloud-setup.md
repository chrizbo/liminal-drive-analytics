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
- Cloud Run service:
  - service: `liminal-api`
  - URL: `https://liminal-api-bkcwct2l6a-uc.a.run.app`
  - alternate URL: `https://liminal-api-793753803919.us-central1.run.app`
  - image: `us-central1-docker.pkg.dev/liminal-drive-analytics/liminal/api:bd0fa13`
  - digest: `sha256:bf2f416dd19f404eb10888c597c996b1a797affcdbe2b1fbf0909525deb6839a`
  - revision: `liminal-api-00003-zfq`
  - access: private; `chrizbo@gmail.com` has `roles/run.invoker`
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
- `chrizbo@gmail.com`: `roles/run.invoker` on the private `liminal-api` Cloud Run service

Do not grant broad deployer roles until the deployment path is defined.

## Container Packaging

The repo includes a `Dockerfile` for the FastAPI/static web service. It starts:

```bash
uvicorn src.api:app --host 0.0.0.0 --port ${PORT}
```

Use `/health` for a lightweight runtime smoke check in Cloud Run. `/healthz`
is also available for local/container tests, but the Cloud Run authenticated
proxy returned a Google front-end 404 for that exact path during setup.
The private Cloud Run smoke test uses the authenticated local proxy. The
`bd0fa13` deployment confirmed `/health` returns `{"ok": true}` and
`/configuration` returns:

```json
{"write_token_required": true, "database_backend": "postgresql"}
```

## Next Cloud Commands

The first private Cloud Run service is deployed. Future deploys should build a
new immutable image tag and redeploy `liminal-api`, wiring:

- `DRIVE_ANALYTICS_DATABASE_URL` from `liminal-database-url`
- `DRIVE_ANALYTICS_WRITE_TOKEN` from `liminal-write-token`
- `--add-cloudsql-instances=liminal-drive-analytics:us-central1:liminal-postgres`
- `--service-account=liminal-api@liminal-drive-analytics.iam.gserviceaccount.com`

Keep the first Cloud Run service private until hosted OAuth and invite flow are
implemented.
