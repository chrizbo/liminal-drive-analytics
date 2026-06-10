"""FastAPI security and operational endpoint tests."""

import os
import sys

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
