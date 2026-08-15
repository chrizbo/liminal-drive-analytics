"""Tests for the isolated fictional product-team demo workspace."""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from db import connect
from demo_data import apply_demo_activity_fixture, reset_demo_database
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


def test_apply_demo_activity_fixture_adds_review_signals(tmp_path):
    path = str(tmp_path / "fixture-folder.db")
    conn = connect(path)
    from db import init
    init(conn)
    for doc_id, title in (
        ("1n_dN06WZ3ZHSHzTNItDkt-Fl-tBjetfqajAAe6ttP2g", "PRD - Smart Drive Briefs"),
        ("1plfvPmfmLK717wcBeS9dd9ncKSWoGTPpHWiTGQF_Bp0", "Q3 roadmap planning notes"),
        ("1yz48ZoiVB4k93in0PdQNWJkKicNLNn69dZrm8LqJXU0", "Strategy hub - FY26 product direction"),
        ("1m0WQGtiADSXli2WdO8xgHWxN--3Qc4k4c-izUFcZpgI", "OKR hub - Q2 planning snapshot"),
        ("1SY2q3ZaccBwuzDsDNnaSGY3C4PrwdXz_Dy43x2_hJ6E", "Decision log"),
        ("1Xso_Qv_ZfprjFHYPXVfe3ugCCjTkuoszC4H1xP73SGg", "Beta launch checklist"),
        ("1qQ1D5PkoI9NRxIDTJ18EIlkRr8CTVwgZSipwIHQjyDM", "Experiment brief - source-aware answers"),
        ("1fmXWp1jNpHwKA8gB_Fnsmi50h3d0XmB8xcegy8WcY7g", "User research synthesis - PM workflows"),
        ("1eP2hIS7wgiy_ca5Ak2KEqPI36_Gu3UGF9btzIZ2SXAw", "Design handoff - brief cards"),
        ("1CPyTX7N76OkA_nHnjyVEbTSXl5M6cCWp1liBC95V_RQ", "Metrics readout - week 32"),
    ):
        conn.execute(
            "INSERT INTO documents (id, title, mime_type, created_at, modified_at, last_indexed_at) VALUES (?, ?, '', '', '', '')",
            (doc_id, title),
        )
    conn.commit()

    apply_demo_activity_fixture(conn)

    assert conn.execute("SELECT COUNT(*) FROM doc_links").fetchone()[0] >= 8
    assert conn.execute("SELECT COUNT(*) FROM activity_snapshots").fetchone()[0] >= 20
    from operations import refresh_findings
    refresh_findings(conn, now="2026-08-14T15:05:00Z")
    findings = list_findings(conn, active=True, limit=100)
    assert any(finding["signal_type"] == "stale_hub" for finding in findings)
    assert any(finding["score"] >= 5 for finding in findings)
    conn.close()
