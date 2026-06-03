# Technical Specification

## Overview

Liminal Drive Analytics indexes Google Drive documents, extracts links and activity signals, builds a graph, and runs analytics over that graph on a schedule. The system is designed to start small (personal Drive, local machine) and scale to org-wide deployment on Google Cloud.

---

## Data Model

### Nodes

| Type | Key | Attributes |
|---|---|---|
| `Document` | Google file ID | title, owner, created_at, modified_at, mime_type, last_indexed_at |
| `Person` | Google user ID | email, display_name |
| `ExternalResource` | normalized URL | domain, url, resource_type (notion/jira/github/etc.) |
| `Term` | normalized string | text, first_seen, last_seen |

### Edges

| Type | From → To | Attributes |
|---|---|---|
| `LINKS_TO` | Document → Document | count, first_seen, last_seen |
| `LINKS_TO_EXTERNAL` | Document → ExternalResource | count, anchor_text, first_seen |
| `AUTHORED` | Person → Document | created_at |
| `EDITED` | Person → Document | last_edit_at, edit_count |
| `VIEWED` | Person → Document | last_view_at, view_count |
| `COMMENTED` | Person → Document | last_comment_at, comment_count |
| `MENTIONS_TERM` | Document → Term | frequency, first_seen, last_seen |

### Activity Snapshots

Time-series table capturing activity counts per document per day. Used for trend detection (rising/stale signals).

```
document_id | date | views | edits | comments | inbound_link_count
```

---

## File Type Coverage

Drive Activity API tracks all file types. Link extraction support varies:

| File Type | Activity | Link Extraction | API |
|---|---|---|---|
| Google Docs | ✓ | ✓ full | Docs API |
| Google Slides | ✓ | ✓ full | Slides API |
| Google Sheets | ✓ | partial (cell hyperlinks) | Sheets API |
| Google Forms | ✓ | minimal | — |
| Uploaded PDFs / Office docs | ✓ | requires download + parse | Drive API (download) |
| Google Sites / Drawings | ✓ | limited | — |

**Phase 1 scope:** Google Docs and Slides only. These are where prose and cross-references live. Sheets cell-link extraction and PDF parsing can be added later.

---

## Activity Data: Retention and Granularity

The Drive Activity API returns individual timestamped events (no pre-aggregated counts). Events can be filtered by time range:

```python
filter='time >= "2023-01-01T00:00:00Z"'
```

**Retention:** Google does not publish a hard retention limit. In practice, activity is available from approximately when a file was created or ~2018 (when Drive Activity API v2 launched), whichever is later. Treat activity history as "substantial but not guaranteed complete" — it is a trend signal, not an audit trail.

**Day-by-day granularity:** Achieved by grouping events by date client-side. Each event has a precise timestamp. Day-level aggregation is reliable for recent history; older data may have gaps.

---

## Indexing Strategy

### Phase 1 — Core graph (recent Docs + Slides)

1. Query Drive API for Docs and Slides modified in the last 90 days.
2. For each file, fetch full content via the appropriate API (Docs or Slides) and extract all hyperlinks.
3. Resolve each link: internal Drive file, Google Doc/Slide, or external resource.
4. Fetch Drive Activity API events for each file; group by day and store as activity snapshots.
5. Write nodes, edges, and snapshots to local graph store.

### Phase 2 — Expand via link graph

Follow outbound `LINKS_TO` edges to docs that weren't in the initial 90-day window. This surfaces older but still-referenced docs without scanning everything. Repeat until no new nodes are discovered or a depth/age limit is hit.

### Phase 3 — Background full scan

Periodic low-priority pass over all Drive files, oldest-modified first. Fills in the long tail.

### Incremental updates

On subsequent runs, only re-fetch docs whose `modifiedTime` is newer than `last_indexed_at`. Activity snapshots are appended daily.

---

## Analytics

### Rising documents

- Compute 7-day rolling activity sum vs. prior 7-day sum.
- Rising = activity velocity positive and above a threshold.
- Optional: weight by in-degree (hub docs rising are higher signal).

### Stale documents

- High historical activity OR high in-degree, but low recent activity (last 30 days < threshold).
- Stale hub docs are flagged as higher priority — they're navigation points people may still follow.

### Key/hub documents

- In-degree rank (number of other docs linking to this doc).
- Betweenness centrality for docs that act as bridges between clusters.
- Decay-weighted: recent links count more than old ones.

### Clusters

- Community detection (e.g., Louvain) on the doc→doc link graph.
- Each cluster roughly corresponds to a team, project, or topic area.
- Label clusters by extracting top terms from member docs.

### Ontology

- Extract noun phrases and proper nouns from all indexed docs using NLP.
- Track frequency per term per time period.
- Rising terms = new concepts gaining traction.
- Declining terms = fading initiatives or renamed concepts.
- Terms that appear in many clusters but with different surrounding context = potential ambiguity worth surfacing.

---

## External Links

Every link that doesn't resolve to a Google Drive file becomes an `ExternalResource` node:

- URL is normalized (strip tracking params, normalize trailing slashes).
- Domain is extracted for type classification (`notion.so` → Notion, `github.com` → GitHub, etc.).
- Aggregated view: which external systems are most linked from Drive, and from which doc clusters.

This passively maps what knowledge lives outside Drive without requiring those systems to be indexed.

---

## Storage

### Recommended stack

| Layer | Library | Purpose |
|---|---|---|
| Graph persistence | SQLite | Nodes, edges, metadata — simple, embedded, no server |
| Graph analysis | [NetworkX](https://networkx.org/) | Centrality, community detection, PageRank, traversals |
| Activity time-series | SQLite (same DB) | Daily activity snapshots per document |
| Term index | SQLite FTS5 | Full-text search over extracted document terms |

SQLite stores everything at rest. NetworkX loads the graph in-memory for analysis — appropriate for personal Drive scale (tens of thousands of nodes). All algorithms needed (Louvain community detection, betweenness centrality, in-degree ranking) are available in NetworkX out of the box.

### Upgrade path

When personal Drive scale is outgrown or graph-native traversal queries become awkward in SQL:

- **[Kuzu](https://kuzudb.com)** — embedded graph database (like SQLite for graphs), Cypher query language, no server required. Easy drop-in replacement for the SQLite graph layer, keeps the local-first workflow intact.
- **[DuckDB](https://duckdb.org)** — columnar analytical engine, ideal for the time-series activity layer when trending queries get complex. Embedded, fast, SQL-native.
- **[Neo4j Community](https://neo4j.com/download/)** — full graph database with a browser-based visual explorer. Worth adopting if you want to explore the graph interactively. Runs via Docker locally; has a managed cloud tier (AuraDB, free tier available) as a Cloud migration target.

### Cloud migration

For org-wide Google Cloud deployment:

---

## Google Cloud Migration Path

Designed for clean lift-and-shift:

| Local | Google Cloud |
|---|---|
| SQLite | Firestore (graph) or BigQuery (analytics) |
| Python script | Cloud Run job |
| Cron / manual | Cloud Scheduler |
| OAuth desktop flow | Service Account + Domain-Wide Delegation (Workspace) |
| Terminal output | Simple dashboard (Streamlit on Cloud Run, or Looker Studio over BigQuery) |

For personal Drive testing, OAuth desktop flow is sufficient. For org-wide deployment, a Workspace Admin grants Domain-Wide Delegation to a service account so the indexer can access all users' Drive activity.

---

## API Scopes Required

| Scope | Purpose |
|---|---|
| `https://www.googleapis.com/auth/drive.readonly` | List files and metadata |
| `https://www.googleapis.com/auth/documents.readonly` | Read document content |
| `https://www.googleapis.com/auth/drive.activity.readonly` | View/edit/comment activity |

---

## Phases and Milestones

| Phase | Goal | Done when |
|---|---|---|
| 0 | Auth + list files | Can list 10 recent Docs from personal Drive |
| 1 | Link extraction | Can parse a doc and extract all hyperlinks |
| 2 | Graph construction | NetworkX graph built from a 90-day window |
| 3 | Activity signals | Rising/stale/hub scores computed |
| 4 | External link map | External nodes typed and aggregated |
| 5 | Ontology pass | Top terms per cluster extracted |
| 6 | Cloud migration | Runs on Cloud Scheduler, data in BigQuery |
