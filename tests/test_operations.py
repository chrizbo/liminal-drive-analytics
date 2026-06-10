"""Tests for persistent operational findings, reviews, and leader briefs."""

import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import db
from operations import (
    generate_brief, get_finding, list_findings, polish_brief,
    refresh_findings, update_review,
)


@pytest.fixture
def operational_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "operations.db"))
    conn = db.connect()
    db.init(conn)
    for doc_id, title in (("source", "Source Doc"), ("hub", "Hub Doc")):
        conn.execute("""
            INSERT INTO documents (
                id, title, mime_type, created_at, modified_at, last_indexed_at, web_url
            ) VALUES (?, ?, 'application/vnd.google-apps.document', '', '', '', ?)
        """, (doc_id, title, f"https://docs.google.com/document/d/{doc_id}"))
    conn.execute(
        "INSERT INTO doc_links (src_id, dst_id, first_seen, last_seen) VALUES ('source','hub','','')"
    )
    conn.commit()
    yield conn
    conn.close()


def test_refresh_is_idempotent_and_recurrence_creates_new_finding(operational_db):
    first = refresh_findings(operational_db, now="2026-06-01T00:00:00Z")
    assert first["created"] == 1
    original = list_findings(operational_db, active=True)[0]

    second = refresh_findings(operational_db, now="2026-06-02T00:00:00Z")
    assert second["created"] == 0
    assert second["updated"] == 1

    operational_db.execute("DELETE FROM doc_links")
    operational_db.commit()
    removed = refresh_findings(operational_db, now="2026-06-03T00:00:00Z")
    assert removed["deactivated"] == 1

    operational_db.execute(
        "INSERT INTO doc_links (src_id, dst_id, first_seen, last_seen) VALUES ('source','hub','','')"
    )
    operational_db.commit()
    recurrence = refresh_findings(operational_db, now="2026-06-04T00:00:00Z")
    assert recurrence["created"] == 1
    active = list_findings(operational_db, active=True)[0]
    assert active["id"] != original["id"]


def test_review_updates_state_and_records_history(operational_db):
    refresh_findings(operational_db)
    finding = list_findings(operational_db, active=True)[0]
    result = update_review(operational_db, finding["id"], {
        "status": "resolved",
        "disposition": "update_needed",
        "reviewer": "Ops Lead",
        "assignee": "Doc Owner",
        "note": "Owner confirmed an update is underway.",
        "follow_up_date": "2026-06-15",
    }, now="2026-06-07T12:00:00Z")
    assert result["status"] == "resolved"
    assert result["reviewed_at"] == "2026-06-07T12:00:00Z"
    assert result["review_history"][0]["reviewer"] == "Ops Lead"


def test_generate_brief_persists_evidence_references(operational_db):
    refresh_findings(operational_db)
    brief = generate_brief(
        operational_db, days=7,
        now=datetime(2026, 6, 7, tzinfo=timezone.utc),
    )
    claims = brief["deterministic"]["sections"]["knowledge_risks"]
    assert claims
    assert claims[0]["evidence_ids"]


class FakeResponse:
    def __init__(self, output_text):
        self.output_text = output_text


class FakeResponses:
    def __init__(self, output_text):
        self.output_text = output_text

    def create(self, **kwargs):
        return FakeResponse(self.output_text)


class FakeClient:
    def __init__(self, output_text):
        self.responses = FakeResponses(output_text)


def test_polish_brief_accepts_only_preserved_evidence():
    original = {
        "sections": {
            "what_changed": [{"text": "Original", "evidence_ids": ["finding-1"]}],
            "follow_ups": [], "knowledge_risks": [], "recently_reviewed": [],
        }
    }
    valid = json.loads(json.dumps(original))
    valid["sections"]["what_changed"][0]["text"] = "Clearer"
    assert polish_brief(original, FakeClient(json.dumps(valid))) == valid

    invalid = json.loads(json.dumps(valid))
    invalid["sections"]["what_changed"][0]["evidence_ids"] = ["invented"]
    assert polish_brief(original, FakeClient(json.dumps(invalid))) is None


def test_polish_brief_without_configuration_falls_back(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert polish_brief({"sections": {}}) is None
