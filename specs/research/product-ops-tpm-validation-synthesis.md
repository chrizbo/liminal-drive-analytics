# Product Ops / TPM Validation Synthesis

## Purpose

This document turns the Sales Safari notes into a focused validation plan for Liminal Drive Analytics.

It should help answer:

- Is Product Ops / TPM a plausible first customer segment?
- Is the pain strong enough to support a product, not just a demo?
- Does Liminal have a wedge against AI chat over Drive and broader enterprise search?
- What should the next five customer conversations test?

## Current Read

The strongest evidence is not that people want "Drive analytics."

The stronger pattern is:

> Product Ops and TPMs already run rituals to keep roadmap, launch, decision, and status context trustworthy. Liminal may be valuable if it automates the document-health checks behind those rituals.

That means Liminal should avoid sounding like:

- A Google Drive file cleaner.
- A permission auditor.
- A generic knowledge dashboard.
- An AI chat box over Drive.
- A document management system.

It should test positioning closer to:

> A weekly Product Ops review queue for product docs that are stale, rising, duplicated, drifting, ownerless, or disconnected from decisions.

## Market Map

| Category | Buyer / user | What they solve | Competitor examples | Liminal risk | Liminal opening |
| --- | --- | --- | --- | --- | --- |
| AI chat over Drive | Individual PMs, operators, anyone using Workspace AI | Ask questions, summarize files, compare docs, draft updates. | ChatGPT Google Drive, Gemini in Drive, GPT for Google Workspace, ChatPDF. | Users may prefer natural language Q&A over another dashboard. | Liminal runs recurring detection and maintains review state without waiting for a user to know what to ask. |
| Enterprise AI search | IT, knowledge management, product/org leaders | Search and synthesize across Drive, Slack, Jira, Confluence, SharePoint, and many apps. | Glean, Atlassian Rovo. | Cross-system context is often more useful than Drive-only context. | Liminal can start narrower, with Product Ops-specific findings, bounded scope, and workflow rather than broad search. |
| Drive audit / security | Workspace admins, IT, security | Risky sharing, public links, former-employee access, bulk permission cleanup. | Soluvery Audit and Manage Google Drive, Drive Guard, Folgo. | Admins may interpret "Drive health" as permission/security hygiene. | These tools are gatekeeper context, not Product Ops workflow. Liminal should explain its read-only scope clearly. |
| Drive cleanup / storage | Individual users, admins, ops | Duplicates, large files, hidden files, folder size, storage bloat. | Filerev, Overdrive Tools, Duplicate File Finder. | "Duplicate/orphaned" language overlaps and can pull Liminal into cleanup utility territory. | Liminal's duplicate/orphaned signals should mean product-context risk, not storage cleanup. |
| Document management / workflow | IT, legal/compliance, regulated operations | Controlled documents, metadata, retention, approval workflows, audit logs. | AODocs, LumApps publishing. | Heavy platforms can absorb teams that want formal doc control. | Liminal can be lighter-weight: monitor existing docs and route review, not replace document systems. |
| Roadmap / Product Ops platforms | Product Ops, product leaders | Roadmaps, prioritization, stakeholder visibility, feedback, central product system. | Productboard, Aha, airfocus. | These tools claim the "single source of truth" layer. | Liminal can monitor the supporting doc universe around roadmaps, decisions, PRDs, launches, and status rituals. |

## Three Wedges To Test

### 1. Weekly Product Ops Doc-Health Review

Promise:

> Know which product docs need attention this week.

Signals:

- Stale hubs.
- Rising docs that need owner review.
- Duplicate specs.
- Orphaned meeting notes.
- Terminology drift.
- Important docs with no clear review owner.

Why it might work:

- Product Ops already owns rituals, systems, visibility, and process hygiene.
- The product maps to a recurring queue, not a one-time search.
- Review state, ownership, and disposition are things chat tools do poorly by default.

Risk:

- "Doc-health review" may feel like extra work unless tied to an existing meeting or reporting rhythm.

### 2. Pre-Meeting / Status Readiness Brief

Promise:

> Before planning, launch review, or exec status, see what changed, what is stale, and what needs follow-up.

Signals:

- Changed docs since last meeting.
- Quiet docs attached to active initiatives.
- Old decisions still referenced by active specs.
- Open follow-ups from meeting notes.
- Unowned risks or blockers.

Why it might work:

- Reddit and Product Ops materials show repeated pain around status, alignment, and late visibility.
- This attaches Liminal to a known ritual with urgency.
- The output can be a digest, not just an app destination.

Risk:

- AI chat can draft meeting briefs if users supply the right source set.
- Drive-only may miss Jira, Slack, Figma, or Confluence context.

### 3. Decision / Context Recovery

Promise:

> Stop reconstructing product context from Slack threads, old notes, and half-remembered decisions.

Signals:

- Meeting notes that mention decisions but are not linked into durable docs.
- Specs referencing old decision docs.
- Multiple docs that disagree on terminology or requirements.
- Product areas with many active docs but no clear hub.

Why it might work:

- The strongest Reddit artifact was about old tracking methods breaking as teams grew.
- The pain is emotionally sharp: people lose trust, repeat conversations, and waste hours.

Risk:

- This likely requires Slack/Jira/meeting transcript integrations eventually.
- A Drive-only beta must find teams whose product decisions genuinely live in Docs.

## Riskiest Assumptions

| Assumption | Why risky | How to test |
| --- | --- | --- |
| Product Ops owns this pain. | Product Ops may own process, but PMs/TPMs may feel the pain and IT may own access. | Ask who currently fixes stale docs, conflicting specs, missing owners, and pre-meeting context. |
| Drive-only is enough for beta. | Product context often spans Slack, Jira, Figma, Notion, Confluence, Linear, and meetings. | Ask interviewees to trace the last stale/missing-context incident across tools. |
| AI chat is insufficient. | Gemini, ChatGPT, Rovo, and Glean already answer many doc questions. | Ask what they use AI chat for, what they still verify manually, and what they forget to ask. |
| Teams will open a review queue. | A dashboard can become yet another place to check. | Anchor the product to an existing ritual: weekly ops review, launch review, roadmap meeting, or exec status. |
| Admins will approve bounded Drive indexing. | Drive access is sensitive, even read-only. | Ask Workspace admins what scope, storage, logs, deletion, and consent would be required. |
| Graph signals are compelling. | Users talk about trust, owners, stale docs, and decisions, not graphs. | Demo findings with the graph as evidence, then ask what users remember and trust. |

## What To Build Toward

Near-term product direction:

- Make the Doc Audit feel like a weekly Product Ops review queue.
- Add clearer owner, risk, review date, status, and disposition language.
- Make "why flagged" evidence obvious: links, activity, freshness, graph role, contributors.
- Keep the graph as supporting evidence, not the headline.
- Add pre-meeting digest language to the Overview: changed, stale, needs follow-up.
- Add admin-facing trust copy: selected Shared Drives/folders, read-only, metadata/link/activity first, no full body storage for MVP.

Do not overbuild yet:

- Broad AI chat.
- File cleanup utilities.
- Permissions auditor workflows.
- Full document management or approval workflow.
- Cross-system indexing before Drive-only demand is tested.

## Interview Script

Use these as problem interviews, not product demos.

### Opening

"I'm researching how Product Ops and TPMs keep product context trustworthy across docs, meetings, and status rituals. I'm not trying to pitch yet. I mostly want to understand where the work gets painful today."

### Current Workflow

- "Before a planning, launch-readiness, roadmap, or exec-status meeting, what do you manually check?"
- "Where do PRDs, launch docs, decision logs, meeting notes, and roadmap updates actually live?"
- "When someone asks 'what's the latest on this?', where do you look first?"
- "Do you mostly work from Drive links, Shared Drives, Recent/Home, search, Slack/Jira links, or asking people?"

### Pain Incidents

- "What was the last product doc you discovered was stale or misleading?"
- "What was the last decision your team had to reconstruct?"
- "Where did you look: Slack, Drive, Jira, Figma, meetings, or a person?"
- "What happened because the context was missing, stale, or contradictory?"
- "Who fixed it, if anyone?"

### Ownership And Review

- "What does 'owner' mean on your team: doc owner, decision owner, follow-up owner, accountable person, or something else?"
- "Does anyone own the product team's Shared Drive or documentation structure?"
- "How do you know which docs need review this week?"
- "When docs disagree, who resolves it?"

### AI And Search

- "Have you tried Gemini, ChatGPT, Glean, Rovo, or another AI/search tool for product context?"
- "What did it do well?"
- "Where did you not trust it?"
- "What do you still have to remember to ask?"
- "Would it be more useful to ask a chat question on demand, or get a weekly queue of issues you did not know to ask about?"

### Buying / Adoption

- "If a tool flagged stale, duplicated, or unowned product docs, who would care first?"
- "Who would approve connecting selected Shared Drives or folders?"
- "Would read-only access to selected scopes be acceptable?"
- "Where would findings need to show up: app, email, Slack, Jira, Asana, status doc, or meeting agenda?"
- "What would make this feel like useful Product Ops infrastructure rather than another dashboard?"

## Five-Interview Plan

Recruit for variance, not volume:

1. Product Ops lead at a Google Workspace-heavy B2B SaaS company, 50-500 employees.
2. TPM responsible for launch/program status across multiple workstreams.
3. Group PM or senior PM drowning in cross-functional context.
4. Chief of Staff / BizOps person who prepares exec or product leadership updates.
5. Workspace admin or IT ops person who has approved or rejected Drive-connected apps.

Success signal:

- At least three of five can name a recent stale/missing/contradictory product-context incident.
- At least two already run a recurring review/status ritual where findings could fit.
- At least two say AI chat helps but does not remove the need for review/ownership/follow-up.
- At least one can describe a plausible pilot scope using selected Shared Drives or folders.

Failure signal:

- People agree stale docs exist but cannot name a recent costly incident.
- No one owns the fix.
- Their context lives mostly outside Drive.
- They already trust Gemini/Glean/Rovo enough for this job.
- They would not open a review queue or route findings into an existing workflow.

## Messaging To Test

Primary:

> A weekly Product Ops review queue for product docs that need attention.

Variants:

- "Know which product docs are stale, rising, duplicated, drifting, or ownerless before they cause rework."
- "Stop reconstructing product context from Slack threads and old meeting notes."
- "AI chat helps when you know what to ask. Liminal finds the product-doc risks you forgot to ask about."
- "Drive shows what was recent. Liminal shows what needs review."
- "Evidence-backed, human-reviewed product knowledge checks."

Avoid for now:

- "Drive analytics."
- "Drive health score."
- "AI for Google Drive."
- "Knowledge management platform."
- "Document control."

## Research Backlog

Next evidence sources to mine:

- G2 reviews for Glean, Productboard, Aha, airfocus, Guru, Notion, and Confluence.
- Google Workspace Marketplace reviews for Drive audit, cleanup, and AI document apps.
- LinkedIn posts/comments by Product Ops and TPM leaders.
- Google Workspace Admin Community questions about approving Drive-connected apps.
- Native Reddit search for ProductManagement phrases: old meeting notes, Slack threads, decisions, weekly status, design docs, tribal knowledge.

## Source Notes

Detailed raw notes live in:

- [Product Ops / TPM Sales Safari Log](../product-ops-tpm-sales-safari-log.md)
- [Liminal Sales Safari Research Plan](../sales-safari-research-plan.md)

Representative external sources:

- Atlassian Product Operations: https://www.atlassian.com/agile/product-management/product-operations
- Productboard Product Operations: https://www.productboard.com/product-operations/
- Pragmatic Institute Product Operations: https://www.pragmaticinstitute.com/resources/articles/product/product-operations/
- ChatGPT Google Drive connector: https://openai.com/business/plugins/google-drive/
- Ask Gemini in Drive: https://support.google.com/drive/answer/16963068
- Glean Google Drive connector: https://www.glean.com/connectors/google-drive
- Atlassian Rovo MCP: https://developer.atlassian.com/cloud/rovo-mcp/
- Soluvery Audit and Manage Google Drive: https://workspace.google.com/marketplace/app/audit_and_manage_google_drive/1038143450653
- Filerev Organizer and Duplicate Remover: https://workspace.google.com/marketplace/app/organizer_duplicate_remover_for_google_d/31056671523
- GPT for Google Workspace: https://workspace.google.com/marketplace/app/gpt_for_google_workspace/845108372332
