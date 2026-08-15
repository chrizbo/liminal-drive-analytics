"""Contract tests for the product-team demo activity fixture."""

import json
from pathlib import Path


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "demo_activity.json"


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text())


def test_demo_activity_fixture_has_expected_product_corpus():
    fixture = load_fixture()
    titles = {doc["title"] for doc in fixture["documents"]}

    assert fixture["mode"] == "synthetic_demo_activity"
    assert len(fixture["documents"]) == 10
    assert "PRD - Smart Drive Briefs" in titles
    assert "Strategy hub - FY26 product direction" in titles
    assert "OKR hub - Q2 planning snapshot" in titles


def test_demo_activity_fixture_flags_stale_hubs():
    fixture = load_fixture()
    docs_by_title = {doc["title"]: doc for doc in fixture["documents"]}
    stale_titles = set(fixture["expected_deterministic_labels"]["stale_or_superseded_sources"])
    activity_by_doc = {
        snapshot["document_id"]: snapshot
        for snapshot in fixture["activity_snapshots"]
        if snapshot["date"] == "2026-08-14"
    }

    assert stale_titles == {
        "Strategy hub - FY26 product direction",
        "OKR hub - Q2 planning snapshot",
    }
    assert all(docs_by_title[title]["source_role"] == "stale_or_superseded_context" for title in stale_titles)
    assert all(docs_by_title[title]["status"] in {"stale", "possibly_stale"} for title in stale_titles)
    for title in stale_titles:
        doc_id = docs_by_title[title]["id"]
        snapshot = activity_by_doc[doc_id]
        assert snapshot["views"] + snapshot["edits"] + snapshot["comments"] == 0


def test_demo_activity_fixture_has_activity_comments_and_eval_prompts():
    fixture = load_fixture()
    doc_ids = {doc["id"] for doc in fixture["documents"]}

    assert len(fixture["activity_snapshots"]) >= 20
    assert len(fixture["person_activity"]) >= 5
    assert len(fixture["comments"]) >= 3
    assert len(fixture["llm_eval_prompts"]) >= 3
    assert all(snapshot["document_id"] in doc_ids for snapshot in fixture["activity_snapshots"])
    assert all(comment["document_id"] in doc_ids for comment in fixture["comments"])
    assert any("Google Drive activity cannot be backfilled" in note for note in fixture["notes"])
