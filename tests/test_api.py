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
    client = TestClient(api.app)
    result = client.get("/configuration").json()
    assert result["write_token_required"] is False
    assert "path_significant_domains" in result
    assert "openai_model" in result
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    assert client.get("/configuration").json()["write_token_required"] is True


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
    conn.execute("INSERT INTO doc_links VALUES ('source', 'hub', '', '')")
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
    conn.execute("INSERT INTO doc_links VALUES ('source', 'hub', '', '')")
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

    workspaces = client.get("/workspaces").json()
    assert [workspace["id"] for workspace in workspaces[:2]] == ["demo", "live"]


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


def test_indexing_job_reports_progress_and_completion(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "indexing.db"))
    monkeypatch.setenv("DRIVE_ANALYTICS_WRITE_TOKEN", "secret")
    api.indexing_jobs.clear()

    def fake_run(days, verbose, expand, shared_drive, progress):
        assert days == 30
        assert expand is False
        assert shared_drive is None
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
