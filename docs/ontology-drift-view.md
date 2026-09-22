# A dedicated Ontology / Language-Drift view for Product Ops & TPM

**Status:** Design spec — not yet built. Companion to [`docs/ontology-roadmap.md`](ontology-roadmap.md),
which covers the underlying term-extraction/alignment engine this view is a UI layer on top of.

## Why this matters

`docs/ontology-roadmap.md` already grounds this work in the *"Getting the Words Right"*
playbook's idea of **[representation drift](https://dotwork.com/getting-the-words-right)**:
information loses fidelity as it moves through an organization — status gets flattened,
filtered, and reworded until dashboards feel confident while the underlying reality has
quietly diverged. That's the internal thesis. It's worth being explicit that this isn't
a novel or unstudied phenomenon — there's a real research literature behind the idea that
*language itself* is a legible signal of organizational health, not just a communication
nicety:

- **Terminology divergence is the default, not the exception.** Furnas, Landauer, Gomez &
  Dumais's classic HCI study, [*The Vocabulary Problem in Human-System Communication*](https://dl.acm.org/doi/10.1145/32206.32212)
  (CACM, 1987), found that two people independently choose the same word for the same
  thing less than 20% of the time across every domain they tested. This matters for how
  we read alignment scores: low overlap between two unrelated docs is expected and
  uninteresting. The signal worth surfacing is low overlap specifically *where it
  shouldn't exist* — between a hub doc and something that explicitly cites or descends
  from it.

- **Hub documents are supposed to work as boundary objects.** Star & Griesemer's concept
  of [boundary objects](https://en.wikipedia.org/wiki/Boundary_object) (1989) — artifacts
  "plastic enough" to adapt to each local team's needs while "robust enough to maintain a
  common identity" across them — is a useful frame for what a strategy doc or metrics
  dictionary is *for*. `alignment_score` in this codebase is effectively a proxy for
  whether a satellite document (a PRD, launch plan, retro) is actually treating the hub
  doc as a working boundary object, versus having quietly drifted into its own vocabulary.

- **Language convergence is a studied predictor of group cohesion — with real caveats.**
  Linguistic Style Matching (LSM) research (Gonzales, Hancock & Pennebaker,
  [2010](https://journals.sagepub.com/doi/10.1177/0093650209351468); Heuer,
  Müller-Frommeyer & Kauffeld, [2020](https://dx.doi.org/10.1177/1046496419874498)) shows
  that measurable language-style convergence between people predicts group cohesion, and
  in some settings task performance. The 2020 study is an important caution against
  overselling this: the LSM–performance relationship is *context-dependent* and can turn
  negative in longer-tenured teams (high mimicry can also indicate groupthink or
  suppressed dissent, not just healthy alignment). The honest framing for this view is
  "sustained, unexplained divergence from your org's own hub documents is worth a look,"
  not "higher alignment score is always better."

- **The same lens extends naturally to meetings, not just written docs** — which is the
  user's explicit ask for this view. Pentland's *[Honest Signals](https://mitpress.mit.edu/9780262515122/honest-signals/)*
  research found that communication *patterns* (not content) were among the strongest
  predictors of team performance his lab measured. Applied here: once transcripts are
  ingested (see below), the same drift lens can ask not just "does this doc use the
  strategy's vocabulary" but "does this team's *spoken* vocabulary in meetings ever make
  it into the docs" — a distinct and currently invisible gap (already flagged, unbuilt,
  in [`FUTURE_IDEAS.md`](../FUTURE_IDEAS.md) under Meeting Transcript Integration: "oral
  but not textual").

- **Framed as a governance problem, not a data-quality problem.** Industry writing on
  semantic drift ([Thoughtworks](https://www.thoughtworks.com/insights/blog/data-strategy/semantic-drift-stewarding-meaning-ai);
  [ER/Studio](https://erstudio.com/blog/semantic-drift-is-your-company-speaking-the-same-language/))
  converges on the same point: drift accumulates because the org's measurement/reward
  system tracks local delivery and records nothing about the cost of diverging
  definitions. That's exactly why this is a Product Ops/TPM view and not an engineering
  dashboard — the fix, when there is one, is a process/ownership fix, not a data-cleanup
  script.
- **The nearest engineering analogy — spec/documentation drift** — is a well-known
  predictor of downstream failure in software delivery (a spec that silently stops
  matching reality erodes trust in specs generally, and teams stop maintaining them,
  compounding the problem). Ontology drift between a strategy doc and its descendants is
  the product-org equivalent, and useful shorthand when pitching this to
  engineering-adjacent stakeholders.

- **A necessary caution: not all drift is a bug to fix.** Post-merger integration
  research (e.g. [McKinsey](https://www.mckinsey.com/capabilities/people-and-organizational-performance/our-insights/organizational-culture-in-mergers-addressing-the-unseen-forces),
  [PeopleOne](https://www.peopleone.io/resources/blogs/how-culture-can-make-or-break-your-merger-and-acquisition-integration/))
  documents identity-marking vocabulary (e.g. "legacy" vs. "the new company") persisting
  for years after a merger closes, because it reflects a real, unresolved organizational
  seam — not a documentation gap that better editing would fix. This view should let a
  TPM mark a hotspot as "known, tracked elsewhere" rather than treating every flagged
  pair as a defect to be closed.

**The honest summary:** language-drift metrics are a recognized, studied *class* of
organizational signal with real predictive research behind them — not proven, causal, or
universally "more alignment = better," but a legitimate thing for Product Ops to watch,
in the same category as stale-doc or orphaned-doc signals this app already surfaces
structurally.

## Current state (condensed — see `docs/ontology-roadmap.md` for full detail)

- Ontology data lives in `doc_terms` and `doc_alignment` ([`src/db.py:328-348`](../src/db.py)),
  populated by deterministic (no-LLM) term extraction and Jaccard alignment scoring in
  [`src/ontology.py`](../src/ontology.py).
- Today this is **demo-workspace only**: `index_doc_terms`/`refresh_ontology` are called
  exclusively from `src/demo_data.py`; `src/indexer.py` never populates these tables for
  real workspaces.
- The only existing surface for this data is the per-document drawer's "Concept
  alignment" section ([`web/app.js:692-745`](../web/app.js)) — visible one document at a
  time, and gated behind `state.workspace === "demo"`.
- `terminology_drift` is already a first-class findings signal type
  (`src/operations.py`), feeding the Doc Audit queue and the Team Digest brief, and
  `GET /ontology/drift?threshold=` already exists as an API endpoint
  ([`src/api.py:1426-1443`](../src/api.py)).
- There is no rollup/aggregate view across documents for this data, and no history table
  — `doc_alignment` is a snapshot that overwrites on each refresh.

## The `#ontology` view

Add a new route to the existing flat hash-router nav (`web/index.html`, route table in
`web/app.js`) alongside `overview`/`review`/`graph`/`documents`/`external`/`settings`. No
new role or permission system is needed or exists elsewhere in the app.

Layout follows the app's existing no-dependency, hand-rolled SVG/CSS convention (no chart
library is used anywhere in `web/`) and reuses established patterns rather than
inventing new ones:

1. **Corpus-level drift summary strip** — same `.summary-strip`/`.summary-metric` tiles
   used on `overview()`: total linked pairs scored, % below the drift threshold, count of
   hub docs with at least one divergent descendant. No trend arrow in v1 (see Non-goals).

2. **Hotspot documents list** — the core "what should I look at" list, built the same way
   as the existing `needs-attention` aggregation (`GET /analytics/needs-attention`):
   group `doc_alignment` rows by document, take the *minimum* `alignment_score` among each
   doc's linked neighbors, sort ascending, cap at N. Each row shows:
   - doc title/link and role (hub vs. satellite, from graph in-degree),
   - its worst-aligned neighbor and that score,
   - top divergent terms (already computed and stored — no new extraction needed),
   - a deep link into the existing per-document drawer for full detail.

   This needs one new backend aggregation, `GET /ontology/hotspots`, added alongside
   `ontology_drift_rows()` in `src/storage.py` — a new query, not a new table.

3. **Signal-chip filter row** — reuse the `.signal-chip.terminology_drift` styling already
   defined in `web/styles.css`, filtering the hotspot list the same way `review()`
   filters the Doc Audit.

4. **Review action routes into the existing Doc Audit**, not a parallel workflow. This
   view is a **lens onto data that already exists** (findings, alignment scores,
   divergent terms) — it must not become a second place to triage or dispose of the same
   signal.

5. **Stretch, not v1:** resurface the already-built-but-currently-unused `/clusters`
   endpoint (`src/api.py`, uses `communities()` in `src/graph.py`) to show drift within
   vs. across graph communities. The backend exists and is orphaned today; wiring it into
   this view is a natural v1.1, not required to ship v1.

## Real-data wiring

In scope for this effort (not deferred), since the view is not useful for real customers
while `doc_terms`/`doc_alignment` stay empty outside the demo workspace. This adopts
Phase 2 of `docs/ontology-roadmap.md` as-is rather than re-designing it:

- `src/content.py: fetch_doc_text(service, doc_id)` — Google Docs API content extraction.
- `doc_content` table: `(doc_id, text_hash, extracted_at)` only — raw text is never
  persisted, matching the roadmap's existing privacy design.
- Extend `src/indexer.py`'s per-document pass to fetch text, call `index_doc_terms`, and
  call `refresh_ontology(conn)` once per indexing run.
- Remove the `isDemo` gate on the drawer's alignment section and on the new `#ontology`
  route once real data exists.

### Extending to transcripts

Meeting transcripts are not ingested at all today — this is the tabled "Meeting
Transcript Integration" idea in `FUTURE_IDEAS.md`, which already points at the
agentics-beyond-code transcript processor pattern as a starting point. Treat this as a
**separate wiring phase** from Google Docs content extraction above (different source
system, different privacy questions — transcripts often contain more sensitive verbatim
speech than a polished doc):

- Once ingested, extract transcript terms into `doc_terms` same as any other document,
  but add a `source_type` column (`doc` | `transcript`) to distinguish them.
- This unlocks the "oral but not textual" signal already named in `FUTURE_IDEAS.md`:
  terms that show up repeatedly in meetings but never land in any written doc — a
  distinct and arguably higher-value signal than doc-to-doc drift, per the Pentland
  research above (communication pattern, not just content, predicts team performance).

## Non-goals for v1

- **Drift trend/history.** `doc_alignment` upserts on `(src_id, dst_id)` and overwrites
  the prior score on every refresh — there's no way to show "drift is worsening" without
  a schema change. Flagging, not building: an append-only `doc_alignment_history` table
  keyed by `(src_id, dst_id, computed_at)` is the natural Phase 2 follow-up.
- **Cluster-level rollup** beyond exposing the existing `/clusters` endpoint as a stretch
  item.
- **Cross-workspace comparison** — out of scope; this app's tenancy model is per-workspace
  throughout, and nothing here changes that.

## Open questions for stakeholders

1. Should a TPM be able to mark a hotspot "known, won't fix" independent of the
   underlying `terminology_drift` finding's own disposition — or is routing straight into
   the Doc Audit's existing disposition field sufficient? (The M&A research above
   suggests some drift is a permanent, acknowledged seam rather than something to
   resolve — the UI should make peace with that rather than nagging forever.)
2. Once transcripts are wired in, should transcript-only terms be scored against the same
   alignment mechanism as doc-to-doc pairs, or do they need their own threshold/severity
   calibration (spoken language is naturally less precise than written docs, so the same
   Jaccard threshold may over-flag)?
3. Is `GET /ontology/hotspots` capped/paginated the same way `needs-attention` is, or does
   Product Ops want to see the full ranked list for a workspace regardless of size?
