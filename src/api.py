"""FastAPI backend — exposes Drive Analytics data as JSON.

Designed so the Streamlit dashboard can be replaced with any frontend
(React, Observable, plain JS) without touching the data layer.

Run with:
    uvicorn src.api:app --reload

Or from the src/ directory:
    uvicorn api:app --reload
"""

import os
import sys
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import connect, init
from graph import build_doc_graph, in_degree_rank, communities
from analytics import (
    activity_by_doc, stale_activity, title_map,
    rising_docs, stale_docs,
    STALE_WINDOW_DAYS, STALE_RECENT_MAX,
)
from utils import doc_url, direness_score, severity_label

app = FastAPI(
    title="Drive Analytics API",
    description="Graph-based analytics for Google Drive documents.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_conn():
    conn = connect()
    init(conn)
    return conn


# ── Overview ──────────────────────────────────────────────────────────────────

@app.get("/overview")
def overview():
    """High-level counts — documents, links, external links, activity days."""
    conn = get_conn()
    result = {
        "documents_indexed": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "doc_links":         conn.execute("SELECT COUNT(*) FROM doc_links").fetchone()[0],
        "external_links":    conn.execute("SELECT COUNT(*) FROM external_links").fetchone()[0],
        "activity_days":     conn.execute("SELECT COUNT(DISTINCT date) FROM activity_snapshots").fetchone()[0],
        "persons_indexed":   conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0],
    }
    conn.close()
    return result


# ── Documents ─────────────────────────────────────────────────────────────────

@app.get("/documents")
def list_documents(limit: int = 100, offset: int = 0):
    """List indexed documents with basic metadata."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, title, mime_type, owner_email, modified_at, web_url
        FROM documents ORDER BY modified_at DESC LIMIT ? OFFSET ?
    """, (limit, offset)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/documents/{doc_id}")
def get_document(doc_id: str,
                 recent_days: int = 7,
                 prior_days: int = 7):
    """Full detail for a single document — metadata, links, activity, contributors."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    doc = dict(row)
    doc["url"] = doc_url(doc_id, doc.get("web_url") or "", doc.get("mime_type") or "")

    # Inbound links
    doc["inbound_links"] = [
        {"src_id": r["src_id"],
         "title": conn.execute("SELECT title FROM documents WHERE id=?", (r["src_id"],)).fetchone()["title"]
                  if conn.execute("SELECT title FROM documents WHERE id=?", (r["src_id"],)).fetchone() else None}
        for r in conn.execute("SELECT src_id FROM doc_links WHERE dst_id=?", (doc_id,)).fetchall()
    ]

    # Outbound links
    doc["outbound_links"] = [
        {"dst_id": r["dst_id"],
         "title": conn.execute("SELECT title FROM documents WHERE id=?", (r["dst_id"],)).fetchone()["title"]
                  if conn.execute("SELECT title FROM documents WHERE id=?", (r["dst_id"],)).fetchone() else None}
        for r in conn.execute("SELECT src_id, dst_id FROM doc_links WHERE src_id=?", (doc_id,)).fetchall()
    ]

    # Activity history
    doc["activity_history"] = [
        dict(r) for r in conn.execute("""
            SELECT date, views, edits, comments
            FROM activity_snapshots WHERE document_id=? ORDER BY date
        """, (doc_id,)).fetchall()
    ]

    # Contributors
    doc["contributors"] = [
        {"person_id": r["person_id"],
         "display_name": r["display_name"],
         "email": r["email"],
         "action": r["action"],
         "count": r["count"],
         "last_seen": r["last_seen"]}
        for r in conn.execute("""
            SELECT pa.person_id, p.display_name, p.email, pa.action, pa.count, pa.last_seen
            FROM person_activity pa
            LEFT JOIN persons p ON pa.person_id = p.id
            WHERE pa.document_id=?
            ORDER BY pa.count DESC
        """, (doc_id,)).fetchall()
    ]

    # External links
    doc["external_links"] = [
        {"domain": r["domain"], "apex_domain": r["apex_domain"],
         "url": r["url"], "anchor_text": r["anchor_text"]}
        for r in conn.execute("""
            SELECT er.domain, er.apex_domain, er.url, el.anchor_text
            FROM external_links el
            JOIN external_resources er ON el.resource_id = er.id
            WHERE el.src_id=?
        """, (doc_id,)).fetchall()
    ]

    conn.close()
    return doc


# ── Analytics ─────────────────────────────────────────────────────────────────

@app.get("/analytics/rising")
def analytics_rising(recent_days: int = 7, prior_days: int = 7, limit: int = 20):
    """Documents gaining activity — sorted by absolute gain."""
    conn = get_conn()
    titles   = title_map(conn)
    mimes    = {r["id"]: r["mime_type"] or "" for r in conn.execute("SELECT id, mime_type FROM documents")}
    web_urls = {r["id"]: r["web_url"] or "" for r in conn.execute("SELECT id, web_url FROM documents")}
    activity = activity_by_doc(conn, days_recent=recent_days, days_prior=prior_days)
    conn.close()

    results = []
    for doc_id, gain, recent, prior in rising_docs(activity, titles, top_n=limit):
        results.append({
            "id": doc_id,
            "title": titles.get(doc_id),
            "url": doc_url(doc_id, web_urls.get(doc_id, ""), mimes.get(doc_id, "")),
            "recent_activity": recent,
            "prior_activity": prior,
            "gain": gain,
        })
    return results


@app.get("/analytics/stale")
def analytics_stale(limit: int = 20):
    """Documents that have gone quiet after being active or having inbound links."""
    conn = get_conn()
    titles   = title_map(conn)
    mimes    = {r["id"]: r["mime_type"] or "" for r in conn.execute("SELECT id, mime_type FROM documents")}
    web_urls = {r["id"]: r["web_url"] or "" for r in conn.execute("SELECT id, web_url FROM documents")}
    stale_act = stale_activity(conn)
    G = build_doc_graph(conn)
    in_deg = in_degree_rank(G)
    conn.close()

    results = []
    for doc_id, recent, hist_total, indeg, dropoff in stale_docs(stale_act, in_deg, titles, top_n=limit):
        results.append({
            "id": doc_id,
            "title": titles.get(doc_id),
            "url": doc_url(doc_id, web_urls.get(doc_id, ""), mimes.get(doc_id, "")),
            "recent_30d": recent,
            "history_total": hist_total,
            "history_daily_avg": stale_act[doc_id]["history_daily_avg"],
            "inbound_links": indeg,
            "dropoff_score": round(dropoff, 1),
        })
    return results


@app.get("/analytics/hubs")
def analytics_hubs(limit: int = 20):
    """Documents with the most inbound links from other documents."""
    conn = get_conn()
    titles   = title_map(conn)
    mimes    = {r["id"]: r["mime_type"] or "" for r in conn.execute("SELECT id, mime_type FROM documents")}
    web_urls = {r["id"]: r["web_url"] or "" for r in conn.execute("SELECT id, web_url FROM documents")}
    G = build_doc_graph(conn)
    conn.close()

    results = []
    for doc_id, deg in in_degree_rank(G):
        if deg == 0 or doc_id not in titles:
            continue
        results.append({
            "id": doc_id,
            "title": titles.get(doc_id),
            "url": doc_url(doc_id, web_urls.get(doc_id, ""), mimes.get(doc_id, "")),
            "inbound_links": deg,
        })
        if len(results) >= limit:
            break
    return results


@app.get("/analytics/needs-attention")
def analytics_needs_attention(recent_days: int = 7, prior_days: int = 7, limit: int = 30):
    """Prioritized list of documents that warrant a look, with severity and suggested action."""
    conn = get_conn()
    titles   = title_map(conn)
    mimes    = {r["id"]: r["mime_type"] or "" for r in conn.execute("SELECT id, mime_type FROM documents")}
    web_urls = {r["id"]: r["web_url"] or "" for r in conn.execute("SELECT id, web_url FROM documents")}
    activity  = activity_by_doc(conn, days_recent=recent_days, days_prior=prior_days)
    stale_act = stale_activity(conn)
    G = build_doc_graph(conn)
    in_deg = dict(in_degree_rank(G))
    conn.close()

    items = []
    seen  = set()

    for doc_id, deg in sorted(in_deg.items(), key=lambda x: x[1], reverse=True):
        if doc_id not in titles or deg == 0:
            continue
        if activity.get(doc_id, {}).get("recent", 0) == 0:
            score = direness_score("high", in_deg_count=deg)
            items.append({
                "id": doc_id, "title": titles[doc_id],
                "url": doc_url(doc_id, web_urls.get(doc_id,""), mimes.get(doc_id,"")),
                "score": score, "severity": severity_label(score),
                "signal": f"Stale hub — {deg} doc{'s' if deg!=1 else ''} link here",
                "action": "Review accuracy or add a deprecation notice",
            })
            seen.add(doc_id)

    from analytics import rising_docs as _rising
    for doc_id, gain, rec, pri in _rising(activity, titles, limit * 2):
        if doc_id in seen or doc_id not in titles: continue
        score = direness_score("medium", gain=gain)
        items.append({
            "id": doc_id, "title": titles[doc_id],
            "url": doc_url(doc_id, web_urls.get(doc_id,""), mimes.get(doc_id,"")),
            "score": score, "severity": severity_label(score),
            "signal": f"Rising — +{gain} activity ({pri}→{rec})",
            "action": "Good time to review, update, or link from an index doc",
        })
        seen.add(doc_id)

    for doc_id, recent, hist_total, indeg, dropoff in stale_docs(stale_act, list(in_deg.items()), titles, limit*2):
        if doc_id in seen or doc_id not in titles: continue
        score = direness_score("low", prior_act=hist_total)
        hist_avg = stale_act[doc_id]["history_daily_avg"]
        items.append({
            "id": doc_id, "title": titles[doc_id],
            "url": doc_url(doc_id, web_urls.get(doc_id,""), mimes.get(doc_id,"")),
            "score": score, "severity": severity_label(score),
            "signal": f"Went quiet — was {hist_avg:.1f}/day, now ≤{STALE_RECENT_MAX} in {STALE_WINDOW_DAYS}d",
            "action": "Archive, update, or leave as-is if complete",
        })
        seen.add(doc_id)

    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:limit]


# ── Graph ─────────────────────────────────────────────────────────────────────

@app.get("/graph")
def graph(min_inbound: int = 0, include_unindexed: bool = False):
    """Document graph as nodes + edges — ready for Cytoscape.js, D3, or vis.js."""
    conn = get_conn()
    titles   = title_map(conn)
    mimes    = {r["id"]: r["mime_type"] or "" for r in conn.execute("SELECT id, mime_type FROM documents")}
    web_urls = {r["id"]: r["web_url"] or "" for r in conn.execute("SELECT id, web_url FROM documents")}
    activity  = activity_by_doc(conn)
    stale_act = stale_activity(conn)
    G = build_doc_graph(conn)
    in_deg = dict(in_degree_rank(G))
    comms  = communities(G)
    conn.close()

    community_map = {}
    for i, cluster in enumerate(comms):
        for n in cluster:
            community_map[n] = i

    rising_ids   = {d for d, *_ in rising_docs(activity, titles, 9999)}
    stale_act_ids = set()
    stale_hub_ids = set()
    for doc_id, deg in in_deg.items():
        if deg > 0 and activity.get(doc_id, {}).get("recent", 0) == 0:
            stale_hub_ids.add(doc_id)
    for doc_id, *_ in stale_docs(stale_act, list(in_deg.items()), titles, 9999):
        stale_act_ids.add(doc_id)
    hub_ids = {n for n, d in in_deg.items() if d >= 2}

    def status(node_id):
        if node_id in stale_hub_ids: return "stale_hub"
        if node_id in rising_ids:    return "rising"
        if node_id in hub_ids:       return "hub"
        if node_id in stale_act_ids: return "stale"
        return "normal"

    nodes = []
    for node in G.nodes():
        is_known = node in titles
        if not include_unindexed and not is_known:
            continue
        deg = in_deg.get(node, 0)
        if deg < min_inbound:
            continue
        nodes.append({
            "id": node,
            "title": titles.get(node, "[unindexed]"),
            "url": doc_url(node, web_urls.get(node, ""), mimes.get(node, "")),
            "inbound_links": deg,
            "cluster": community_map.get(node, -1),
            "status": status(node),
            "indexed": is_known,
        })

    node_ids = {n["id"] for n in nodes}
    edges = [
        {"source": src, "target": dst}
        for src, dst in G.edges()
        if src in node_ids and dst in node_ids
    ]

    return {"nodes": nodes, "edges": edges}


# ── External links ────────────────────────────────────────────────────────────

@app.get("/external-links")
def external_links(group_by: str = "apex", limit: int = 50):
    """External link summary. group_by='apex' rolls up subdomains; 'domain' shows each."""
    conn = get_conn()
    col = "er.apex_domain" if group_by == "apex" else "er.domain"
    rows = conn.execute(f"""
        SELECT COALESCE(NULLIF({col},''), er.domain) as label, COUNT(*) as cnt
        FROM external_links el
        JOIN external_resources er ON el.resource_id = er.id
        WHERE er.domain != '' AND er.domain IS NOT NULL
        GROUP BY label ORDER BY cnt DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [{"domain": r["label"], "links": r["cnt"]} for r in rows]


@app.get("/clusters")
def clusters():
    """Document clusters with auto-generated labels."""
    import re
    conn = get_conn()
    titles = title_map(conn)
    G = build_doc_graph(conn)
    comms = communities(G)
    conn.close()

    STOPWORDS = {"the","a","an","and","or","of","in","to","for","on","at","by",
                 "with","from","is","it","its","this","that","as","are","was"}

    result = []
    for i, cluster in enumerate(sorted(comms, key=len, reverse=True)):
        words = []
        known = [titles[n] for n in cluster if n in titles]
        for t in known:
            for w in re.sub(r"[^\w\s]", " ", t).lower().split():
                if w not in STOPWORDS and len(w) > 2:
                    words.append(w)
        freq = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        top = sorted(freq, key=freq.get, reverse=True)[:3]
        result.append({
            "cluster_id": i,
            "label": " · ".join(top) if top else f"cluster-{i}",
            "total_docs": len(cluster),
            "indexed_docs": len(known),
            "sample_titles": known[:5],
        })
    return result
