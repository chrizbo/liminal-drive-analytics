# OAuth and Security Readiness

## Principle

Liminal should be boringly trustworthy: read-only, explicit about what it accesses, careful about what it stores, and easy to disconnect.

## OAuth Scope Direction

Current local scopes:

| Scope | Purpose |
|---|---|
| `drive.readonly` | List Drive files, metadata, and downloadable content where supported. |
| `documents.readonly` | Read Google Docs body structure for links and terms. |
| `drive.activity.readonly` | Read view, edit, and comment activity signals. |
| `contacts.readonly` | Resolve activity actors to names/emails where Google permits it. |

Before public expansion, verify that each scope is still necessary. If a feature can work without a scope, defer that scope.

## Consent UX Requirements

Before sending a user to Google OAuth, the app should explain:

- Which Drive area will be indexed.
- What data is read: metadata, document links/content structure, activity events, contributor identities when available.
- What data is stored: document metadata, link graph, external domains/URLs, activity aggregates, findings, review state, extracted terms.
- What is not done: no Drive writes, no file permission changes, no ads, no sale of user data.
- How to disconnect and delete indexed data.

## Drive Access Authority

Drive access determines what the crawler is allowed to read from Google. It is separate from how Liminal encrypts credentials or stored analytics data.

### Beta Access Model

- Start with user OAuth for private beta customers.
- Limit crawling to customer-selected Shared Drives or bounded folder roots.
- Treat the selected Drive scope as a product boundary even if the connected account can technically see more.
- Store granted scopes, connected account identity, selected Drive roots, and access health per tenant/workspace.
- Re-check access during crawls because Google permissions can change after onboarding.

### Later Access Model

Workspace admin/domain-wide delegation can be added for customers that need durable org-managed access. This should be treated as a higher-trust deployment mode with stronger admin UX, audit logs, and security review.

### Access Failure Behavior

- If a user revokes OAuth, pause future crawls for affected workspaces.
- If the connected user loses access to selected Drive roots, mark the workspace as action-required.
- If admin delegation is removed, pause delegated crawls and preserve the last successful graph until deletion is requested.
- Do not delete stored analytics automatically just because Drive access fails; disconnect and data deletion should remain separate customer actions.

## Credential Encryption

Minimum requirements:

- Store refresh tokens encrypted with KMS-backed encryption.
- Never log access tokens or refresh tokens.
- Rotate app secrets through Secret Manager.
- Store granted scopes and token health per connection.
- Support revocation/disconnect.
- Delete encrypted tokens when a workspace or tenant disconnects.

Credential encryption protects the secret that lets the service call Google APIs. Destroying or revoking credentials stops future crawling, but it does not by itself delete already indexed graph data.

## Stored Data Encryption

Stored data encryption protects the customer-specific data and derived signals Liminal keeps after crawling. It is separate from Drive access and credential storage.

The service should encrypt stored Drive-derived data, but the encryption model should preserve the analytics that make the product useful.

### Baseline

- Use Google Cloud-managed encryption at rest for Cloud SQL, Cloud Storage, logs, and backups.
- Use HTTPS/TLS for all browser, API, and worker traffic.
- Encrypt Google refresh tokens and other credentials separately with KMS-backed envelope encryption.
- Keep production database access limited to the app and worker service accounts.

### Tenant-Level Protection

For beta, prefer tenant-scoped encryption boundaries for sensitive fields rather than encrypting every analytics row in a way that makes SQL unusable.

Recommended approach:

- Assign each tenant a KMS-wrapped data encryption key.
- Encrypt sensitive fields before storage: OAuth tokens, selected document titles if needed, owner/contributor emails, private URLs, notes, and any future document excerpts.
- Keep derived numeric metrics queryable: activity counts, link counts, freshness timestamps, severity scores, and finding status.
- Store normalized join keys only when needed for graph operations, and avoid storing full document body text.

### Analytics Impact

Field-level or tenant-level encryption affects reporting depending on what is encrypted:

- Encrypting tokens has no product analytics impact.
- Encrypting document body text has little impact if the service only stores extracted terms, links, and aggregates.
- Encrypting titles, emails, or URLs limits ad hoc cross-tenant debugging and support, but tenant-scoped reporting still works after decrypting for authorized requests.
- Encrypting graph join keys such as document IDs would make graph queries, incremental updates, and deduplication much harder. Avoid this for beta unless a customer requirement forces it.
- Encrypting aggregate metrics would make SQL reporting and trend analysis unnecessarily difficult. Keep aggregates queryable and tenant-isolated.

The default beta posture should be: strong platform encryption, tenant-scoped key material for sensitive fields, queryable derived analytics, and no cross-tenant analytics unless data is explicitly anonymized and aggregated.

### Separation of Controls

Keep these operations distinct:

| Control | What It Affects | Result |
|---|---|---|
| Revoke Google OAuth | Future Drive API access | Crawls stop; stored analytics remain until deleted. |
| Delete credential key/material | Future Drive API access | Crawls cannot resume until the customer reconnects. |
| Delete tenant data key/material | Encrypted stored sensitive fields | Stored sensitive fields become unreadable or are destroyed. |
| Delete indexed workspace data | Stored graph, activity, findings, and metadata | Product history for that workspace is removed. |

This separation lets a customer pause access without losing history, or delete stored data without relying on Google OAuth state.

## Data Retention Defaults

Initial beta defaults:

- Do not store full document body text unless a later feature explicitly needs it.
- Store extracted links, normalized external URLs, term frequencies, metadata, and activity aggregates.
- Store person-level activity only when needed for visible product features, and aggregate it by default.
- Separate owner/creator identity from non-owner activity because ownership is a document-health signal.
- Make detailed person-level display configurable for a tenant before scaling beyond friendly beta.
- Delete customer graph data on request.

## Tenant Isolation

Requirements:

- Every customer-owned table includes `tenant_id`.
- Every workspace-owned row includes `workspace_id`.
- All API reads/writes verify authenticated membership.
- Background jobs claim work by tenant/workspace and cannot write outside that scope.
- Tests cover cross-tenant read/write attempts.

## Logging Rules

Do log:

- Job IDs, tenant/workspace IDs, run status, counts, durations, API error classes.
- OAuth connection status without secrets.
- Aggregate indexing metrics.

Do not log:

- OAuth tokens.
- Full document contents.
- Large excerpts from documents.
- Full private URLs unless needed for debugging and explicitly scrubbed.

## Google Verification Preparation

Prepare these before expanding beyond a small private test population:

- Privacy policy URL.
- Terms or beta agreement.
- App domain verification in Google Cloud.
- Accurate OAuth consent screen branding.
- Scope-by-scope justification.
- Demo video showing why each scope is requested and where the feature appears in the app.
- Data deletion instructions.
- Security controls summary.

## Beta Trust Checklist

- [ ] Hosted app uses HTTPS only.
- [ ] OAuth callback validates state.
- [ ] Refresh tokens encrypted at rest.
- [ ] Drive access revocation and stored data deletion are separate flows.
- [ ] Sensitive customer fields have an explicit encryption classification.
- [ ] App sessions are secure and expire.
- [ ] CORS is restricted to production app origins.
- [ ] All write endpoints require authenticated role checks.
- [ ] Tenant isolation tests exist.
- [ ] Disconnect flow revokes or deletes stored credentials.
- [ ] Delete-data flow removes tenant/workspace graph data.
- [ ] Job logs avoid document contents and secrets.
- [ ] Privacy policy describes Google user data use plainly.

## Open Security Questions

- Is `contacts.readonly` necessary for the first beta, or can actor identity resolution be deferred?
- Should person-level activity be hidden by default to reduce sensitivity?
- What retention window should activity snapshots use for beta customers?
- Should beta customers sign a lightweight data-processing agreement?
- At what point should the service pursue a formal security assessment?
- Which fields need tenant-level encryption during beta versus standard database encryption at rest?
- Should the service ever support customer-managed encryption keys, or is that an enterprise-only feature?
