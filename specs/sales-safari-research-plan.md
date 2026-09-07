# Liminal Sales Safari Research Plan

## Goal

Question the validity of Liminal Drive Analytics before selling it too hard.

The research should test whether people already complain about the problems Liminal claims to solve, whether those problems have buying energy, and which roles naturally own the follow-up work.

## Product Hypotheses

Liminal is most likely valid if public evidence shows repeated pain around:

- Teams cannot tell which Drive docs are trusted, stale, duplicated, or load-bearing.
- Important decisions and follow-ups are scattered across docs, meetings, Slack, and personal folders.
- Search relevance is not the same as freshness or truth.
- People want a queue of specific document-health actions, not another generic dashboard.
- The person who feels the pain is close enough to budget, admin permission, or an executive sponsor to run a pilot.

It is less likely valid if the pain mostly resolves into:

- "We need better search" solved by Glean, Guru, Slite, or Google Workspace Gemini.
- "We need a wiki" solved by Notion, Confluence, Guru, or Slite.
- "We need Drive permissions/security audits" solved by IT governance products.
- "Our culture does not value documentation" where software has little leverage.

## Sales Safari Method

Use Sales Safari as online ethnography, not survey research.

For each thread, review, comment, or article, capture:

- Pain: what hurts, in the person's own language.
- Trigger: what caused them to care now.
- Stakes: time, money, customer risk, compliance risk, executive visibility, onboarding drag.
- Current workaround: asking people, searching Slack, migrating tools, weekly updates, manual audits, naming conventions.
- Jargon: words they use for the problem.
- Buyer clues: role, company size, tool stack, budget owner, admin access.
- Product pull: what they explicitly wish existed.
- Anti-pull: what they reject, distrust, or fear.

Avoid asking "would you use Liminal?" until after the public evidence map is strong. The better first question is: "Where do people already spend effort because this hurts?"

## Candidate Audiences

### 1. Product Ops / TPM / Chief of Staff

Likely pain:

- Cross-functional plans, specs, launch docs, and decision records drift out of sync.
- Leaders want a weekly pulse without manually reading Drive.
- Follow-ups from meetings are not connected back into source documents.

Best Liminal angle:

- "A weekly knowledge-health review queue for product and operations teams."

Risk:

- They may lack Workspace permissions and need IT/admin sponsorship.

### 2. Product Managers and Group PMs

Likely pain:

- Too many workstreams, stale context, duplicate specs, pressure to know what changed.
- Anxiety around missing the important doc or acting on old context.

Best Liminal angle:

- "Know which docs changed, which docs are relied on, and which need review."

Risk:

- Individual PM pain may be intense but not obviously budgeted.

### 3. Knowledge Management / Enablement / Internal Comms

Likely pain:

- Source-of-truth sprawl across Drive, Notion, Confluence, Slack, and help centers.
- High cost of keeping published/internal knowledge current.

Best Liminal angle:

- "Find stale or conflicting source material before it gets reused."

Risk:

- They may prefer a full knowledge platform instead of a Drive-native analytics layer.

### 4. Google Workspace Admin / IT Ops

Likely pain:

- Shared Drive ownership, permissions, departed-user cleanup, access issues, and migration complexity.

Best Liminal angle:

- "Operational visibility into Drive health without reading document contents."

Risk:

- Their buying frame may be security/compliance, not document usefulness.

### 5. Customer Success / Support / Revenue Enablement

Likely pain:

- Teams send old decks, API docs, support macros, or implementation notes to customers.
- Wrong docs can become customer trust and renewal risk.

Best Liminal angle:

- "Catch stale customer-facing or enablement docs before they cause external damage."

Risk:

- They may not care about the Drive graph unless it routes into their workflow.

## Watering Holes

Start with these sources:

- Reddit: r/ProductManagement, r/sysadmin, r/msp, r/googleworkspace, r/technicalwriting, r/customersuccess.
- Hacker News: Ask HN and Launch HN threads about knowledge bases, enterprise search, docs, wikis, and AI search.
- Google Workspace Admin Community: Shared Drive ownership, migration, permissions, Drive audit, departed-user file transfer.
- G2/Capterra reviews: Glean, Guru, Slite, Notion, Confluence, Document360, enterprise search, knowledge management.
- Vendor blogs and comment sections: Slite, Guru, Glean, Question Base, Docspeare, Document360, Atlassian, Google Workspace.
- LinkedIn posts: stale documentation incidents, knowledge ops, product ops, enablement, customer-facing doc mistakes.

## Search Queries

Use problem language first:

- `"stale docs" "Google Drive"`
- `"outdated docs" "Google Drive"`
- `"which doc is current" "Google Drive"`
- `"source of truth" "Google Drive" "Slack"`
- `"documentation goes stale" "knowledge base"`
- `"stale documentation" "AI search"`
- `"Google Drive" "duplicate docs"`
- `"Google Drive" "version sprawl"`
- `"shared drive" "ownerless" "Google Workspace"`
- `"Google Drive" "departed employee" "files"`
- `"Confluence" "stale documentation" "trust"`
- `"Notion" "source of truth" "Google Drive"`

Use audience language second:

- `site:reddit.com/r/ProductManagement stale docs product specs`
- `site:reddit.com/r/ProductManagement "source of truth"`
- `site:reddit.com/r/sysadmin "Google Drive" "shared drive"`
- `site:reddit.com/r/msp "Google Workspace" "Drive"`
- `site:news.ycombinator.com "stale documentation"`
- `site:support.google.com/a/thread "Shared Drive" "ownership"`
- `site:g2.com/products/glean/reviews "Google Drive"`
- `site:g2.com/products/guru/reviews "outdated docs"`

## Early Evidence From Desk Research

- Google Drive APIs expose file metadata, versions, modified time, owners for My Drive items, Shared Drive IDs, and activity records. This supports Liminal's technical premise, though Shared Drive ownership semantics differ from personal Drive.
- Google Workspace Admin Reports can expose Drive audit activity for up to the last 180 days, which may matter for admin-led pilots and limits historical backfill claims.
- Google says Shared Drives are organization-owned rather than individual-owned, making Shared Drive workflows a natural beta boundary.
- Public HN discussions repeatedly frame stale documentation as a trust problem: once people are burned, they ask humans instead of trusting docs.
- G2 reviews for Glean and Guru show strong existing demand for cross-tool knowledge search, trusted answers, source freshness, ownership, and reduced repeated questions.
- Vendor messaging from Slite, Question Base, and Docspeare has converged around stale knowledge, AI answers, trust, and human-reviewed freshness loops. This validates the problem but also shows a crowded narrative.

## Things To Disprove

- Are teams actually willing to open a separate Doc Audit queue, or do findings need to route into Slack/email/Jira/Asana?
- Does the buyer care about graph structure, or only about freshness, ownership, and actionability?
- Is Google Drive-only too narrow, or valuable because it avoids tool-migration work?
- Are "terminology drift" and "orphaned meeting notes" must-have signals or interesting demos?
- Can Liminal avoid feeling like employee surveillance?
- Does read-only, bounded-scope OAuth reduce security concern enough for beta customers?

## Best First Outreach Targets

Prioritize people who both feel the pain and can get access:

1. Product Ops / TPM leaders at Google Workspace-heavy B2B SaaS companies, 50-500 employees.
2. Chiefs of Staff or operations leads at remote/hybrid teams with heavy planning-doc culture.
3. Enablement or CS ops leaders whose teams maintain customer-facing docs in Drive.
4. Friendly Google Workspace admins who manage Shared Drives for a product or go-to-market org.
5. Technical writing / documentation leaders in companies where Google Docs are the drafting source before docs are published elsewhere.

The strongest wedge is probably not "Drive analytics." It is:

> "Find the docs your team is relying on that are stale, duplicated, drifting, or ownerless before they cause rework."

## Two-Week Research Sprint

### Day 1: Setup

- Create a spreadsheet or markdown table with fields from the Sales Safari Method section.
- Pick two audiences only: Product Ops/TPM and Knowledge/Enablement.
- Collect 30 raw artifacts without synthesizing.

### Days 2-4: Public Threads

- Review 10 Reddit threads, 10 HN threads, and 10 Google Workspace Admin Community threads.
- Extract pains, triggers, stakes, workarounds, and jargon.
- Mark each artifact as strong, medium, weak, or irrelevant.

### Days 5-6: Competitor Review Mining

- Read reviews for Glean, Guru, Slite, Notion, Confluence, and Document360.
- Look for "what problems are you solving?" and "what do you dislike?"
- Separate search/discovery pain from freshness/trust/action pain.

### Days 7-8: Synthesis

- Cluster pains by job-to-be-done.
- Identify the top 3 moments where a person would actively seek help.
- Write candidate landing-page copy using only observed language.

### Days 9-10: Outreach Prep

- Build a list of 20 people matching the strongest audience.
- Ask for problem interviews around their current doc-health workflow, not product feedback.
- Prepare a 5-minute demo only after asking about their current system.

## Decision Criteria

Continue toward private beta if:

- At least 20 strong artifacts show recurring stale/trust/source-of-truth pain.
- At least 8 artifacts include meaningful stakes: customer risk, missed work, onboarding drag, exec visibility, compliance, or rework.
- At least 5 artifacts imply a concrete owner or budget path.
- Interviewees can name a real review workflow where findings would be acted on.

Reposition if:

- The strongest pain is generic enterprise search.
- The strongest buyer is IT/security rather than product/ops.
- The most urgent use case is customer-facing documentation governance.

Pause or narrow if:

- People agree the problem exists but no one owns it.
- They want a one-time cleanup service rather than a recurring product.
- Trust/security concerns block Drive connection even for bounded Shared Drives.

## Sources Used For Initial Framing

- 30x500 Sales Safari positioning: https://courses.30x500.com/p/30x500-pioneers
- Sales Safari in Action overview: https://stackingthebricks.com/vintage-sales-safari-in-action/
- Google Drive Activity API: https://developers.google.com/workspace/drive/activity/v2
- Google Drive files resource: https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- Google Workspace Reports API overview: https://developers.google.com/workspace/admin/reports/v1/overview
- Google Drive activity report: https://developers.google.com/workspace/admin/reports/v1/guides/manage-audit-drive
- Shared drives overview: https://developers.google.com/workspace/drive/api/guides/about-shareddrives
- Ask HN, managing company knowledge base: https://news.ycombinator.com/item?id=30371723
- Ask HN, medium-size engineering org documentation: https://news.ycombinator.com/item?id=26334164
- HN stale documentation discussion: https://news.ycombinator.com/item?id=26413937
- Glean G2 reviews: https://www.g2.com/products/glean-technologies-glean/reviews
- Guru G2 reviews: https://www.g2.com/products/guru/reviews
- Slite stale documentation research article: https://slite.com/learn/dangers-of-stale-documentation
- Docspeare Google Workspace documentation platform: https://www.docspeare.com/
- Google Workspace Admin Shared Drive ownership thread: https://support.google.com/a/thread/55174459/ownership-of-shared-drive-files
- Google Workspace Admin transfer ownership thread: https://support.google.com/a/thread/407671645/transfer-ownership-of-shared-drive-folders-in-google-drive-workspace
