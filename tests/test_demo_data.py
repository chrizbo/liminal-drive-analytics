"""Tests for the isolated fictional product-team demo workspace."""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from db import connect
from demo_data import reset_demo_database
from operations import latest_brief, list_findings


def test_demo_database_contains_product_story(tmp_path):
    path = str(tmp_path / "demo.db")
    reset_demo_database(path, now=datetime(2026, 6, 8, tzinfo=timezone.utc))
    conn = connect(path)
    titles = {row["title"] for row in conn.execute("SELECT title FROM documents")}
    assert "Orbit Mobile Launch Plan" in titles
    assert "Product Metrics Dictionary" in titles
    assert conn.execute("SELECT COUNT(*) FROM doc_links").fetchone()[0] >= 25
    assert conn.execute("SELECT COUNT(*) FROM external_links").fetchone()[0] >= 5
    assert conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0] >= 5
    conn.close()


def test_demo_database_has_findings_reviews_and_brief(tmp_path):
    path = str(tmp_path / "demo.db")
    reset_demo_database(path, now=datetime(2026, 6, 8, tzinfo=timezone.utc))
    conn = connect(path)
    findings = list_findings(conn, active=True, limit=100)
    signal_types = {finding["signal_type"] for finding in findings}
    assert {"stale_hub", "rising", "went_quiet"} <= signal_types
    assert any(finding["status"] == "resolved" for finding in findings)
    assert latest_brief(conn) is not None
    conn.close()


def test_reset_demo_database_replaces_previous_content(tmp_path):
    path = str(tmp_path / "demo.db")
    now = datetime(2026, 6, 8, tzinfo=timezone.utc)
    reset_demo_database(path, now=now)
    conn = connect(path)
    conn.execute("""
        INSERT INTO documents (id, title, mime_type, created_at, modified_at, last_indexed_at)
        VALUES ('intruder', 'Should disappear', '', '', '', '')
    """)
    conn.commit()
    conn.close()
    reset_demo_database(path, now=now)
    conn = connect(path)
    assert conn.execute("SELECT COUNT(*) FROM documents WHERE id='intruder'").fetchone()[0] == 0
    conn.close()
