"""Term extraction and semantic alignment for indexed documents.

Phase 1: deterministic noun-phrase heuristics + Jaccard similarity.
No external NLP dependencies required.
"""

import json
import re
from datetime import datetime, timezone


STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "as", "is", "was", "are", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "shall", "can",
    "that", "this", "these", "those", "it", "its", "we", "our", "they",
    "their", "you", "your", "i", "my", "he", "she", "his", "her",
    "not", "no", "nor", "so", "yet", "both", "either", "each",
    "all", "any", "both", "few", "more", "most", "other", "some", "such",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "also", "just", "than", "about", "how", "what", "when",
    "where", "which", "while", "who", "whom", "why", "here", "there",
    "if", "else", "because", "since", "although", "though", "however",
    "therefore", "thus", "hence", "due", "per", "via", "use", "used",
    "using", "based", "across", "within", "without", "whether",
}

METRIC_SUFFIXES = {"rate", "ratio", "score", "nps", "dau", "mau", "wau", "ltv", "arr", "mrr",
                   "retention", "churn", "csat", "ctr", "cvr", "roas", "roi", "kpi"}

PROCESS_PATTERNS = re.compile(
    r"\b(onboarding|launching|rollout|deployment|migration|integration|"
    r"planning|tracking|monitoring|reporting|testing|reviewing|shipping|"
    r"go-live|sign-up|setup|indexing|syncing)\b"
)


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", " ", text)
    tokens = text.split()
    return [t.strip("-") for t in tokens if t.strip("-") and len(t) > 2]


def _classify_term(term: str) -> str:
    words = term.split()
    last = words[-1] if words else ""
    if last in METRIC_SUFFIXES or any(w in METRIC_SUFFIXES for w in words):
        return "metric"
    if PROCESS_PATTERNS.search(term):
        return "process"
    return "entity"


def extract_terms(text: str) -> list[tuple[str, str]]:
    """Return (term, term_type) pairs from text using noun-phrase heuristics."""
    tokens = _tokenize(text)
    filtered = [t for t in tokens if t not in STOPWORDS and not t.isdigit()]

    freq: dict[str, int] = {}

    # Single tokens
    for t in filtered:
        freq[t] = freq.get(t, 0) + 1

    # Bigrams
    for i in range(len(filtered) - 1):
        bigram = f"{filtered[i]} {filtered[i+1]}"
        freq[bigram] = freq.get(bigram, 0) + 1

    # Trigrams
    for i in range(len(filtered) - 2):
        trigram = f"{filtered[i]} {filtered[i+1]} {filtered[i+2]}"
        freq[trigram] = freq.get(trigram, 0) + 1

    # Keep terms that appear at least twice, or single tokens that appear at least once
    # and aren't stopwords. For unigrams keep freq >= 1, for n-grams freq >= 2.
    results = []
    for term, count in freq.items():
        words = term.split()
        if len(words) == 1 and count >= 1:
            results.append((term, _classify_term(term), count))
        elif len(words) > 1 and count >= 2:
            results.append((term, _classify_term(term), count))

    return [(term, ttype) for term, ttype, _ in results]


def index_doc_terms(conn, doc_id: str, text: str) -> None:
    """Extract terms from text and store in doc_terms table."""
    tokens = _tokenize(text)
    filtered = [t for t in tokens if t not in STOPWORDS and not t.isdigit()]

    freq: dict[str, int] = {}
    for t in filtered:
        freq[t] = freq.get(t, 0) + 1
    for i in range(len(filtered) - 1):
        bigram = f"{filtered[i]} {filtered[i+1]}"
        freq[bigram] = freq.get(bigram, 0) + 1
    for i in range(len(filtered) - 2):
        trigram = f"{filtered[i]} {filtered[i+1]} {filtered[i+2]}"
        freq[trigram] = freq.get(trigram, 0) + 1

    conn.execute("DELETE FROM doc_terms WHERE doc_id = ?", (doc_id,))
    for term, count in freq.items():
        words = term.split()
        if (len(words) == 1 and count >= 1) or (len(words) > 1 and count >= 2):
            ttype = _classify_term(term)
            conn.execute(
                "INSERT OR REPLACE INTO doc_terms (doc_id, term, frequency, term_type) VALUES (?,?,?,?)",
                (doc_id, term, count, ttype),
            )
    conn.commit()


def _term_set(conn, doc_id: str, top_n: int = 30) -> set[str]:
    """Return the top-N most frequent terms for a doc (focuses Jaccard on key concepts)."""
    rows = conn.execute(
        "SELECT term FROM doc_terms WHERE doc_id = ? ORDER BY frequency DESC LIMIT ?",
        (doc_id, top_n),
    ).fetchall()
    return {r["term"] for r in rows}


def compute_alignment(conn, src_id: str, dst_id: str) -> dict:
    """Compute Jaccard alignment between two docs. Returns score and term lists."""
    src_terms = _term_set(conn, src_id)
    dst_terms = _term_set(conn, dst_id)

    if not src_terms or not dst_terms:
        return {
            "alignment_score": None,
            "shared_terms": [],
            "divergent_terms": [],
        }

    shared = src_terms & dst_terms
    union = src_terms | dst_terms
    score = len(shared) / len(union) if union else 0.0

    # Divergent = terms in src not in dst, sorted by frequency descending
    divergent_raw = src_terms - dst_terms
    freq_rows = conn.execute(
        f"SELECT term, frequency FROM doc_terms WHERE doc_id = ? AND term IN ({','.join('?'*len(divergent_raw))})",
        (src_id, *divergent_raw),
    ).fetchall() if divergent_raw else []
    divergent = [r["term"] for r in sorted(freq_rows, key=lambda r: r["frequency"], reverse=True)][:20]

    return {
        "alignment_score": round(score, 3),
        "shared_terms": sorted(shared)[:30],
        "divergent_terms": divergent,
    }


def refresh_ontology(conn) -> None:
    """Recompute doc_alignment for all linked doc pairs that have term data."""
    pairs = conn.execute("SELECT DISTINCT src_id, dst_id FROM doc_links").fetchall()
    now = datetime.now(timezone.utc).isoformat()
    for row in pairs:
        src_id, dst_id = row["src_id"], row["dst_id"]
        result = compute_alignment(conn, src_id, dst_id)
        if result["alignment_score"] is None:
            continue
        conn.execute(
            """INSERT OR REPLACE INTO doc_alignment
               (src_id, dst_id, alignment_score, shared_terms, divergent_terms, computed_at)
               VALUES (?,?,?,?,?,?)""",
            (
                src_id, dst_id,
                result["alignment_score"],
                json.dumps(result["shared_terms"]),
                json.dumps(result["divergent_terms"]),
                now,
            ),
        )
    conn.commit()
