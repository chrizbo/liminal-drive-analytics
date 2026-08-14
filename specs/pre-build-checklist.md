# Pre-Build Checklist

Use this checklist before starting implementation of the user-research MVP. It captures decisions that should be settled enough to avoid rework, without pretending the full product is already known.

## Decisions Already Made

- First access model: user OAuth.
- Drive scope: selected Shared Drives or bounded folder roots.
- Tenant model: multi-tenant from the beginning.
- Database: Cloud SQL/PostgreSQL first.
- Cloud setup: create a dedicated Google Cloud project for Liminal under the existing account/billing setup.
- Crawling: daily incremental by default, configurable per tenant later.
- Stored data: metadata, links, external URLs, terms, activity aggregates, findings, and review state.
- Full document body storage: deferred.
- Person-level activity: aggregate by default.
- Owner/creator identity: separate from general contributor activity because it is a document-health signal.
- Beta boundary: no landing page, billing, Slack integration, cross-system indexing, or broad self-serve launch.

## Build Slice 1 - Tenant-Aware Local Foundation

Before deploying to Google Cloud, make the local app structurally ready for the hosted model.

Done when:

- There are explicit `tenants`, `users`, `memberships`, and `workspaces` concepts.
- Existing demo/live workspaces can be represented as workspaces.
- Customer-owned tables can be queried through tenant/workspace context.
- Tests cover that tenant A cannot access tenant B data.
- The local demo still works.

Why first:

This reduces the risk of bolting multi-tenancy onto a code path that assumes one local database and one user.

## Build Slice 2 - Storage Adapter and PostgreSQL Compatibility

Done when:

- Core table access goes through repository/storage functions where tenant scoping matters.
- SQLite remains usable for local demo/dev.
- PostgreSQL compatibility issues are identified early: JSON handling, migrations, datetime storage, conflict/upsert syntax, and indexes.
- A migration path exists for the graph and findings tables.

## Build Slice 3 - Hosted Auth and Credential Storage

Done when:

- A dedicated Google Cloud project exists for the hosted Liminal service.
- Required service and Workspace APIs are enabled in that project.
- Runtime service accounts, secrets, KMS keys, and OAuth consent are configured.
- Web OAuth replaces local `token.json` for hosted use.
- Google refresh tokens are encrypted before storage.
- Drive access health is visible per workspace.
- Disconnecting Drive stops future crawls without deleting indexed data.
- Deleting workspace data removes indexed graph/activity/finding data.

## Build Slice 4 - Durable Crawling

Done when:

- Initial crawl runs as a durable job.
- Job progress survives process restarts.
- Failed crawls preserve the last successful graph.
- Scheduled incremental crawling focuses on changed documents and recent activity.
- Manual re-index enqueues a job instead of running inside a web request.

## Build Slice 5 - Research Instrumentation

Done when:

- Finding interactions are recorded: open, review, assign, dismiss, complete, follow up.
- Outbound clicks to Google Docs are recorded by finding/workspace.
- The app can compare activity before and after a finding is surfaced using aggregates.
- Reports remain tenant-scoped and do not require detailed per-person activity.

## Product Questions To Ask In Research

- Do users understand the difference between rising docs, stale hubs, duplicates, terminology drift, and orphaned notes?
- Which findings feel actionable versus noisy?
- Do users trust aggregate activity signals without detailed person-level histories?
- Is owner/creator identity useful for deciding who should act?
- Do users want to work the queue in Liminal, or export/send findings elsewhere?
- Does scheduled freshness matter after the first insight moment?
- What would make a team invite another reviewer?

## Technical Risks To Watch

- Google OAuth verification scope requirements.
- Drive API and Drive Activity API quota behavior.
- Shared Drive/folder boundary enforcement during link expansion.
- Tenant scoping gaps in older direct SQL queries.
- PostgreSQL migration complexity from SQLite idioms.
- Keeping graph analysis performant as tenant data grows.
- Avoiding accidental storage of full document text in logs, errors, or debug artifacts.

## Start-Build Recommendation

Start with Build Slice 1. Do not begin with Cloud deployment, OAuth polish, or crawler scheduling. The cleanest first move is making the current code understand tenant/workspace context while preserving the local demo.
