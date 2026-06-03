# Future Ideas

Ideas worth keeping but tabled for now. Revisit once the core graph is working.

---

## People API: Resolve Editor Identities

The Drive Activity API returns `people/XXXXX` resource names for editors and viewers, not human-readable names or emails. Adding the `https://www.googleapis.com/auth/contacts.readonly` scope and calling the People API would let us resolve these to display names and email addresses. This would make the Top Editors table and the Doc Detail contributors section genuinely useful — right now they show opaque IDs. At org scale with Domain-Wide Delegation, this becomes a full people graph.

---

## Dashboard: Plain-Language Summary

A short generated paragraph at the top of the dashboard summarizing the week: which docs are rising, how many stale hubs need attention, whether the external link profile shifted. Leaders read this before tables. Could be template-based first, LLM-generated later.

---

## Dashboard: Watchlist

Flag specific docs to track over time. Persisted in the local DB. Show watchlisted docs prominently on the overview with their current health status. Future: threshold-based alerts (email or Slack) when a watched doc crosses a stale or rising threshold.

---

## Cross-System Indexing

Once external links are mapped as nodes, the natural next step is actually indexing those systems. Priority order based on likely org usage:

- **Notion** — Notion API is well-documented; page links and backlinks are available.
- **GitHub** — Issues, PRs, and markdown files contain rich cross-references. Already have the agentics-beyond-code patterns for this.
- **Confluence** — REST API available; common in enterprise contexts.
- **Jira** — Issue links and epic structures form their own graph.

Each system added expands the graph and makes the "what lives outside Drive" question answerable.

---

## People Graph

Right now people appear only as actors on documents. A richer people graph would include:

- Who co-edits documents together (collaboration strength).
- Who is the effective "owner" of a cluster (not just Drive owner, but most active contributor).
- Bridge people — individuals who edit docs across multiple clusters (cross-functional connectors).
- Knowledge holders — people who are the sole significant contributor to high-in-degree docs (single points of failure).

---

## Document Health Score

Composite score per document combining:

- Freshness (last edit relative to creation date and doc age)
- Completeness (length, presence of headers/structure)
- Connectivity (in-degree + external link presence)
- Authorship breadth (sole author vs. team-maintained)
- Activity trend (rising/stable/stale)

Useful for surfacing "at risk" docs before they cause problems.

---

## Terminology Disambiguation

Beyond tracking term frequency, actively detect when the same term is used differently across clusters:

- "Launch" means different things to eng, marketing, and legal.
- "Owner" is overloaded across almost every org.

Surface these as candidate glossary entries with cluster-specific definitions. Could feed into an auto-generated org glossary.

---

## Change Detection / Alerts

Notify leaders when:

- A key hub doc's activity drops sharply (stale hub emerging).
- A new doc is rapidly accumulating inbound links (rising hub).
- A term appears in a cluster where it hasn't been used before.
- A doc that had many inbound links is deleted or moved.

Delivery could be email digest, Slack message, or GitHub Discussion (following the agentics-beyond-code pattern).

---

## Sentiment / Tone Analysis

Track whether documents are becoming more uncertain, more directive, or more hedged over time via revision history. A spec that was confident in v1 and is full of "TBD" and "pending discussion" by v8 is a signal worth surfacing.

---

## Meeting Transcript Integration

Following the agentics-beyond-code transcript processor pattern: ingest meeting transcripts, extract document references and terminology mentions, and connect them to the graph. A doc mentioned in 5 meetings but never linked from other docs is interesting — it's orally important but not textually connected.

---

## Temporal Graph Snapshots

Store full graph snapshots at regular intervals (weekly) so you can replay how the graph evolved:

- When did this cluster form?
- Which docs were hubs 6 months ago that aren't anymore?
- Is the org's knowledge becoming more or less connected over time?

---

## Sharing / Permissions as a Signal

Document sharing scope (private → team → org → public) combined with activity levels tells a story:

- Broadly shared but rarely visited = cluttered knowledge base.
- Narrowly shared but frequently visited = siloed critical knowledge.
- Recently broadened sharing + rising activity = deliberate knowledge propagation.

---

## Organizational Ontology Export

Generate a machine-readable ontology file (e.g., OWL or simple JSON-LD) from the extracted terminology graph. This could feed other tools — search ranking, onboarding bots, compliance checks — that need to understand what terms mean in this org's context.
