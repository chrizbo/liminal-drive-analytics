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
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
from db import connect, connect_service_database, init
from storage import (
    active_indexing_job_row, attributed_view_count, document_lookup_maps,
    crawl_schedule_row, from_workspace, indexing_job_row, insert_indexing_job,
    delete_indexed_workspace_data, external_link_summary, get_document_detail,
    google_connection_row, insert_analytics_event, list_people,
    latest_indexing_job_row, list_workspace_documents,
    ontology_alignment_rows, ontology_drift_rows,
    ontology_terms as list_ontology_terms, overview_counts,
    person_viewed_document_ids,
    update_indexing_job, upsert_crawl_schedule, upsert_google_connection,
)
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
active_tenant = ContextVar("active_tenant", default=None)
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
        {
            "id": "demo", "name": "Synthetic product team", "kind": "demo",
            "database_path": db.DEMO_DB_PATH, "tenant_id": db.DEMO_TENANT_ID,
            "tenant_name": "Demo tenant", "tenant_kind": "demo",
        },
        {
            "id": "live", "name": "Live Drive", "kind": "live",
            "database_path": db.DB_PATH, "tenant_id": db.LOCAL_TENANT_ID,
            "tenant_name": "Local development", "tenant_kind": "local",
        },
    ]
    for source in load_sources():
        path = source.get("database_path", "")
        if path and os.path.exists(path):
            kind = source.get("kind") or "shared"
            name = source.get("name") or source["id"]
            if kind == "folder" and name.lower() == "demo":
                name = "Demo folder"
            workspaces.append({
                "id": f"shared:{source['id']}",
                "name": name,
                "kind": kind,
                "database_path": path,
                "tenant_id": db.LOCAL_TENANT_ID,
                "tenant_name": "Local development",
                "tenant_kind": "local",
                "source_id": source["id"],
                "indexed_at": source.get("indexed_at"),
            })
    return workspaces


@app.middleware("http")
async def select_workspace(request: Request, call_next):
    workspace_id = request.query_params.get("workspace", "live")
    requested_tenant_id = request.query_params.get("tenant")
    workspace = next((item for item in available_workspaces() if item["id"] == workspace_id), None)
    if not workspace:
        return FileResponse(os.path.join(WEB_DIR, "index.html"), status_code=404) if request.url.path == "/" else await call_next(request)
    if requested_tenant_id and requested_tenant_id != workspace["tenant_id"]:
        return JSONResponse(
            {"detail": "Workspace does not belong to requested tenant"},
            status_code=403,
        )
    if workspace["kind"] == "demo" and not os.path.exists(workspace["database_path"]):
        reset_demo_database(workspace["database_path"])
    token = active_database_path.set(workspace["database_path"])
    workspace_token = active_workspace.set(workspace)
    tenant_token = active_tenant.set({
        "id": workspace["tenant_id"],
        "name": workspace.get("tenant_name") or workspace["tenant_id"],
        "kind": workspace.get("tenant_kind") or "local",
    })
    try:
        return await call_next(request)
    finally:
        active_tenant.reset(tenant_token)
        active_workspace.reset(workspace_token)
        active_database_path.reset(token)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_conn():
    workspace = active_workspace.get()
    if db.service_database_url() and workspace and workspace["kind"] != "demo":
        conn = connect_service_database()
    else:
        conn = connect(active_database_path.get() or db.DB_PATH)
    init(conn)
    if workspace:
        db.ensure_service_context(conn, workspace)
        db.stamp_workspace_rows(conn, workspace["tenant_id"], workspace["id"])
    return conn


def current_scope():
    return from_workspace(active_workspace.get())


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


class CrawlScheduleUpdate(BaseModel):
    enabled: bool = False
    schedule_cron: str = "0 3 * * *"
    schedule_timezone: str = "UTC"
    crawl_mode: str = "incremental"


class AnalyticsEventCreate(BaseModel):
    event_type: str
    finding_id: Optional[str] = None
    document_id: Optional[str] = None
    metadata: dict = {}


class GoogleConnectionUpdate(BaseModel):
    account_email: Optional[str] = None
    granted_scopes: list[str] = []


def load_config():
    try:
        with open(CONFIG_PATH) as config_file:
            return json.load(config_file)
    except Exception:
        return {"path_significant_domains": [], "openai_model": "gpt-5.4-mini"}


@app.get("/workspaces")
def workspaces():
    return [_public_workspace(workspace) for workspace in available_workspaces()]


@app.get("/tenants")
def tenants():
    seen = {}
    for workspace in available_workspaces():
        seen[workspace["tenant_id"]] = {
            "id": workspace["tenant_id"],
            "name": workspace.get("tenant_name") or workspace["tenant_id"],
            "kind": workspace.get("tenant_kind") or "local",
        }
    return list(seen.values())


@app.get("/context")
def context():
    workspace = active_workspace.get()
    tenant = active_tenant.get()
    return {
        "tenant": tenant,
        "workspace": _public_workspace(workspace),
    }


@app.get("/configuration")
def configuration():
    config = load_config()
    return {
        "write_token_required": bool(os.environ.get("DRIVE_ANALYTICS_WRITE_TOKEN")),
        "database_backend": "postgresql" if db.service_database_url() else "sqlite",
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
        "database_backend": "postgresql" if db.service_database_url() else "sqlite",
        "path_significant_domains": domains,
        "openai_model": model,
    }


@app.get("/crawl-schedule")
def crawl_schedule():
    workspace = active_workspace.get()
    conn = get_conn()
    try:
        schedule = crawl_schedule_row(conn, current_scope())
    finally:
        conn.close()
    return _public_crawl_schedule(schedule, workspace)


@app.patch("/crawl-schedule", dependencies=[Depends(require_write_token)])
def crawl_schedule_update(body: CrawlScheduleUpdate):
    workspace = active_workspace.get()
    if workspace["kind"] == "demo":
        raise HTTPException(status_code=400, detail="Demo data cannot be scheduled for Drive crawling")
    if body.crawl_mode not in {"incremental", "activity_refresh", "link_expansion", "backfill"}:
        raise HTTPException(status_code=400, detail="Invalid crawl_mode")
    if len(body.schedule_cron.split()) != 5:
        raise HTTPException(status_code=400, detail="schedule_cron must have five fields")

    now = _utc_now()
    next_run_at = _next_scheduled_run(body.enabled, body.schedule_cron)
    conn = get_conn()
    try:
        existing = crawl_schedule_row(conn, current_scope())
        upsert_crawl_schedule(conn, {
            "id": existing["id"] if existing else str(uuid.uuid4()),
            "enabled": body.enabled,
            "schedule_cron": body.schedule_cron,
            "schedule_timezone": body.schedule_timezone,
            "crawl_mode": body.crawl_mode,
            "next_run_at": next_run_at,
            "paused_at": None if body.enabled else now,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }, current_scope())
        db.update_workspace_crawl_state(conn, workspace["tenant_id"], workspace["id"], {
            "next_scheduled_crawl_at": next_run_at,
            "crawl_mode": body.crawl_mode,
            "crawl_health": "healthy" if body.enabled else "paused",
        })
        schedule = crawl_schedule_row(conn, current_scope())
    finally:
        conn.close()
    return _public_crawl_schedule(schedule, workspace)


@app.post("/events")
def events_create(body: AnalyticsEventCreate):
    if body.event_type not in {"finding_opened", "doc_opened"}:
        raise HTTPException(status_code=400, detail="Invalid event_type")
    conn = get_conn()
    try:
        insert_analytics_event(conn, {
            "id": str(uuid.uuid4()),
            "event_type": body.event_type,
            "finding_id": body.finding_id,
            "document_id": body.document_id,
            "metadata": body.metadata or {},
            "created_at": _utc_now(),
        }, current_scope())
    finally:
        conn.close()
    return {"recorded": True}


def _public_google_connection(row, workspace=None):
    if not row:
        return {
            "workspace_id": workspace["id"] if workspace else None,
            "provider": "google",
            "status": "disconnected",
            "account_email": None,
            "granted_scopes": [],
            "connected_at": None,
            "disconnected_at": None,
            "health": "disconnected",
            "error": None,
        }
    return row


@app.get("/google-connection")
def google_connection():
    workspace = active_workspace.get()
    conn = get_conn()
    try:
        connection = google_connection_row(conn, current_scope())
    finally:
        conn.close()
    return _public_google_connection(connection, workspace)


@app.post("/google-connection/disconnect", dependencies=[Depends(require_write_token)])
def google_connection_disconnect():
    workspace = active_workspace.get()
    if workspace["kind"] == "demo":
        raise HTTPException(status_code=400, detail="Demo data is not connected to Google Drive")
    now = _utc_now()
    conn = get_conn()
    try:
        existing = google_connection_row(conn, current_scope())
        upsert_google_connection(conn, {
            "id": existing["id"] if existing else str(uuid.uuid4()),
            "account_email": existing.get("account_email") if existing else None,
            "status": "disconnected",
            "granted_scopes": [],
            "token_encrypted": None,
            "token_version": None,
            "connected_at": existing.get("connected_at") if existing else None,
            "disconnected_at": now,
            "last_checked_at": now,
            "health": "disconnected",
            "error": None,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }, current_scope())
        schedule = crawl_schedule_row(conn, current_scope())
        if schedule:
            upsert_crawl_schedule(conn, {
                "id": schedule["id"],
                "enabled": False,
                "schedule_cron": schedule["schedule_cron"],
                "schedule_timezone": schedule["schedule_timezone"],
                "crawl_mode": schedule["crawl_mode"],
                "next_run_at": None,
                "paused_at": now,
                "created_at": schedule["created_at"],
                "updated_at": now,
            }, current_scope())
        db.update_workspace_crawl_state(conn, workspace["tenant_id"], workspace["id"], {
            "next_scheduled_crawl_at": None,
            "crawl_health": "paused",
            "failure_reason": "Google Drive disconnected",
        })
        connection = google_connection_row(conn, current_scope())
    finally:
        conn.close()
    return _public_google_connection(connection, workspace)


@app.delete("/workspace-data", dependencies=[Depends(require_write_token)])
def workspace_data_delete():
    workspace = active_workspace.get()
    if workspace["kind"] == "demo":
        raise HTTPException(status_code=400, detail="Demo data cannot be deleted from Settings")
    conn = get_conn()
    try:
        deleted = delete_indexed_workspace_data(conn, current_scope())
        db.update_workspace_crawl_state(conn, workspace["tenant_id"], workspace["id"], {
            "indexed_at": None,
            "last_successful_crawl_at": None,
            "last_attempted_crawl_at": None,
            "crawl_cursor": None,
            "crawl_health": "action_required",
            "failure_reason": "Indexed workspace data deleted",
        })
    finally:
        conn.close()
    return {"deleted": deleted}


@app.get("/")
def web_app():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _public_job(job):
    return {key: value for key, value in job.items() if key not in {"thread"}}


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_scheduled_run(enabled, schedule_cron):
    if not enabled:
        return None
    parts = schedule_cron.split()
    now = datetime.now(timezone.utc)
    if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit():
        minute = max(0, min(59, int(parts[0])))
        hour = max(0, min(23, int(parts[1])))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if parts[4] != "*" and parts[4].isdigit():
            target = int(parts[4]) % 7
            days_until = (target - candidate.weekday()) % 7
            candidate = candidate + timedelta(days=days_until)
        if candidate <= now:
            candidate = candidate + timedelta(days=7 if parts[4] != "*" else 1)
        return candidate.strftime("%Y-%m-%dT%H:%M:%SZ")
    return (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _public_crawl_schedule(row, workspace=None):
    if not row:
        return {
            "workspace_id": workspace["id"] if workspace else None,
            "enabled": False,
            "schedule_cron": "0 3 * * *",
            "schedule_timezone": "UTC",
            "crawl_mode": "incremental",
            "next_run_at": None,
            "paused_at": None,
        }
    payload = dict(row)
    payload["enabled"] = bool(payload["enabled"])
    return payload


def _open_workspace_conn(workspace):
    if workspace["kind"] == "demo" and not os.path.exists(workspace["database_path"]):
        reset_demo_database(workspace["database_path"])
    if db.service_database_url() and workspace["kind"] != "demo":
        conn = connect_service_database()
    else:
        conn = connect(workspace.get("database_path") or db.DB_PATH)
    init(conn)
    db.ensure_service_context(conn, workspace)
    return conn


def _public_workspace(workspace):
    payload = {key: value for key, value in workspace.items() if key != "database_path"}
    try:
        conn = _open_workspace_conn(workspace)
        try:
            payload.update(db.workspace_state(conn, workspace["tenant_id"], workspace["id"]))
        finally:
            conn.close()
    except Exception as exc:
        payload.setdefault("crawl_health", "unknown")
        payload.setdefault("failure_reason", str(exc))
    return payload


def _persist_indexing_job_update(job_id, workspace, values):
    conn = _open_workspace_conn(workspace)
    try:
        scope = from_workspace(workspace)
        update_indexing_job(conn, job_id, values, scope)
    finally:
        conn.close()


def _update_indexing_job(job_id, values, workspace=None):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    values = {**values, "updated_at": now}
    with indexing_jobs_lock:
        job = indexing_jobs.get(job_id)
        if job:
            job.update(values)
    if workspace:
        _persist_indexing_job_update(job_id, workspace, values)


def _persist_workspace_crawl_state(workspace, values):
    conn = _open_workspace_conn(workspace)
    try:
        db.update_workspace_crawl_state(conn, workspace["tenant_id"], workspace["id"], values)
    finally:
        conn.close()


def _has_live_indexing_thread(job_id):
    with indexing_jobs_lock:
        job = indexing_jobs.get(job_id)
        if not job:
            return False
        thread = job.get("thread")
        if not thread:
            return job.get("status") in {"queued", "running"}
        return thread.is_alive()


def _reconcile_orphaned_indexing_job(conn, workspace, job, scope):
    if not job or job.get("status") not in {"queued", "running"}:
        return job
    if _has_live_indexing_thread(job["id"]):
        return job
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    values = {
        "status": "failed",
        "phase": "failed",
        "message": "Indexing was interrupted before completion",
        "error": "No active worker is attached to this job",
        "updated_at": now,
        "completed_at": now,
    }
    update_indexing_job(conn, job["id"], values, scope)
    with indexing_jobs_lock:
        memory_job = indexing_jobs.get(job["id"])
        if memory_job:
            memory_job.update(values)
    return {**job, **values}


def _run_indexing_job(job_id, workspace, days, expand):
    conn = None
    try:
        attempted_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _persist_workspace_crawl_state(workspace, {
            "last_attempted_crawl_at": attempted_at,
            "crawl_mode": "manual",
            "failure_reason": None,
        })

        def progress(event):
            _update_indexing_job(job_id, {
                "status": "running",
                "phase": event.get("phase"),
                "message": event.get("message"),
                "current": event.get("current"),
                "total": event.get("total"),
                "document_title": event.get("document_title"),
            }, workspace)

        source_id = workspace["id"].split(":", 1)[1] if workspace["id"].startswith("shared:") else None
        shared_drive = source_id if workspace["kind"] in {"shared", "shared_drive"} else None
        folder = source_id if workspace["kind"] == "folder" else None
        scope = from_workspace(workspace)
        run_kwargs = {
            "shared_drive": shared_drive,
            "folder": folder,
            "progress": progress,
            "scope": scope,
            "database_path": workspace.get("database_path"),
        }
        if db.service_database_url() and workspace["kind"] != "demo":
            conn = connect_service_database()
            init(conn)
            db.ensure_service_context(conn, workspace)
            db.stamp_workspace_rows(conn, workspace["tenant_id"], workspace["id"])
            run_kwargs["conn"] = conn
        result = run_indexer(days, False, expand, **run_kwargs)
        _update_indexing_job(job_id, {
            "status": "completed", "phase": "complete", "progress": 100,
            "message": f"{workspace['name']} is up to date", "result": result,
            "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }, workspace)
        completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _persist_workspace_crawl_state(workspace, {
            "indexed_at": completed_at,
            "last_successful_crawl_at": completed_at,
            "crawl_health": "healthy",
            "failure_reason": None,
        })
    except Exception as exc:
        completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _update_indexing_job(job_id, {
            "status": "failed", "phase": "failed", "message": str(exc),
            "error": str(exc), "completed_at": completed_at,
        }, workspace)
        _persist_workspace_crawl_state(workspace, {
            "crawl_health": "degraded",
            "failure_reason": str(exc),
        })
    finally:
        if conn:
            conn.close()


@app.get("/indexing/jobs/current")
def indexing_current():
    workspace = active_workspace.get()
    conn = get_conn()
    try:
        job = latest_indexing_job_row(conn, current_scope())
        job = _reconcile_orphaned_indexing_job(conn, workspace, job, current_scope())
    finally:
        conn.close()
    if not job:
        return {"status": "idle", "workspace_id": workspace["id"]}
    return _public_job(job)


@app.get("/indexing/jobs/{job_id}")
def indexing_detail(job_id: str):
    workspace = active_workspace.get()
    conn = get_conn()
    try:
        job = indexing_job_row(conn, job_id, current_scope())
        job = _reconcile_orphaned_indexing_job(conn, workspace, job, current_scope())
    finally:
        conn.close()
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
    conn = get_conn()
    try:
        existing = active_indexing_job_row(conn, current_scope())
        existing = _reconcile_orphaned_indexing_job(conn, workspace, existing, current_scope())
        if existing and existing.get("status") not in {"queued", "running"}:
            existing = None
        if existing:
            return _public_job(existing)
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        job = {
            "id": job_id, "workspace_id": workspace["id"], "workspace_name": workspace["name"],
            "status": "queued", "phase": "queued", "message": "Waiting to start",
            "current": None, "total": None, "progress": None, "document_title": None,
            "days": body.days, "expand": body.expand,
            "created_at": now, "updated_at": now,
        }
        insert_indexing_job(conn, job, current_scope())
    finally:
        conn.close()
    with indexing_jobs_lock:
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
    result = overview_counts(conn, current_scope())
    conn.close()
    return result


# ── Documents ─────────────────────────────────────────────────────────────────

@app.get("/documents")
def list_documents(limit: int = 100, offset: int = 0):
    """List indexed documents with basic metadata."""
    conn = get_conn()
    result = list_workspace_documents(conn, current_scope(), limit, offset)
    conn.close()
    return result


@app.get("/documents/{doc_id}")
def get_document(doc_id: str,
                 recent_days: int = 7,
                 prior_days: int = 7):
    """Full detail for a single document — metadata, links, activity, contributors."""
    conn = get_conn()
    doc = get_document_detail(conn, doc_id, current_scope())
    conn.close()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


# ── Analytics ─────────────────────────────────────────────────────────────────

@app.get("/analytics/rising")
def analytics_rising(recent_days: int = 7, prior_days: int = 7, limit: int = 20):
    """Documents gaining activity — sorted by absolute gain."""
    conn = get_conn()
    scope = current_scope()
    titles, mimes, web_urls = document_lookup_maps(conn, scope)
    activity = activity_by_doc(conn, days_recent=recent_days, days_prior=prior_days, scope=scope)
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
    scope = current_scope()
    titles, mimes, web_urls = document_lookup_maps(conn, scope)
    stale_act = stale_activity(conn, scope=scope)
    G = build_doc_graph(conn, scope)
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
    scope = current_scope()
    titles, mimes, web_urls = document_lookup_maps(conn, scope)
    G = build_doc_graph(conn, scope)
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
    items = detect_findings(conn, recent_days=recent_days, prior_days=prior_days, scope=current_scope())
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
    result = list_findings(conn, status, active, signal_type, assignee, severity, limit, scope=current_scope())
    conn.close()
    return result


@app.get("/findings/{finding_id}")
def finding_detail(finding_id: str):
    conn = get_conn()
    result = get_finding(conn, finding_id, scope=current_scope())
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
        result = update_review(conn, finding_id, values, scope=current_scope())
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
    result = refresh_findings(conn, body.recent_days, body.prior_days, scope=current_scope())
    conn.close()
    return result


@app.get("/briefs/latest")
def brief_latest():
    conn = get_conn()
    result = latest_brief(conn, scope=current_scope())
    conn.close()
    if not result:
        raise HTTPException(status_code=404, detail="No briefs generated")
    return result


@app.get("/briefs/recommendations")
def brief_recommendations(person_id: Optional[str] = None, limit: int = 8):
    """Rising documents worth reading, personalized when attributed view data exists."""
    conn = get_conn()
    scope = current_scope()
    titles, mimes, web_urls = document_lookup_maps(conn, scope)
    docs = {
        doc_id: {
            "title": title,
            "url": doc_url(doc_id, web_urls.get(doc_id, ""), mimes.get(doc_id, "")),
        }
        for doc_id, title in titles.items()
    }
    activity = activity_by_doc(conn, scope=scope)
    rising = rising_docs(activity, titles, top_n=500)
    view_count = attributed_view_count(conn, scope)
    viewed_ids = set()
    person_view_count = 0
    if person_id:
        viewed_ids, person_view_count = person_viewed_document_ids(conn, person_id, scope)
    recommendations = []
    for document_id, gain, recent, prior in rising:
        if person_id and view_count and document_id in viewed_ids:
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
        "attributed_view_events_available": bool(view_count),
        "recommendations": recommendations,
    }


@app.get("/people")
def people_list():
    conn = get_conn()
    rows = list_people(conn, current_scope())
    conn.close()
    return rows


@app.get("/briefs/{brief_id}")
def brief_detail(brief_id: str):
    conn = get_conn()
    result = get_brief(conn, brief_id, scope=current_scope())
    conn.close()
    if not result:
        raise HTTPException(status_code=404, detail="Brief not found")
    return result


@app.post("/briefs/generate", dependencies=[Depends(require_write_token)])
def brief_generate(body: BriefGenerateRequest):
    conn = get_conn()
    scope = current_scope()
    refresh_findings(conn, recent_days=body.days, prior_days=body.days, scope=scope)
    model = body.model or load_config().get("openai_model", "gpt-5.4-mini")
    result = generate_brief(conn, days=body.days, polish=body.polish, model=model, scope=scope)
    conn.close()
    return result


# ── Graph ─────────────────────────────────────────────────────────────────────

@app.get("/graph")
def graph(min_inbound: int = 0, include_unindexed: bool = False):
    """Document graph as nodes + edges — ready for Cytoscape.js, D3, or vis.js."""
    conn = get_conn()
    scope = current_scope()
    titles, mimes, web_urls = document_lookup_maps(conn, scope)
    activity  = activity_by_doc(conn, scope=scope)
    stale_act = stale_activity(conn, scope=scope)
    G = build_doc_graph(conn, scope)
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
    rows = external_link_summary(conn, current_scope(), group_by, limit)
    conn.close()
    return rows


@app.get("/clusters")
def clusters():
    """Document clusters with auto-generated labels."""
    import re
    conn = get_conn()
    scope = current_scope()
    titles = title_map(conn, scope)
    G = build_doc_graph(conn, scope)
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
    rows = list_ontology_terms(conn, doc_id, current_scope())
    conn.close()
    return rows


@app.get("/ontology/alignment/{doc_id}")
def ontology_alignment(doc_id: str):
    conn = get_conn()
    scope = current_scope()
    titles = title_map(conn, scope)
    rows = ontology_alignment_rows(conn, doc_id, scope)
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
    scope = current_scope()
    titles = title_map(conn, scope)
    rows = ontology_drift_rows(conn, threshold, scope)
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
