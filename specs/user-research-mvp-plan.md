# User Research MVP Plan

## Goal

Build the minimum hosted version of Liminal that can be shown in user research and early customer conversations with real or demo Workspace data.

The goal is not to prove every service capability. The goal is to prove that people understand the concept, trust the signals, and want to return to the Doc Audit and digest after seeing their Drive knowledge graph.

## Confirmed Direction

- Start with user OAuth and selected Shared Drives or bounded folder roots.
- Support multi-tenant structure from the beginning so multiple people or teams can try it.
- Use Cloud SQL/PostgreSQL for the first hosted database.
- Use daily incremental crawling as the default freshness target.
- Store metadata, extracted links, external URLs, term frequencies, activity aggregates, findings, and review state.
- Do not store full document body text for the research MVP.
- Show person-level data primarily as aggregates.
- Distinguish document owners/creators from other contributors because ownership is part of the document-health signal.
- Keep the beta boundary tight: no landing page, billing, Slack integration, cross-system indexing, or broad self-serve launch.

## Phase 0 - Research Demo Baseline

Purpose: make the current app easy to demo consistently before changing the architecture.

Done when:

- Demo data can be reset and shown reliably.
- The Overview, Doc Audit, detail drawer, and graph tell a coherent story.
- The demo can explain the product without requiring a live customer connection.
- The limitations are clear: local auth, local storage, manual setup, and prototype-only trust model.

Useful for:

- Concept validation.
- Language testing.
- Understanding which findings people care about.
- Recruiting friendly beta users.

## Phase 1 - Hosted Research Instance

Purpose: show the product as a service while keeping scope narrow.

Done when:

- FastAPI and the static app run on Cloud Run.
- PostgreSQL-backed app storage exists.
- The app has tenant, user, membership, and workspace concepts.
- User OAuth works for Google Drive access.
- Credentials are encrypted and stored per tenant/workspace.
- A user can select one Shared Drive or bounded folder root.
- An initial crawl runs as a durable background job.
- The UI shows indexing progress and final crawl freshness.

Minimum research experience:

1. Sign in.
2. Connect Google Drive.
3. Pick a Drive scope.
4. Run first crawl.
5. See Overview, Doc Audit, and graph.

## Phase 2 - Multi-Tenant Research Beta

Purpose: let several people or teams try Liminal without separate deployments.

Done when:

- Multiple tenants can exist in the same deployment.
- Every customer-owned table is tenant-scoped.
- Workspaces are isolated by `tenant_id` and `workspace_id`.
- Tenant-scoped encryption is in place for credentials and sensitive fields.
- Cross-tenant access tests exist.
- Admins can pause crawling, disconnect Drive, and delete workspace data.

Important note: encryption helps reduce blast radius, but it does not replace tenant isolation. Multi-tenancy depends on authenticated membership checks, tenant-scoped queries, storage boundaries, tests, and operational discipline.

## Phase 3 - Recurring Freshness

Purpose: make Liminal feel alive without manual runs.

Done when:

- Daily incremental crawls run by default.
- Tenant crawl schedules can be configured with simple presets or cron-style schedule plus timezone.
- Scheduled crawls focus on changed documents and recent activity rather than full reindexing.
- Backfill and link expansion run separately from the freshness path.
- The UI shows last successful crawl, next scheduled crawl, crawl health, and partial/failure states.

Research question:

- Does fresh recurring analysis make people come back, or is one-time insight enough?

## Phase 4 - Research Instrumentation

Purpose: learn whether the flagged documents actually drive useful behavior.

Done when:

- The app tracks in-product engagement with findings: opened, reviewed, assigned, dismissed, completed, followed up.
- The app tracks outbound clicks from a finding to a Google Doc.
- The app can compare flagged-document activity before and after a finding is surfaced using Drive Activity aggregates.
- The app can report whether flagged docs were edited, commented on, or linked more after review.
- Analytics are tenant-scoped and aggregated by default.

Do not overbuild this into a general analytics platform yet. The first research question is whether Liminal causes useful follow-up on the documents it flags.

## Person and Ownership Model

For the research MVP, avoid making individual activity the center of the product.

Show:

- Document owner or creator when Google provides it.
- Whether a doc appears single-owner, team-maintained, or orphaned.
- Aggregate contributor count.
- Aggregate recent activity by type: views, edits, comments.
- High-level contributor freshness, such as last contributor activity date.

Avoid by default:

- Ranking individual viewers.
- Showing detailed per-person view histories.
- Treating employee activity as performance monitoring.

Ownership should be a document-health signal. Non-owner activity should usually be aggregated unless a tenant explicitly enables more detail.

## Research Success Criteria

- Participants understand the product within a short demo.
- Participants can name at least one real workflow where they would use it.
- Participants trust why a document was flagged.
- Participants click through from a finding to inspect the source document.
- Participants take or describe a concrete follow-up action.
- At least one reviewer returns to the Doc Audit or digest without being prompted.
- Flagged documents show downstream engagement: opened from Liminal, reviewed, edited, commented on, assigned, dismissed with reason, or resolved.

## Build Order

1. Add tenant/user/workspace model.
2. Move local storage toward PostgreSQL-compatible repositories.
3. Add web OAuth and encrypted credential storage.
4. Add durable crawl jobs.
5. Add selected Drive scope onboarding.
6. Add multi-tenant route guards and tests.
7. Add scheduled incremental crawling.
8. Add research instrumentation for finding engagement.
9. Add deletion/disconnect flows.

## Deferred From Research MVP

- Public landing page.
- Billing.
- Self-serve public signup.
- Slack or email digest automation.
- Domain-wide delegation.
- Cross-system indexing.
- Customer-managed encryption keys.
- Enterprise compliance package.
- Broad product analytics across tenants.
