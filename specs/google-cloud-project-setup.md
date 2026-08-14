# Google Cloud Project Setup

## Principle

The hosted Liminal service should run in its own Google Cloud project, even if it uses an existing Google Cloud account, billing account, or organization.

Keeping Liminal in a separate project gives cleaner boundaries for billing, IAM, OAuth consent, quotas, secrets, logs, deletion, and future handoff. It also reduces the chance that service infrastructure gets tangled with unrelated projects.

## Project Shape

Recommended initial project:

- Project name: `liminal-drive-analytics`
- Project purpose: hosted Liminal service for user research, private trials, and future production use
- Billing: attach to the existing billing account
- Region: choose one primary region for Cloud Run, Cloud SQL, KMS, and storage
- Environment: start with one service project; add separate staging/production projects later if needed

Future project split:

- `liminal-drive-analytics-staging`
- `liminal-drive-analytics-prod`

Do not put customer or research data in a general-purpose sandbox project.

## Setup Steps

### 1. Create Project

Create a new Google Cloud project under the existing account or organization.

Record:

- Project ID.
- Project number.
- Billing account.
- Default region.
- Owner/admin accounts.

### 2. Enable Required APIs

Enable service infrastructure APIs:

- Cloud Run API.
- Cloud Build API.
- Artifact Registry API.
- Cloud SQL Admin API.
- Secret Manager API.
- Cloud KMS API.
- Cloud Scheduler API.
- Cloud Tasks API or Pub/Sub API.
- Cloud Logging/Error Reporting APIs as needed.

Enable Google Workspace data APIs for the OAuth client:

- Google Drive API.
- Google Docs API.
- Google Slides API.
- Drive Activity API.
- People API only if actor identity resolution remains in scope.

Before building hosted OAuth, re-check whether `contacts.readonly`/People API is needed for the research MVP.

### 3. Configure IAM

Create separate service accounts instead of using broad default credentials:

| Service Account | Purpose |
|---|---|
| `liminal-api` | Runs the Cloud Run API/web service. |
| `liminal-worker` | Runs crawl/indexing jobs. |
| `liminal-scheduler` | Triggers crawl planning or job enqueueing. |
| `liminal-deployer` | Used by deployment automation if needed. |

Grant least-privilege roles:

- API service can read needed secrets, connect to Cloud SQL, and use KMS decrypt for permitted keys.
- Worker can read encrypted Google credentials, use KMS decrypt, connect to Cloud SQL, and write crawl/job data.
- Scheduler can invoke the API/planner or enqueue tasks.
- Avoid project-wide owner/editor roles for runtime services.

### 4. Create Secrets and Keys

Use Secret Manager for:

- App session secret.
- OAuth client secret.
- Database password or connection secret if not using IAM auth.
- Any deployment-only secrets.

Use Cloud KMS for:

- Credential encryption.
- Tenant data key wrapping.
- Future key rotation and tenant deletion semantics.

Decide whether the initial service uses one KMS key for all tenants with tenant-wrapped data keys, or separate KMS keys per tenant later. For the research MVP, one KMS key plus tenant data keys is likely enough.

### 5. Create Database

Create Cloud SQL for PostgreSQL in the selected region.

Initial requirements:

- Private or tightly controlled connectivity from Cloud Run.
- Automated backups enabled.
- Deletion protection considered before inviting external users.
- Migration process documented.
- Separate database/schema for app data if needed.

Do not manually create production-only schema in the console without capturing the migration in code.

### 6. Configure OAuth Consent

Create/configure the OAuth consent screen in this project.

For research/private beta:

- Use accurate app name and support contact.
- Keep the app in testing mode while possible.
- Add test users for early research participants.
- Configure redirect URIs for hosted environments.
- Prepare scope justifications before expanding beyond test users.

The OAuth project should match the service project unless there is a strong reason to separate them later.

### 7. Prepare Deployment Targets

Create or configure:

- Artifact Registry repository for the app image.
- Cloud Run service for API/web.
- Cloud Run job or worker service for crawling.
- Cloud Scheduler job for crawl planning.
- Cloud Tasks queue or Pub/Sub topic for durable work dispatch.

### 8. Configure Observability

Set up:

- Structured logging.
- Error reporting.
- Alerts for failed crawls, repeated OAuth failures, and database connectivity issues.
- Log retention appropriate for research/private trial usage.

Logs must not include OAuth tokens, full document contents, large excerpts, or private URLs unless explicitly scrubbed.

## Local Configuration To Track

Add project-specific configuration to a non-secret config file or deployment documentation:

- `GOOGLE_CLOUD_PROJECT`
- primary region
- Cloud Run service name
- Cloud SQL instance name
- KMS key name
- Secret Manager secret names
- OAuth redirect URI
- task queue/topic names

Secrets themselves should never be committed.

## Pre-Build Decision

Before hosted work starts, choose:

- Project ID.
- Primary region.
- Whether research trials and production share one project initially.
- Whether deployment is manual first or automated through CI.
- Whether Cloud Tasks or Pub/Sub is the first durable-job mechanism.
