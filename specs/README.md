# Service Planning Specs

This folder tracks the path from local prototype to hosted service. The initial focus is a private beta for Google Workspace teams using Google Cloud.

## Current Direction

- Start with Workspace teams, not a broad public consumer launch.
- Use Google Cloud first because the project already depends on Google APIs and the owner already has a Google Cloud account.
- Keep the product app-focused. No public service landing page yet.
- Run the hosted service in its own Google Cloud project attached to the existing account/billing setup.
- Preserve the core promise: read-only Drive insight that surfaces knowledge health, rising documents, stale hubs, terminology drift, and documents needing review.

## Specs

- [User Research MVP Plan](user-research-mvp-plan.md) - minimum phased build for early demos, research, and friendly trials.
- [Pre-Build Checklist](pre-build-checklist.md) - final decisions, first implementation slices, research questions, and technical risks.
- [Private Beta Plan](private-beta-plan.md) - product scope, milestones, risks, and beta success criteria.
- [Google Cloud Architecture](google-cloud-architecture.md) - proposed service architecture, data model changes, and migration path from the local app.
- [Google Cloud Project Setup](google-cloud-project-setup.md) - separate cloud project setup, APIs, IAM, secrets, KMS, OAuth, and deployment targets.
- [OAuth and Security Readiness](oauth-security-readiness.md) - consent, verification, token handling, tenant isolation, retention, and trust requirements.
- [Future Considerations](future-considerations.md) - important ideas intentionally deferred from the research MVP.

## Working Assumptions

- The local app remains useful as the prototype and demo environment.
- The hosted service should support multiple customer workspaces from one deployment.
- The first beta customers should connect specific Shared Drives or bounded Drive scopes before any org-wide indexing.
- Admin/domain-wide delegation is a later beta option, not the first onboarding path unless a pilot customer explicitly wants it.
- Person-level activity should be aggregated by default, with document ownership/creation treated as a separate document-health signal.
- Early success should include engagement with flagged documents, not only app usage.
- The product should be useful before adding cross-system indexing for Notion, GitHub, Slack, Confluence, or Jira.
