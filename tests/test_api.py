"""FastAPI security and operational endpoint tests."""

import os
import sys
import time
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import db
import api


def test_write_endpoints_require_admin_token(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    client = TestClient(api.app)

    denied = client.post("/findings/refresh", json={"recent_days": 7, "prior_days": 7})
    assert denied.status_code == 401

    allowed = client.post(
        "/findings/refresh",
        json={"recent_days": 7, "prior_days": 7},
        headers={"X-Admin-Token": "secret"},
    )
    assert allowed.status_code == 200
    assert allowed.json() == {"created": 0, "updated": 0, "deactivated": 0}


def test_write_endpoints_allow_local_use_without_configured_token(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "api-local.db"))
    monkeypatch.delenv("DRIVE_ANALYTICS_WRITE_TOKEN", raising=False)
    response = TestClient(api.app).post(
        "/findings/refresh",
        json={"recent_days": 7, "prior_days": 7},
    )
    assert response.status_code == 200


def test_configuration_reports_write_token_requirement(monkeypatch):
    monkeypatch.delenv("DRIVE_ANALYTICS_WRITE_TOKEN", raising=False)
    monkeypatch.delenv(db.DATABASE_URL_ENV, raising=False)
    client = TestClient(api.app)
    result = client.get("/configuration").json()
    assert result["write_token_required"] is False
    assert result["database_backend"] == "sqlite"
    assert "path_significant_domains" in result
    assert "openai_model" in result
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    assert client.get("/configuration").json()["write_token_required"] is True


def test_configuration_reports_postgres_backend(monkeypatch):
    monkeypatch.setenv(db.DATABASE_URL_ENV, "postgresql://localhost/drive_analytics")
    result = TestClient(api.app).get("/configuration").json()
    assert result["database_backend"] == "postgresql"


def test_configuration_update_persists_settings(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(api, "CONFIG_PATH", str(config_path))
    monkeypatch.delenv("DRIVE_ANALYTICS_WRITE_TOKEN", raising=False)
    response = TestClient(api.app).patch("/configuration", json={
        "openai_model": "gpt-test",
        "path_significant_domains": ["Example.com", "github.com", "example.com"],
    })
    assert response.status_code == 200
    assert response.json()["openai_model"] == "gpt-test"
    assert response.json()["path_significant_domains"] == ["example.com", "github.com"]


def test_findings_reads_are_unauthenticated(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "api-read.db"))
    client = TestClient(api.app)
    response = client.get("/findings")
    assert response.status_code == 200
    assert response.json() == []


def test_existing_needs_attention_shape_is_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "api-compat.db"))
    conn = db.connect()
    db.init(conn)
    for doc_id in ("source", "hub"):
        conn.execute("""
            INSERT INTO documents (
                id, title, mime_type, created_at, modified_at, last_indexed_at, web_url
            ) VALUES (?, ?, '', '', '', '', '')
        """, (doc_id, doc_id.title()))
    conn.execute("""
        INSERT INTO doc_links (src_id, dst_id, first_seen, last_seen)
        VALUES ('source', 'hub', '', '')
    """)
    conn.commit()
    conn.close()

    response = TestClient(api.app).get("/analytics/needs-attention")
    assert response.status_code == 200
    item = response.json()[0]
    assert {"id", "title", "url", "signal", "action", "evidence"} <= set(item)


def test_review_endpoint_persists_update(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "api-review.db"))
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    conn = db.connect()
    db.init(conn)
    conn.execute("""
        INSERT INTO documents (
            id, title, mime_type, created_at, modified_at, last_indexed_at, web_url
        ) VALUES ('source', 'Source', '', '', '', '', '')
    """)
    conn.execute("""
        INSERT INTO documents (
            id, title, mime_type, created_at, modified_at, last_indexed_at, web_url
        ) VALUES ('hub', 'Hub', '', '', '', '', '')
    """)
    conn.execute("""
        INSERT INTO doc_links (src_id, dst_id, first_seen, last_seen)
        VALUES ('source', 'hub', '', '')
    """)
    conn.commit()
    from operations import refresh_findings
    refresh_findings(conn)
    finding_id = conn.execute("SELECT id FROM findings WHERE active=1").fetchone()["id"]
    conn.close()

    client = TestClient(api.app)
    response = client.patch(
        f"/findings/{finding_id}/review",
        json={"status": "in_review", "reviewer": "Ops Lead", "disposition": "monitor"},
        headers={"X-Admin-Token": "secret"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "in_review"
    assert response.json()["review_history"][0]["reviewer"] == "Ops Lead"


def test_web_app_and_workspace_list_are_served():
    client = TestClient(api.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Liminal Drive Analytics" in response.text

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"ok": True}

    workspaces = client.get("/workspaces").json()
    assert [workspace["id"] for workspace in workspaces[:2]] == ["demo", "live"]
    assert workspaces[0]["name"] == "Synthetic product team"
    assert workspaces[0]["tenant_id"] == db.DEMO_TENANT_ID
    assert workspaces[1]["tenant_id"] == db.LOCAL_TENANT_ID


def test_tenant_and_workspace_context_are_exposed(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "context.db"))
    client = TestClient(api.app)

    tenants = client.get("/tenants").json()
    assert {tenant["id"] for tenant in tenants} >= {db.DEMO_TENANT_ID, db.LOCAL_TENANT_ID}

    context = client.get("/context?workspace=live").json()
    assert context["tenant"]["id"] == db.LOCAL_TENANT_ID
    assert context["workspace"]["id"] == "live"


def test_context_exposes_workspace_crawl_state(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "context-crawl.db"))
    conn = db.connect()
    db.init(conn)
    db.ensure_service_context(conn, {
        "id": "live",
        "tenant_id": db.LOCAL_TENANT_ID,
        "tenant_name": "Local development",
        "tenant_kind": "local",
        "name": "Live Drive",
        "kind": "live",
        "database_path": db.DB_PATH,
    })
    db.update_workspace_crawl_state(conn, db.LOCAL_TENANT_ID, "live", {
        "last_successful_crawl_at": "2026-08-15T01:01:00Z",
        "last_attempted_crawl_at": "2026-08-15T01:00:00Z",
        "crawl_mode": "manual",
        "crawl_health": "healthy",
    })
    conn.close()

    context = TestClient(api.app).get("/context?workspace=live").json()

    assert context["workspace"]["last_successful_crawl_at"] == "2026-08-15T01:01:00Z"
    assert context["workspace"]["last_attempted_crawl_at"] == "2026-08-15T01:00:00Z"
    assert context["workspace"]["crawl_mode"] == "manual"
    assert context["workspace"]["crawl_health"] == "healthy"
    assert "database_path" not in context["workspace"]


def test_workspace_rejects_explicit_wrong_tenant(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "tenant-a.db"))
    client = TestClient(api.app)
    response = client.get(f"/overview?workspace=live&tenant={db.DEMO_TENANT_ID}")
    assert response.status_code == 403
    assert "Workspace does not belong" in response.json()["detail"]


def test_workspace_accepts_explicit_matching_tenant(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "tenant-match.db"))
    client = TestClient(api.app)
    response = client.get(f"/overview?workspace=live&tenant={db.LOCAL_TENANT_ID}")
    assert response.status_code == 200
    assert response.json()["documents_indexed"] == 0


def test_shared_database_workspaces_are_tenant_scoped(monkeypatch, tmp_path):
    database_path = str(tmp_path / "shared-tenants.db")
    workspaces = [
        {
            "id": "workspace-a", "name": "Workspace A", "kind": "live",
            "database_path": database_path, "tenant_id": "tenant-a",
            "tenant_name": "Tenant A", "tenant_kind": "test",
        },
        {
            "id": "workspace-b", "name": "Workspace B", "kind": "live",
            "database_path": database_path, "tenant_id": "tenant-b",
            "tenant_name": "Tenant B", "tenant_kind": "test",
        },
    ]
    monkeypatch.setattr(api, "available_workspaces", lambda: workspaces)
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")

    conn = db.connect(database_path)
    db.init(conn)
    for workspace in workspaces:
        db.ensure_service_context(conn, workspace)
    conn.execute("""
        INSERT INTO documents (id, tenant_id, workspace_id, title, modified_at)
        VALUES ('doc-a', 'tenant-a', 'workspace-a', 'Doc A', '2026-01-01')
    """)
    conn.execute("""
        INSERT INTO documents (id, tenant_id, workspace_id, title, modified_at)
        VALUES ('doc-b', 'tenant-b', 'workspace-b', 'Doc B', '2026-01-01')
    """)
    for finding_id, tenant_id, workspace_id, doc_id in (
        ("finding-a", "tenant-a", "workspace-a", "doc-a"),
        ("finding-b", "tenant-b", "workspace-b", "doc-b"),
    ):
        conn.execute("""
            INSERT INTO findings (
                id, tenant_id, workspace_id, document_id, signal_type, score, severity,
                suggested_action, evidence_json, first_detected_at, last_detected_at,
                active, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'rising', 5, 'medium', 'Review',
                '{"document_id":"x"}', '2026-01-01', '2026-01-01', 1, 'new',
                '2026-01-01', '2026-01-01')
        """, (finding_id, tenant_id, workspace_id, doc_id))
    conn.commit()
    conn.close()

    client = TestClient(api.app)
    docs_a = client.get("/documents?workspace=workspace-a").json()
    docs_b = client.get("/documents?workspace=workspace-b").json()
    assert [doc["id"] for doc in docs_a] == ["doc-a"]
    assert [doc["id"] for doc in docs_b] == ["doc-b"]

    findings_a = client.get("/findings?workspace=workspace-a").json()
    findings_b = client.get("/findings?workspace=workspace-b").json()
    assert [finding["id"] for finding in findings_a] == ["finding-a"]
    assert [finding["id"] for finding in findings_b] == ["finding-b"]

    cross_tenant_update = client.patch(
        "/findings/finding-a/review?workspace=workspace-b",
        json={"status": "resolved"},
        headers={"X-Admin-Token": "secret"},
    )
    assert cross_tenant_update.status_code == 404


def test_workspace_query_selects_demo_database(monkeypatch, tmp_path):
    live_path = tmp_path / "live.db"
    demo_path = tmp_path / "demo.db"
    monkeypatch.setattr(db, "DB_PATH", str(live_path))
    monkeypatch.setattr(db, "DEMO_DB_PATH", str(demo_path))

    for path, title in ((live_path, "Live document"), (demo_path, "Demo document")):
        conn = db.connect(str(path))
        db.init(conn)
        conn.execute("INSERT INTO documents (id, title) VALUES (?, ?)", (title, title))
        conn.commit()
        conn.close()

    client = TestClient(api.app)
    assert client.get("/overview?workspace=live").json()["documents_indexed"] == 1
    assert client.get("/documents?workspace=demo").json()[0]["title"] == "Demo document"


def test_demo_workspace_cannot_start_indexing(monkeypatch):
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    response = TestClient(api.app).post(
        "/indexing/jobs?workspace=demo",
        json={"days": 90, "expand": True},
        headers={"X-Admin-Token": "secret"},
    )
    assert response.status_code == 400
    assert "Demo data" in response.json()["detail"]


def test_crawl_schedule_defaults_and_updates(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "schedule.db"))
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    client = TestClient(api.app)

    default = client.get("/crawl-schedule?workspace=live").json()
    assert default["enabled"] is False
    assert default["schedule_cron"] == "0 3 * * *"
    assert default["crawl_mode"] == "incremental"

    updated = client.patch(
        "/crawl-schedule?workspace=live",
        headers={"X-Admin-Token": "secret"},
        json={
            "enabled": True,
            "schedule_cron": "15 4 * * *",
            "schedule_timezone": "America/Los_Angeles",
            "crawl_mode": "activity_refresh",
        },
    )
    assert updated.status_code == 200
    schedule = updated.json()
    assert schedule["enabled"] is True
    assert schedule["schedule_cron"] == "15 4 * * *"
    assert schedule["schedule_timezone"] == "America/Los_Angeles"
    assert schedule["crawl_mode"] == "activity_refresh"
    assert schedule["next_run_at"]

    context = client.get("/context?workspace=live").json()
    assert context["workspace"]["next_scheduled_crawl_at"] == schedule["next_run_at"]
    assert context["workspace"]["crawl_mode"] == "activity_refresh"
    assert context["workspace"]["crawl_health"] == "healthy"


def test_events_are_recorded_with_workspace_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "events.db"))
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    client = TestClient(api.app)

    response = client.post("/events?workspace=live", json={
        "event_type": "finding_opened",
        "finding_id": "finding-1",
        "document_id": "doc-1",
        "metadata": {"source": "doc_audit"},
    })

    assert response.status_code == 200
    assert response.json() == {"recorded": True}
    conn = db.connect()
    event = conn.execute("SELECT * FROM analytics_events").fetchone()
    conn.close()
    assert event["tenant_id"] == db.LOCAL_TENANT_ID
    assert event["workspace_id"] == "live"
    assert event["event_type"] == "finding_opened"
    assert event["finding_id"] == "finding-1"
    assert event["document_id"] == "doc-1"
    assert '"source": "doc_audit"' in event["metadata_json"]


def test_demo_workspace_cannot_update_crawl_schedule(monkeypatch):
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    response = TestClient(api.app).patch(
        "/crawl-schedule?workspace=demo",
        headers={"X-Admin-Token": "secret"},
        json={"enabled": True, "schedule_cron": "0 3 * * *", "schedule_timezone": "UTC", "crawl_mode": "incremental"},
    )
    assert response.status_code == 400
    assert "Demo data" in response.json()["detail"]


def test_disconnect_pauses_schedule_and_crawl_health(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "disconnect.db"))
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    client = TestClient(api.app)
    client.patch(
        "/crawl-schedule?workspace=live",
        headers={"X-Admin-Token": "secret"},
        json={
            "enabled": True,
            "schedule_cron": "0 3 * * *",
            "schedule_timezone": "UTC",
            "crawl_mode": "incremental",
        },
    )

    response = client.post(
        "/google-connection/disconnect?workspace=live",
        headers={"X-Admin-Token": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"
    schedule = client.get("/crawl-schedule?workspace=live").json()
    assert schedule["enabled"] is False
    assert schedule["next_run_at"] is None
    assert schedule["paused_at"]
    context = client.get("/context?workspace=live").json()
    assert context["workspace"]["crawl_health"] == "paused"
    assert context["workspace"]["failure_reason"] == "Google Drive disconnected"


def test_delete_workspace_data_removes_indexed_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "delete-data.db"))
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    conn = db.connect()
    db.init(conn)
    db.ensure_service_context(conn, {
        "id": "live",
        "tenant_id": db.LOCAL_TENANT_ID,
        "tenant_name": "Local development",
        "tenant_kind": "local",
        "name": "Live Drive",
        "kind": "live",
        "database_path": db.DB_PATH,
    })
    conn.execute("""
        INSERT INTO documents (id, tenant_id, workspace_id, title, modified_at)
        VALUES ('doc-1', ?, 'live', 'Doc 1', '2026-01-01')
    """, (db.LOCAL_TENANT_ID,))
    conn.execute("""
        INSERT INTO activity_snapshots (tenant_id, workspace_id, document_id, date, views, edits, comments)
        VALUES (?, 'live', 'doc-1', '2026-01-01', 1, 0, 0)
    """, (db.LOCAL_TENANT_ID,))
    conn.execute("""
        INSERT INTO findings (
            id, tenant_id, workspace_id, document_id, signal_type, score, severity,
            suggested_action, evidence_json, first_detected_at, last_detected_at,
            active, status, created_at, updated_at
        ) VALUES ('finding-1', ?, 'live', 'doc-1', 'rising', 5, 'medium',
            'Review', '{}', '2026-01-01', '2026-01-01', 1, 'new',
            '2026-01-01', '2026-01-01')
    """, (db.LOCAL_TENANT_ID,))
    conn.commit()
    conn.close()

    response = TestClient(api.app).delete(
        "/workspace-data?workspace=live",
        headers={"X-Admin-Token": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["deleted"]["documents"] == 1
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM activity_snapshots").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 0
    workspace = conn.execute("SELECT * FROM workspaces WHERE id='live'").fetchone()
    conn.close()
    assert workspace["crawl_health"] == "action_required"
    assert workspace["failure_reason"] == "Indexed workspace data deleted"


def test_indexing_job_reports_progress_and_completion(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "indexing.db"))
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    api.indexing_jobs.clear()

    def fake_run(
        days, verbose, expand, shared_drive=None, folder=None,
        progress=None, scope=None, database_path=None, conn=None,
    ):
        assert days == 30
        assert expand is False
        assert shared_drive is None
        assert folder is None
        assert scope.tenant_id == db.LOCAL_TENANT_ID
        assert scope.workspace_id == "live"
        assert conn is None
        progress({"phase": "indexing", "message": "Indexing Example", "current": 1, "total": 2})
        return {"source": "Drive", "files_found": 2, "findings": {}}

    monkeypatch.setattr(api, "run_indexer", fake_run)
    client = TestClient(api.app)
    started = client.post(
        "/indexing/jobs?workspace=live",
        json={"days": 30, "expand": False},
        headers={"X-Admin-Token": "secret"},
    )
    assert started.status_code == 200
    job_id = started.json()["id"]

    result = None
    for _ in range(20):
        result = client.get(f"/indexing/jobs/{job_id}?workspace=live").json()
        if result["status"] == "completed":
            break
        time.sleep(0.01)
    assert result["status"] == "completed"
    assert result["result"]["files_found"] == 2
    conn = db.connect()
    workspace = conn.execute("SELECT * FROM workspaces WHERE id='live'").fetchone()
    conn.close()
    assert workspace["last_attempted_crawl_at"]
    assert workspace["last_successful_crawl_at"]
    assert workspace["indexed_at"] == workspace["last_successful_crawl_at"]
    assert workspace["crawl_mode"] == "manual"
    assert workspace["crawl_health"] == "healthy"
    assert workspace["failure_reason"] is None
    live_workspace = next(
        workspace for workspace in client.get("/workspaces").json()
        if workspace["id"] == "live"
    )
    assert live_workspace["last_successful_crawl_at"] == workspace["last_successful_crawl_at"]
    assert live_workspace["crawl_health"] == "healthy"


def test_indexing_job_status_survives_memory_clear(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "durable-indexing.db"))
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    api.indexing_jobs.clear()

    def fake_run(
        days, verbose, expand, shared_drive=None, folder=None,
        progress=None, scope=None, database_path=None, conn=None,
    ):
        progress({"phase": "indexing", "message": "Indexing Example", "current": 1, "total": 1})
        return {"source": "Drive", "files_found": 1, "findings": {"created": 0}}

    monkeypatch.setattr(api, "run_indexer", fake_run)
    client = TestClient(api.app)
    started = client.post(
        "/indexing/jobs?workspace=live",
        json={"days": 30, "expand": False},
        headers={"X-Admin-Token": "secret"},
    )
    assert started.status_code == 200
    job_id = started.json()["id"]
    for _ in range(20):
        result = client.get(f"/indexing/jobs/{job_id}?workspace=live").json()
        if result["status"] == "completed":
            break
        time.sleep(0.01)

    api.indexing_jobs.clear()

    detail = client.get(f"/indexing/jobs/{job_id}?workspace=live").json()
    current = client.get("/indexing/jobs/current?workspace=live").json()
    assert detail["status"] == "completed"
    assert detail["result"]["files_found"] == 1
    assert current["id"] == job_id


def test_orphaned_active_indexing_job_does_not_block_restart(monkeypatch, tmp_path):
    from storage import StorageScope, insert_indexing_job

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "orphaned-indexing.db"))
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    api.indexing_jobs.clear()

    conn = db.connect()
    db.init(conn)
    db.ensure_service_context(conn, {
        "id": "live",
        "tenant_id": db.LOCAL_TENANT_ID,
        "tenant_name": "Local development",
        "tenant_kind": "local",
        "name": "Live Drive",
        "kind": "live",
        "database_path": db.DB_PATH,
    })
    insert_indexing_job(conn, {
        "id": "orphaned-job",
        "workspace_id": "live",
        "workspace_name": "Live Drive",
        "status": "running",
        "phase": "indexing",
        "message": "Indexing when the process stopped",
        "current": 1,
        "total": 10,
        "progress": None,
        "document_title": "Interrupted doc",
        "days": 30,
        "expand": False,
        "created_at": "2026-08-15T00:00:00Z",
        "updated_at": "2026-08-15T00:00:00Z",
    }, StorageScope(db.LOCAL_TENANT_ID, "live"))
    conn.close()

    def fake_run(
        days, verbose, expand, shared_drive=None, folder=None,
        progress=None, scope=None, database_path=None, conn=None,
    ):
        return {"source": "Drive", "files_found": 1, "findings": {}}

    monkeypatch.setattr(api, "run_indexer", fake_run)
    client = TestClient(api.app)

    orphaned = client.get("/indexing/jobs/orphaned-job?workspace=live").json()
    assert orphaned["status"] == "failed"
    assert "interrupted" in orphaned["message"]

    started = client.post(
        "/indexing/jobs?workspace=live",
        json={"days": 30, "expand": False},
        headers={"X-Admin-Token": "secret"},
    )
    assert started.status_code == 200
    assert started.json()["id"] != "orphaned-job"


def test_failed_indexing_job_marks_workspace_degraded(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "failed-indexing.db"))
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    api.indexing_jobs.clear()

    def fake_run(
        days, verbose, expand, shared_drive=None, folder=None,
        progress=None, scope=None, database_path=None, conn=None,
    ):
        raise RuntimeError("Drive quota exhausted")

    monkeypatch.setattr(api, "run_indexer", fake_run)
    client = TestClient(api.app)
    started = client.post(
        "/indexing/jobs?workspace=live",
        json={"days": 30, "expand": False},
        headers={"X-Admin-Token": "secret"},
    )
    assert started.status_code == 200
    job_id = started.json()["id"]
    for _ in range(20):
        result = client.get(f"/indexing/jobs/{job_id}?workspace=live").json()
        if result["status"] == "failed":
            break
        time.sleep(0.01)

    assert result["status"] == "failed"
    assert result["error"] == "Drive quota exhausted"
    conn = db.connect()
    workspace = conn.execute("SELECT * FROM workspaces WHERE id='live'").fetchone()
    conn.close()
    assert workspace["last_attempted_crawl_at"]
    assert workspace["last_successful_crawl_at"] is None
    assert workspace["crawl_health"] == "degraded"
    assert workspace["failure_reason"] == "Drive quota exhausted"


def test_folder_indexing_job_passes_folder_source(monkeypatch, tmp_path):
    folder_database_path = str(tmp_path / "folder.db")
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    monkeypatch.setattr(api, "available_workspaces", lambda: [{
        "id": "shared:folder-1",
        "name": "Demo folder",
        "kind": "folder",
        "database_path": folder_database_path,
        "tenant_id": db.LOCAL_TENANT_ID,
        "tenant_name": "Local development",
        "tenant_kind": "local",
    }])
    api.indexing_jobs.clear()

    def fake_run(
        days, verbose, expand, shared_drive=None, folder=None,
        progress=None, scope=None, database_path=None, conn=None,
    ):
        assert shared_drive is None
        assert folder == "folder-1"
        assert scope.tenant_id == db.LOCAL_TENANT_ID
        assert scope.workspace_id == "shared:folder-1"
        assert database_path == folder_database_path
        assert conn is None
        progress({"phase": "indexing", "message": "Indexing Folder", "current": 1, "total": 1})
        return {"source": "Folder", "files_found": 1, "findings": {}}

    monkeypatch.setattr(api, "run_indexer", fake_run)
    client = TestClient(api.app)
    started = client.post(
        "/indexing/jobs?workspace=shared:folder-1",
        json={"days": 30, "expand": True},
        headers={"X-Admin-Token": "secret"},
    )
    assert started.status_code == 200
    job_id = started.json()["id"]

    result = None
    for _ in range(20):
        result = client.get(f"/indexing/jobs/{job_id}?workspace=shared:folder-1").json()
        if result["status"] == "completed":
            break
        time.sleep(0.01)
    assert result["status"] == "completed"
    assert result["result"]["files_found"] == 1


def test_shared_drive_indexing_job_passes_shared_drive_source(monkeypatch, tmp_path):
    shared_database_path = str(tmp_path / "shared.db")
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    monkeypatch.setattr(api, "available_workspaces", lambda: [{
        "id": "shared:drive-1",
        "name": "Product Drive",
        "kind": "shared_drive",
        "database_path": shared_database_path,
        "tenant_id": db.LOCAL_TENANT_ID,
        "tenant_name": "Local development",
        "tenant_kind": "local",
    }])
    api.indexing_jobs.clear()

    def fake_run(
        days, verbose, expand, shared_drive=None, folder=None,
        progress=None, scope=None, database_path=None, conn=None,
    ):
        assert shared_drive == "drive-1"
        assert folder is None
        assert scope.tenant_id == db.LOCAL_TENANT_ID
        assert scope.workspace_id == "shared:drive-1"
        assert database_path == shared_database_path
        assert conn is None
        progress({"phase": "indexing", "message": "Indexing Shared Drive", "current": 1, "total": 1})
        return {"source": "Shared Drive", "files_found": 1, "findings": {}}

    monkeypatch.setattr(api, "run_indexer", fake_run)
    client = TestClient(api.app)
    started = client.post(
        "/indexing/jobs?workspace=shared:drive-1",
        json={"days": 30, "expand": True},
        headers={"X-Admin-Token": "secret"},
    )
    assert started.status_code == 200
    job_id = started.json()["id"]

    result = None
    for _ in range(20):
        result = client.get(f"/indexing/jobs/{job_id}?workspace=shared:drive-1").json()
        if result["status"] == "completed":
            break
        time.sleep(0.01)
    assert result["status"] == "completed"
    assert result["result"]["files_found"] == 1


def test_indexing_job_uses_service_database_connection_when_configured(monkeypatch, tmp_path):
    class FakeServiceConnection:
        dialect = "postgresql"

        def __init__(self):
            self.statements = []
            self.closed = False

        def execute(self, sql, params=()):
            self.statements.append((sql, params))

        def commit(self):
            pass

        def close(self):
            self.closed = True

    workspace = {
        "id": "shared:folder-1",
        "name": "Demo folder",
        "kind": "folder",
        "database_path": str(tmp_path / "folder.db"),
        "tenant_id": db.LOCAL_TENANT_ID,
        "tenant_name": "Local development",
        "tenant_kind": "local",
    }
    conn = FakeServiceConnection()
    monkeypatch.setenv(db.DATABASE_URL_ENV, "postgresql://localhost/drive_analytics")
    monkeypatch.setattr(api, "connect_service_database", lambda: conn)
    api.indexing_jobs.clear()

    def fake_run(
        days, verbose, expand, shared_drive=None, folder=None,
        progress=None, scope=None, database_path=None, conn=None,
    ):
        assert conn is not None
        assert conn.dialect == "postgresql"
        assert scope.tenant_id == db.LOCAL_TENANT_ID
        assert scope.workspace_id == "shared:folder-1"
        assert database_path == workspace["database_path"]
        progress({"phase": "indexing", "message": "Indexing hosted folder", "current": 1, "total": 1})
        return {"source": "Folder", "files_found": 1, "findings": {}}

    monkeypatch.setattr(api, "run_indexer", fake_run)
    job_id = "job-hosted"
    api.indexing_jobs[job_id] = {
        "id": job_id,
        "workspace_id": workspace["id"],
        "workspace_name": workspace["name"],
        "status": "queued",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }

    api._run_indexing_job(job_id, workspace, 30, True)

    job = api.indexing_jobs[job_id]
    assert job["status"] == "completed"
    assert conn.closed is True
    assert any(statement.startswith("CREATE TABLE") for statement, _ in conn.statements)
    assert any("INSERT INTO workspaces" in statement for statement, _ in conn.statements)


def test_brief_recommendations_exclude_docs_viewed_by_selected_person(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "recommendations.db"))
    conn = db.connect()
    db.init(conn)
    today = datetime.now(timezone.utc).date()
    for doc_id, title in (("seen", "Seen rising doc"), ("unseen", "Unseen rising doc")):
        conn.execute("""
            INSERT INTO documents (id, title, mime_type, web_url)
            VALUES (?, ?, 'application/vnd.google-apps.document', ?)
        """, (doc_id, title, f"https://docs.google.com/document/d/{doc_id}"))
        conn.execute("""
            INSERT INTO activity_snapshots (document_id, date, views, edits, comments)
            VALUES (?, ?, 10, 0, 0)
        """, (doc_id, today.isoformat()))
        conn.execute("""
            INSERT INTO activity_snapshots (document_id, date, views, edits, comments)
            VALUES (?, ?, 1, 0, 0)
        """, (doc_id, (today - timedelta(days=10)).isoformat()))
    conn.execute("INSERT INTO persons (id, email, display_name) VALUES ('person-1','','Reader')")
    conn.execute("""
        INSERT INTO person_activity (person_id, document_id, action, last_seen, count)
        VALUES ('person-1', 'seen', 'view', '', 1)
    """)
    conn.commit()
    conn.close()

    response = TestClient(api.app).get(
        "/briefs/recommendations?workspace=live&person_id=person-1"
    )
    assert response.status_code == 200
    result = response.json()
    assert result["personalized"] is True
    assert [doc["id"] for doc in result["recommendations"]] == ["unseen"]
