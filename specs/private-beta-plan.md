# Private Beta Plan

## Goal

Turn Liminal Drive Analytics into a hosted private beta that Google Workspace teams can connect to their Drive, index selected Shared Drives or team-owned document sets, and review knowledge-health findings in the existing app experience.

The beta should prove that teams get recurring value from the Doc Audit, Team Digest, and graph without requiring a consultant-style manual run.

## Non-Goals

- No public marketing site or landing page.
- No self-serve paid signup.
- No broad consumer Gmail launch.
- No write access to Drive.
- No cross-system indexing beyond classifying external links.
- No full enterprise compliance program before the first friendly pilots.
- No full document body storage for the initial beta.

## Target Beta User

The first user should be someone who already feels the cost of messy Drive knowledge:

- Product, operations, TPM, or chief-of-staff style role.
- Works in a Google Workspace organization.
- Has authority to connect one or more Shared Drives, or can get Workspace admin help.
- Wants a weekly pulse and an actionable queue more than a raw analytics dashboard.

## Beta Product Scope

### Must Have

- Hosted app login.
- Google OAuth connection for a user or admin.
- Multi-tenant app structure with isolated tenant/workspace data.
- Select one or more Shared Drives or bounded Drive roots to index.
- Background indexing with visible progress.
- Automatic recurring indexing so the service stays fresh without manual runs.
- Tenant-level crawl configuration for cadence, preferred run time, and pause/resume.
- Overview with Team Digest.
- Doc Audit queue with review state, assignee, notes, and follow-up date.
- Document detail drawer with links, contributors, activity, and suggested action.
- Aggregated person/contributor signals, with owner/creator separated from other contributors.
- Graph view for exploration.
- Re-index on demand and scheduled incremental refresh.
- Disconnect Google account and delete indexed data.

### Should Have

- Invite additional teammates to view the workspace.
- Basic role split: owner/admin, reviewer, viewer.
- Weekly digest email to workspace admins or reviewers.
- Indexing health page showing last successful run, next scheduled run, failures, and quota/rate-limit issues.
- Export findings as CSV for teams that want to work outside the app.

### Later

- Slack digest.
- Domain-wide delegation setup for Workspace admins.
- Granular permission mirroring from Drive.
- Semantic/LLM-enhanced terminology alignment.
- Cross-system indexing.
- Billing.

## Milestones

### Milestone 1 - Hosted Single-Tenant Beta

Done when one friendly Workspace team can use a deployed instance without running code locally.

- Deploy FastAPI and static web app to Cloud Run.
- Move configuration to environment variables and Secret Manager.
- Store the graph in a managed database or tenant-prefixed cloud storage.
- Replace desktop OAuth with web OAuth callback.
- Encrypt and refresh Google tokens server-side.
- Run indexing as a Cloud Run job or background worker.
- Keep a single beta customer per deployment if that is the fastest safe path.

### Milestone 2 - Multi-Tenant Private Beta

Done when several teams can use the same service deployment with isolated data.

- Add tenant, user, membership, and workspace tables.
- Route every API request through authenticated user and tenant context.
- Partition graph data by tenant/workspace.
- Add workspace creation, Drive connection, and Shared Drive selection flows.
- Add scheduled indexing per workspace with retry/backoff and run health tracking.
- Add tenant deletion and Google disconnect flows.

### Milestone 3 - Trust and Operational Readiness

Done when the service is credible for non-friend beta teams.

- Publish privacy policy and terms for beta users.
- Document data collected, retained, derived, and deleted.
- Add structured logs without document contents.
- Add job failure alerts.
- Add backups and restore test.
- Add security review of token storage, CORS, auth, and tenant isolation.
- Prepare Google OAuth verification materials if scope classification requires it before expansion.

## Beta Success Criteria

- A team can connect Drive and get useful findings within the first indexing session.
- At least one reviewer returns to the Doc Audit after the first demo.
- Weekly digest creates concrete follow-up actions.
- Findings are explainable enough that users trust why they were surfaced.
- Flagged documents get downstream engagement: opened from Liminal, reviewed, assigned, edited, commented on, dismissed with reason, or resolved.
- Indexing is reliable enough that the app feels like a service, not a script.
- Scheduled crawls keep findings and digests fresh without a human remembering to run the indexer.
- Beta users do not feel surprised by what data the app accessed or stored.

## Crawling Over Time

The beta should treat crawling as an ongoing service loop, not a manual command.

### Crawl Types

- Initial crawl: runs after a workspace connects Drive and indexes the selected Shared Drives or folder roots.
- Incremental crawl: runs on a schedule and fetches documents changed since the last successful crawl.
- Activity refresh: updates recent Drive Activity windows even when document content did not change.
- Link expansion crawl: follows newly discovered internal Drive links within the allowed workspace boundary.
- Backfill crawl: slowly fills in older or lower-priority documents without blocking fresh insights.
- Manual re-index: remains available as an admin override, but should not be the normal operating model.

### Scheduling Defaults

- Run lightweight incremental crawls daily for active beta workspaces.
- Run deeper backfill or link-expansion crawls weekly.
- Let each tenant configure crawl cadence and preferred run window, using a cron-style schedule plus timezone.
- Treat full reindexing as exceptional; normal scheduled crawls should focus on changed documents and recent activity.
- Stagger schedules across tenants to avoid Google API quota spikes.
- Pause or slow crawling for workspaces with repeated authorization, permission, or quota failures.

### Tenant Configuration

Each tenant should have crawl settings that admins can understand and change without editing code:

- Enabled or paused.
- Cron-style schedule, such as `0 3 * * *`, stored with the tenant timezone.
- Preferred crawl mode for scheduled runs: incremental by default, with optional activity refresh and weekly backfill.
- Maximum crawl frequency and quiet hours.
- Per-workspace overrides when one Shared Drive needs a different cadence.

The scheduler should interpret the tenant configuration, enqueue due crawls, and make the next scheduled run visible in the app.

### Freshness Signals

The UI should make crawl freshness visible:

- Last successful crawl.
- Current crawl status.
- Next scheduled crawl.
- Number of documents scanned, changed, skipped, and failed.
- Whether findings and digest are based on fresh, stale, or partial data.

### Failure Handling

- Retain durable crawl jobs and job attempts.
- Retry transient Google API errors with exponential backoff.
- Mark authorization failures as action-required.
- Keep the previous successful graph available when a crawl fails.
- Alert the service owner when repeated failures affect a beta workspace.

## Key Product Questions

- Should findings be visible to all invited teammates, or only admins/reviewers?
- Is the strongest weekly artifact an in-app digest, email, or exported review queue?
- What minimum engagement analytics are needed to understand whether flagged documents lead to useful follow-up?

## Suggested First Build Order

1. Hosted deployment of the existing app.
2. Web OAuth and encrypted token storage.
3. Tenant/workspace model.
4. Cloud indexing job model with scheduled incremental crawls.
5. Shared Drive selection and first-run onboarding.
6. Data deletion and disconnect.
7. Team invite and roles.
8. Weekly digest delivery.
9. OAuth verification package and beta trust docs.
