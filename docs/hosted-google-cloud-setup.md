# Hosted Google Cloud Setup

This records the Google Cloud state for the hosted Liminal service so future
work uses the same project and service boundaries.

## Project

- Account: `chrizbo@gmail.com`
- Project ID: `liminal-drive-analytics`
- Project number: `793753803919`
- Default region: `us-central1`
- Intended billing account: `Liminal Practice` (`01C4CB-8173D0-6B2CD2`)

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
- Runtime service accounts:
  - `liminal-api@liminal-drive-analytics.iam.gserviceaccount.com`
  - `liminal-worker@liminal-drive-analytics.iam.gserviceaccount.com`
  - `liminal-scheduler@liminal-drive-analytics.iam.gserviceaccount.com`
  - `liminal-deployer@liminal-drive-analytics.iam.gserviceaccount.com`

Enabled Workspace APIs:

- Google Drive API: `drive.googleapis.com`
- Google Docs API: `docs.googleapis.com`
- Google Slides API: `slides.googleapis.com`
- Drive Activity API: `driveactivity.googleapis.com`
- People API: `people.googleapis.com`

## Billing Blocker

Attaching the project to the intended `Liminal Practice` billing account failed
with a billing quota error:

```text
Cloud billing quota exceeded: billingAccounts/01C4CB-8173D0-6B2CD2
```

Until billing is attached, Google will not enable the paid service stack for:

- Cloud Run
- Cloud Build
- Artifact Registry
- Cloud SQL Admin
- Secret Manager
- Cloud KMS
- Cloud Scheduler
- Cloud Tasks

Next options:

- Request a billing quota increase for `Liminal Practice`.
- Attach `liminal-drive-analytics` to another open billing account after an
  explicit owner decision.

## Next Cloud Commands

After billing is attached, enable the remaining service APIs:

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  cloudkms.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudtasks.googleapis.com \
  logging.googleapis.com \
  clouderrorreporting.googleapis.com \
  --project=liminal-drive-analytics
```

Then create the first deployment targets:

```bash
gcloud artifacts repositories create liminal \
  --repository-format=docker \
  --location=us-central1 \
  --description="Liminal service images" \
  --project=liminal-drive-analytics
```

Create Cloud SQL only after confirming the billing account, size, and deletion
protection setting, because it creates ongoing paid capacity.
