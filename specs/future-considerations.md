# Future Considerations

These are important ideas, but they should not block the user-research MVP.

## Access and Admin Models

- Workspace admin/domain-wide delegation for durable org-managed access. Research (2026-09) confirms this is the right later tier, not a default: a Super Admin must authorize it per customer domain (it doesn't remove the "someone has to act" step, it changes what they authorize), it cannot reach personal Gmail accounts, and Google now requires multi-party approval for it because a single leaked key can read the whole domain.
- Preferred enterprise path over domain-wide delegation: a per-tenant Cloud service account that the Workspace admin or team lead adds as a member of each specific Shared Drive (directly or via a Google Group), the same way they'd share it with a coworker. No OAuth screen at all, smaller blast radius than domain-wide delegation, and it matches Liminal's own principle of treating the selected Drive scope as a product boundary — Google's sharing model enforces the boundary instead of app-level discipline.
- Granular Drive permission mirroring inside Liminal.
- Customer-managed encryption keys for enterprise customers.
- More advanced admin audit logs.

## Analytics and Measurement

- Richer product analytics across usage patterns.
- Cross-tenant aggregate benchmarks, only with anonymized and consented data.
- Longitudinal impact reporting: whether stale docs get refreshed, orphaned docs get linked, and duplicate specs get consolidated.
- Team-level knowledge health trends over quarters.

## Collaboration and Notifications

- Weekly digest email.
- Slack digest and action routing.
- Follow-up reminders.
- Exports or sync into external task trackers.

## Data and Signal Expansion

- LLM-enhanced terminology alignment.
- Semantic duplicate detection.
- Deeper document health score.
- Change detection across revisions.
- Temporal graph snapshots.

## Cross-System Indexing

- Notion.
- GitHub.
- Confluence.
- Jira.
- Slack.
- Meeting transcripts.

## Product and Go-To-Market

- Public landing page.
- Self-serve signup.
- Pricing and billing.
- Workspace Marketplace listing.
- Formal enterprise security/compliance package.

## Open Questions For Later

- Should Liminal become a monitoring product, a knowledge ops workflow product, or both?
- Should the primary weekly artifact be email, Slack, or in-app digest?
- Should person-level detail ever be enabled by default?
- When does BigQuery become necessary for reporting?
- Which security commitments are required before inviting non-friendly beta customers?
