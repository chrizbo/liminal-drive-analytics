"""FastAPI backend — exposes Liminal Drive Analytics data as JSON.

Designed so the Streamlit dashboard can be replaced with any frontend
(React, Observable, plain JS) without touching the data layer.

Run with:
    uvicorn src.api:app --reload

Or from the src/ directory:
    uvicorn api:app --reload
"""

import os
import json
import secrets
import sys
import threading
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
from db import connect, init
from demo_data import reset_demo_database
from graph import build_doc_graph, in_degree_rank, communities
from analytics import (
    activity_by_doc, stale_activity, title_map,
    rising_docs, stale_docs,
)
from utils import doc_url
from operations import (
    DISPOSITIONS, FINDING_STATUSES, SIGNAL_TYPES,
    detect_findings, generate_brief, get_brief, get_finding, latest_brief, list_findings,
    refresh_findings, update_review,
)
from sources import load_sources
import indexer
from indexer import run as run_indexer
import ontology as _ontology

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")
CONFIG_PATH = os.path.join(ROOT, "config.json")
active_database_path = ContextVar("active_database_path", default=None)
active_workspace = ContextVar("active_workspace", default=None)
indexing_jobs = {}
indexing_jobs_lock = threading.Lock()

app = FastAPI(
    title="Liminal Drive Analytics API",
    description="Graph-based analytics for Google Drive documents. https://github.com/chrizbo/liminal-drive-analytics",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get("DRIVE_ANALYTICS_CORS_ORIGINS", "*").split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


def available_workspaces():
    workspaces = [
        {"id": "demo", "name": "Demo product team", "kind": "demo", "database_path": db.DEMO_DB_PATH},
        {"id": "live", "name": "Live Drive", "kind": "live", "database_path": db.DB_PATH},
    ]
    for source in load_sources():
        path = source.get("database_path", "")
        if path and os.path.exists(path):
            workspaces.append({
                "id": f"shared:{source['id']}",
                "name": source.get("name") or source["id"],
                "kind": "shared",
                "database_path": path,
                "indexed_at": source.get("indexed_at"),
            })
    return workspaces


@app.middleware("http")
async def select_workspace(request: Request, call_next):
    workspace_id = request.query_params.get("workspace", "live")
    workspace = next((item for item in available_workspaces() if item["id"] == workspace_id), None)
    if not workspace:
        return FileResponse(os.path.join(WEB_DIR, "index.html"), status_code=404) if request.url.path == "/" else await call_next(request)
    if workspace["kind"] == "demo" and not os.path.exists(workspace["database_path"]):
        reset_demo_database(workspace["database_path"])
    token = active_database_path.set(workspace["database_path"])
    workspace_token = active_workspace.set(workspace)
    try:
        return await call_next(request)
    finally:
        active_workspace.reset(workspace_token)
        active_database_path.reset(token)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_conn():
    conn = connect(active_database_path.get() or db.DB_PATH)
    init(conn)
    return conn


def require_write_token(x_admin_token: Optional[str] = Header(default=None)):
    expected = os.environ.get("DRIVE_ANALYTICS_WRITE_TOKEN")
    if not expected:
        return
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Valid X-Admin-Token required")


class ReviewUpdate(BaseModel):
    status: Optional[str] = None
    disposition: Optional[str] = None
    reviewer: Optional[str] = None
    assignee: Optional[str] = None
    note: Optional[str] = None
    follow_up_date: Optional[str] = None


class FindingsRefreshRequest(BaseModel):
    recent_days: int = 7
    prior_days: int = 7


class BriefGenerateRequest(BaseModel):
    days: int = 7
    polish: bool = False
    model: Optional[str] = None


class IndexingStartRequest(BaseModel):
    days: int = 90
    expand: bool = True


class SettingsUpdate(BaseModel):
    path_significant_domains: list[str]
    openai_model: str = "gpt-5.4-mini"


def load_config():
    try:
        with open(CONFIG_PATH) as config_file:
            return json.load(config_file)
    except Exception:
        return {"path_significant_domains": [], "openai_model": "gpt-5.4-mini"}


@app.get("/workspaces")
def workspaces():
    return [
        {key: value for key, value in workspace.items() if key != "database_path"}
        for workspace in available_workspaces()
    ]


@app.get("/configuration")
def configuration():
    config = load_config()
    return {
        "write_token_required": bool(os.environ.get("DRIVE_ANALYTICS_WRITE_TOKEN")),
        "path_significant_domains": config.get("path_significant_domains", []),
        "openai_model": config.get("openai_model", "gpt-5.4-mini"),
    }


@app.patch("/configuration", dependencies=[Depends(require_write_token)])
def configuration_update(body: SettingsUpdate):
    domains = sorted({
        domain.strip().lower()
        for domain in body.path_significant_domains
        if domain.strip()
    })
    model = body.openai_model.strip() or "gpt-5.4-mini"
    config = load_config()
    config["path_significant_domains"] = domains
    config["openai_model"] = model
    with open(CONFIG_PATH, "w") as config_file:
        json.dump(config, config_file, indent=2)
    indexer.PATH_SIGNIFICANT = set(domains)
    return {
        "write_token_required": bool(os.environ.get("DRIVE_ANALYTICS_WRITE_TOKEN")),
        "path_significant_domains": domains,
        "openai_model": model,
    }


@app.get("/")
def web_app():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


def _public_job(job):
    return {key: value for key, value in job.items() if key not in {"thread"}}


def _update_indexing_job(job_id, values):
    with indexing_jobs_lock:
        job = indexing_jobs.get(job_id)
        if not job:
            return
        job.update(values)
        job["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_indexing_job(job_id, workspace, days, expand):
    try:
        def progress(event):
            _update_indexing_job(job_id, {
                "status": "running",
                "phase": event.get("phase"),
                "message": event.get("message"),
                "current": event.get("current"),
                "total": event.get("total"),
                "document_title": event.get("document_title"),
            })

        shared_drive = workspace["id"].split(":", 1)[1] if workspace["kind"] == "shared" else None
        result = run_indexer(days, False, expand, shared_drive, progress)
        _update_indexing_job(job_id, {
            "status": "completed", "phase": "complete", "progress": 100,
            "message": f"{workspace['name']} is up to date", "result": result,
            "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    except Exception as exc:
        _update_indexing_job(job_id, {
            "status": "failed", "phase": "failed", "message": str(exc),
            "error": str(exc), "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })


@app.get("/indexing/jobs/current")
def indexing_current():
    workspace = active_workspace.get()
    with indexing_jobs_lock:
        jobs = [job for job in indexing_jobs.values() if job["workspace_id"] == workspace["id"]]
        if not jobs:
            return {"status": "idle", "workspace_id": workspace["id"]}
        jobs.sort(key=lambda job: job["created_at"], reverse=True)
        return _public_job(jobs[0])


@app.get("/indexing/jobs/{job_id}")
def indexing_detail(job_id: str):
    with indexing_jobs_lock:
        job = indexing_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Indexing job not found")
        return _public_job(job)


@app.post("/indexing/jobs", dependencies=[Depends(require_write_token)])
def indexing_start(body: IndexingStartRequest):
    workspace = active_workspace.get()
    if workspace["kind"] == "demo":
        raise HTTPException(status_code=400, detail="Demo data cannot be indexed from Google Drive")
    if body.days < 1 or body.days > 3650:
        raise HTTPException(status_code=400, detail="days must be between 1 and 3650")
    with indexing_jobs_lock:
        existing = next((
            job for job in indexing_jobs.values()
            if job["workspace_id"] == workspace["id"] and job["status"] in {"queued", "running"}
        ), None)
        if existing:
            return _public_job(existing)
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        job = {
            "id": job_id, "workspace_id": workspace["id"], "workspace_name": workspace["name"],
            "status": "queued", "phase": "queued", "message": "Waiting to start",
            "current": None, "total": None, "days": body.days, "expand": body.expand,
            "created_at": now, "updated_at": now,
        }
        indexing_jobs[job_id] = job
    thread = threading.Thread(
        target=_run_indexing_job, args=(job_id, dict(workspace), body.days, body.expand),
        name=f"drive-index-{job_id[:8]}", daemon=True,
    )
    with indexing_jobs_lock:
        indexing_jobs[job_id]["thread"] = thread
    thread.start()
    return _public_job(job)


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
    items = detect_findings(conn, recent_days=recent_days, prior_days=prior_days)
    conn.close()
    items.sort(key=lambda x: x["score"], reverse=True)
    return [
        {
            "id": item["document_id"],
            "title": item["document_title"],
            "url": item["document_url"],
            "score": item["score"],
            "severity": item["severity"],
            "signal": item["signal"],
            "action": item["suggested_action"],
            "evidence": item["metrics"],
        }
        for item in items[:limit]
    ]


# ── Operational findings and briefs ──────────────────────────────────────────

@app.get("/findings")
def findings_list(status: Optional[str] = None,
                  active: Optional[bool] = None,
                  signal_type: Optional[str] = None,
                  assignee: Optional[str] = None,
                  severity: Optional[str] = None,
                  limit: int = 100):
    if status and status not in FINDING_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if signal_type and signal_type not in SIGNAL_TYPES:
        raise HTTPException(status_code=400, detail="Invalid signal_type")
    conn = get_conn()
    result = list_findings(conn, status, active, signal_type, assignee, severity, limit)
    conn.close()
    return result


@app.get("/findings/{finding_id}")
def finding_detail(finding_id: str):
    conn = get_conn()
    result = get_finding(conn, finding_id)
    conn.close()
    if not result:
        raise HTTPException(status_code=404, detail="Finding not found")
    return result


@app.patch("/findings/{finding_id}/review", dependencies=[Depends(require_write_token)])
def finding_review(finding_id: str, body: ReviewUpdate):
    values = body.model_dump(exclude_unset=True)
    if values.get("status") and values["status"] not in FINDING_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if values.get("disposition") and values["disposition"] not in DISPOSITIONS:
        raise HTTPException(status_code=400, detail="Invalid disposition")
    conn = get_conn()
    try:
        result = update_review(conn, finding_id, values)
    except ValueError as exc:
        conn.close()
        raise HTTPException(status_code=400, detail=str(exc))
    conn.close()
    if not result:
        raise HTTPException(status_code=404, detail="Finding not found")
    return result


@app.post("/findings/refresh", dependencies=[Depends(require_write_token)])
def findings_refresh(body: FindingsRefreshRequest):
    conn = get_conn()
    result = refresh_findings(conn, body.recent_days, body.prior_days)
    conn.close()
    return result


@app.get("/briefs/latest")
def brief_latest():
    conn = get_conn()
    result = latest_brief(conn)
    conn.close()
    if not result:
        raise HTTPException(status_code=404, detail="No briefs generated")
    return result


@app.get("/briefs/recommendations")
def brief_recommendations(person_id: Optional[str] = None, limit: int = 8):
    """Rising documents worth reading, personalized when attributed view data exists."""
    conn = get_conn()
    titles = title_map(conn)
    docs = {
        row["id"]: {
            "title": row["title"],
            "url": doc_url(row["id"], row["web_url"] or "", row["mime_type"] or ""),
        }
        for row in conn.execute("SELECT id, title, web_url, mime_type FROM documents")
    }
    activity = activity_by_doc(conn)
    rising = rising_docs(activity, titles, top_n=500)
    attributed_view_count = conn.execute(
        "SELECT COUNT(*) FROM person_activity WHERE action='view'"
    ).fetchone()[0]
    viewed_ids = set()
    person_view_count = 0
    if person_id:
        viewed_rows = conn.execute("""
                SELECT document_id, count FROM person_activity
                WHERE person_id=? AND action='view'
            """, (person_id,)).fetchall()
        viewed_ids = {row["document_id"] for row in viewed_rows}
        person_view_count = sum(row["count"] for row in viewed_rows)
    recommendations = []
    for document_id, gain, recent, prior in rising:
        if person_id and attributed_view_count and document_id in viewed_ids:
            continue
        document = docs.get(document_id)
        if not document:
            continue
        recommendations.append({
            "id": document_id,
            "title": document["title"],
            "url": document["url"],
            "gain": gain,
            "recent_activity": recent,
            "prior_activity": prior,
            "viewed_by_person": document_id in viewed_ids,
        })
        if len(recommendations) >= limit:
            break
    conn.close()
    return {
        "person_id": person_id,
        "personalized": bool(person_id and person_view_count),
        "attributed_view_events_available": bool(attributed_view_count),
        "recommendations": recommendations,
    }


@app.get("/people")
def people_list():
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.id, p.display_name, p.email,
               SUM(CASE WHEN pa.action='view' THEN pa.count ELSE 0 END) as attributed_views
        FROM persons p
        LEFT JOIN person_activity pa ON pa.person_id = p.id
        GROUP BY p.id
        ORDER BY COALESCE(NULLIF(p.display_name,''), NULLIF(p.email,''), p.id)
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/briefs/{brief_id}")
def brief_detail(brief_id: str):
    conn = get_conn()
    result = get_brief(conn, brief_id)
    conn.close()
    if not result:
        raise HTTPException(status_code=404, detail="Brief not found")
    return result


@app.post("/briefs/generate", dependencies=[Depends(require_write_token)])
def brief_generate(body: BriefGenerateRequest):
    conn = get_conn()
    refresh_findings(conn, recent_days=body.days, prior_days=body.days)
    model = body.model or load_config().get("openai_model", "gpt-5.4-mini")
    result = generate_brief(conn, days=body.days, polish=body.polish, model=model)
    conn.close()
    return result


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


@app.get("/ontology/terms")
def ontology_terms(doc_id: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT term, frequency, term_type FROM doc_terms WHERE doc_id = ? ORDER BY frequency DESC",
        (doc_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/ontology/alignment/{doc_id}")
def ontology_alignment(doc_id: str):
    conn = get_conn()
    titles = title_map(conn)
    rows = conn.execute(
        """SELECT src_id, dst_id, alignment_score, shared_terms, divergent_terms
           FROM doc_alignment WHERE src_id = ? OR dst_id = ?""",
        (doc_id, doc_id),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        direction = "outbound" if r["src_id"] == doc_id else "inbound"
        linked_id = r["dst_id"] if direction == "outbound" else r["src_id"]
        result.append({
            "linked_doc_id": linked_id,
            "linked_doc_title": titles.get(linked_id, linked_id),
            "direction": direction,
            "alignment_score": r["alignment_score"],
            "shared_terms": json.loads(r["shared_terms"] or "[]"),
            "divergent_terms": json.loads(r["divergent_terms"] or "[]"),
        })
    result.sort(key=lambda x: (x["alignment_score"] or 1.0))
    return result


@app.get("/ontology/drift")
def ontology_drift(threshold: float = 0.4):
    conn = get_conn()
    titles = title_map(conn)
    rows = conn.execute(
        """SELECT src_id, dst_id, alignment_score, divergent_terms
           FROM doc_alignment WHERE alignment_score IS NOT NULL AND alignment_score < ?
           ORDER BY alignment_score ASC""",
        (threshold,),
    ).fetchall()
    conn.close()
    return [
        {
            "src_id": r["src_id"],
            "src_title": titles.get(r["src_id"], r["src_id"]),
            "dst_id": r["dst_id"],
            "dst_title": titles.get(r["dst_id"], r["dst_id"]),
            "alignment_score": r["alignment_score"],
            "divergent_terms": json.loads(r["divergent_terms"] or "[]")[:10],
        }
        for r in rows
    ]


app.mount("/assets", StaticFiles(directory=WEB_DIR), name="web-assets")
