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

Remaining baseline grants before first hosted deploy:

- `liminal-worker`: `roles/secretmanager.secretAccessor`
- `liminal-api`: KMS decrypt/encrypt on `credential-encryption`
- `liminal-worker`: KMS decrypt/encrypt on `credential-encryption`
- `liminal-scheduler`: task enqueue permission for `liminal-crawl`

Do not grant broad deployer roles until the deployment path is defined.

## Next Cloud Commands

Grant the remaining runtime IAM:

```bash
gcloud projects add-iam-policy-binding liminal-drive-analytics \
  --member=serviceAccount:liminal-worker@liminal-drive-analytics.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor \
  --quiet

gcloud kms keys add-iam-policy-binding credential-encryption \
  --keyring=liminal \
  --location=us-central1 \
  --member=serviceAccount:liminal-api@liminal-drive-analytics.iam.gserviceaccount.com \
  --role=roles/cloudkms.cryptoKeyEncrypterDecrypter \
  --project=liminal-drive-analytics \
  --quiet

gcloud kms keys add-iam-policy-binding credential-encryption \
  --keyring=liminal \
  --location=us-central1 \
  --member=serviceAccount:liminal-worker@liminal-drive-analytics.iam.gserviceaccount.com \
  --role=roles/cloudkms.cryptoKeyEncrypterDecrypter \
  --project=liminal-drive-analytics \
  --quiet
```

Create Cloud SQL only after confirming the billing account, size, and deletion
protection setting, because it creates ongoing paid capacity.
