# Ontology & Semantic Alignment — Roadmap

## Why this matters

Drive Analytics surfaces *structural* signals about your knowledge base: which docs are hubs, which
are rising, which have gone stale. The next layer is *semantic*: are the docs that reference each
other actually saying the same things?

The [Getting the Words Right](https://dotwork.com/getting-the-words-right) playbook names this
problem well — organizational knowledge breaks down through **representation drift**. Terminology
diverges across documents, hub docs fall out of sync with the docs that pull from them, and leaders
lose visibility not because data is missing but because the words have quietly stopped meaning the
same thing.

### The endurant / perdurant lens

- **Endurants** (persistent entities): products, metrics, principles, values — typically defined
  in hub documents (strategy, metrics dictionary, architecture decisions)
- **Perdurants** (unfolding processes): launches, retros, experiments, incidents — typically
  reference those hubs

A PRD that references the strategy doc should echo its language. When it doesn't — when "activation"
in the strategy becomes "adoption" in the launch plan — that's a signal worth surfacing.

---

## Phase 1 — Demo ontology foundation *(current)*

**Status:** Planned  
**Scope:** Demo workspace only, no LLM dependency

### What's built

- **Doc content stubs** in `src/demo_data.py` — representative text for each demo document,
  seeded with deliberate terminology variation across the linked graph
- **`doc_terms` table** — extracted terms per document (term, frequency, type: entity/process/metric)
- **`doc_alignment` table** — pairwise alignment scores for linked doc pairs (Jaccard on key terms,
  shared_terms, divergent_terms)
- **`src/ontology.py`** — term extraction (noun-phrase heuristics, no NLP dependency) and alignment
  computation
- **API endpoints:**
  - `GET /ontology/terms?doc_id=...`
  - `GET /ontology/alignment/{doc_id}`
  - `GET /ontology/drift?threshold=0.4`
- **Frontend (demo-gated):**
  - Document drawer: "Concept alignment" section with per-linked-doc alignment bars and divergent terms
  - Graph view: optional "Show alignment" toggle that colors edges green/yellow/red by score

### Interesting signals the demo surfaces

| Doc pair | Expected signal | Why |
|----------|-----------------|-----|
| `old-requirements` → `product-strategy` | Low alignment (red) | Legacy doc uses pre-2026 strategy language |
| `launch-plan` → `product-strategy` | Medium alignment (yellow) | Uses "adoption" vs. strategy's "activation" |
| `onboarding-spec` → `roadmap` | Medium alignment (yellow) | Avoids "activation", uses "setup flow" |
| `experiment` → `metrics` | High alignment (green) | Correctly uses metrics dictionary vocabulary |
| `gtm` → `launch-plan` | Medium (yellow) | Mixed vocabulary |

---

## Phase 2 — Live Drive content extraction *(planned)*

**Depends on:** Phase 1 complete  
**Scope:** All workspaces; requires Google Docs API scope addition

### What's added

- **`src/content.py`** — `fetch_doc_text(service, doc_id) -> str` using the Google Docs API
  (`documents.get()` returns structured JSON; we extract paragraph text)
- **`doc_content` table** — `(doc_id, text_hash, extracted_at)` — stores content hash and
  extraction timestamp; raw text is *not* stored (privacy-conscious)
- **`src/indexer.py` extension** — after link extraction, fetch + term-index Google Doc content
- **Ontology endpoints** become workspace-agnostic; frontend removes demo gate

### Privacy design

Raw document text is never persisted. Only extracted term frequencies are stored. For sensitive
organizations, content extraction can be scoped to hub documents only (configurable via settings).

---

## Phase 3 — LLM-enhanced semantic alignment *(planned)*

**Depends on:** Phase 2 complete  
**Scope:** Optional; requires OpenAI key (already used for brief polishing)

### Why Phase 1 doesn't need LLMs

Phase 1 uses deterministic term extraction (noun-phrase heuristics + stopword filtering) and
Jaccard similarity for alignment scoring. This is sufficient when terminology varies lexically —
"activation" vs. "adoption" shows as low overlap. The gap: true synonyms that differ only
semantically (same concept, different word choice) are invisible to Jaccard. Phase 3 closes that.

### What's added

- **Embedding-based term clustering** — "activation" and "adoption" detected as near-synonyms in
  org context using `text-embedding-3-small`
- **Synonym drift detection** — surface candidate synonym pairs: "these two terms may mean the same
  thing across your docs — consider aligning to one"
- **Auto-generated org glossary** — cluster-specific definitions for overloaded terms (feeds the
  "Terminology Disambiguation" idea from `FUTURE_IDEAS.md`)
- **LLM alignment summaries** — natural language explanation of misalignment per doc pair:
  "launch-plan uses 'adoption' where strategy uses 'activation' — consider aligning to the
  strategy's vocabulary"

---

## Connection to other roadmap items

- **Document Health Score** (`FUTURE_IDEAS.md`): alignment score becomes one component of the
  composite health score
- **Organizational Ontology Export** (`FUTURE_IDEAS.md`): Phase 3 term graph feeds JSON-LD export
- **Change Detection / Alerts** (`FUTURE_IDEAS.md`): alert when a key hub doc's vocabulary shifts
  (new terms appear, established terms disappear)
- **Cross-System Indexing** (`FUTURE_IDEAS.md`): Phase 2 content extraction patterns extend
  naturally to Notion, Confluence page content
