"""Create a realistic fictional product-team dataset for dashboard demos."""

import argparse
import os
from datetime import datetime, timezone, timedelta

from db import DEMO_DB_PATH, connect, init
from operations import generate_brief, list_findings, refresh_findings, update_review


DOC_MIME = "application/vnd.google-apps.document"
SLIDE_MIME = "application/vnd.google-apps.presentation"

PEOPLE = [
    ("person-maya", "maya@northstar.example", "Maya Chen"),
    ("person-devon", "devon@northstar.example", "Devon Brooks"),
    ("person-priya", "priya@northstar.example", "Priya Raman"),
    ("person-luis", "luis@northstar.example", "Luis Ortega"),
    ("person-elena", "elena@northstar.example", "Elena Park"),
    ("person-sam", "sam@northstar.example", "Sam Okafor"),
]

DOCUMENTS = [
    ("product-strategy", "Northstar Product Strategy 2026", "maya@northstar.example", DOC_MIME, 150),
    ("roadmap", "Q3 Product Roadmap", "maya@northstar.example", SLIDE_MIME, 60),
    ("launch-plan", "Orbit Mobile Launch Plan", "devon@northstar.example", DOC_MIME, 35),
    ("launch-checklist", "Orbit Mobile Launch Readiness Checklist", "devon@northstar.example", DOC_MIME, 20),
    ("beta-feedback", "Orbit Mobile Beta Feedback Synthesis", "priya@northstar.example", DOC_MIME, 18),
    ("research-plan", "Mobile Onboarding Research Plan", "priya@northstar.example", DOC_MIME, 70),
    ("onboarding-spec", "Mobile Onboarding v2 Product Spec", "maya@northstar.example", DOC_MIME, 28),
    ("metrics", "Product Metrics Dictionary", "luis@northstar.example", DOC_MIME, 250),
    ("experiment", "Activation Experiment Results", "luis@northstar.example", SLIDE_MIME, 25),
    ("pricing", "Packaging and Pricing Decision", "maya@northstar.example", DOC_MIME, 115),
    ("customer-brief", "Enterprise Design Partner Brief", "elena@northstar.example", DOC_MIME, 40),
    ("gtm", "Orbit Mobile GTM Brief", "elena@northstar.example", DOC_MIME, 32),
    ("support", "Orbit Mobile Support Playbook", "sam@northstar.example", DOC_MIME, 26),
    ("incident", "Mobile Login Incident Review", "sam@northstar.example", DOC_MIME, 12),
    ("api-decision", "Mobile API Architecture Decision", "sam@northstar.example", DOC_MIME, 95),
    ("weekly", "Product Weekly - June 5", "devon@northstar.example", DOC_MIME, 3),
    ("old-requirements", "Orbit Mobile Requirements - Original Draft", "maya@northstar.example", DOC_MIME, 180),
    ("retro", "Orbit Beta Retrospective", "devon@northstar.example", DOC_MIME, 45),
]

LINKS = [
    ("roadmap", "product-strategy"), ("launch-plan", "product-strategy"),
    ("pricing", "product-strategy"), ("weekly", "product-strategy"),
    ("launch-plan", "roadmap"), ("onboarding-spec", "roadmap"),
    ("gtm", "roadmap"), ("weekly", "roadmap"),
    ("launch-checklist", "launch-plan"), ("gtm", "launch-plan"),
    ("support", "launch-plan"), ("weekly", "launch-plan"),
    ("launch-plan", "beta-feedback"), ("onboarding-spec", "beta-feedback"),
    ("retro", "beta-feedback"), ("weekly", "beta-feedback"),
    ("onboarding-spec", "research-plan"), ("beta-feedback", "research-plan"),
    ("experiment", "research-plan"),
    ("roadmap", "metrics"), ("launch-plan", "metrics"), ("onboarding-spec", "metrics"),
    ("experiment", "metrics"), ("pricing", "metrics"), ("weekly", "metrics"),
    ("launch-plan", "pricing"), ("gtm", "pricing"), ("customer-brief", "pricing"),
    ("incident", "api-decision"), ("onboarding-spec", "api-decision"),
    ("support", "api-decision"),
    ("old-requirements", "api-decision"), ("launch-plan", "old-requirements"),
]

EXTERNALS = [
    ("launch-plan", "https://linear.app/northstar/project/orbit-mobile", "Linear project", "linear.app", "linear"),
    ("launch-checklist", "https://github.com/northstar/orbit-mobile", "Mobile repository", "github.com", "github"),
    ("beta-feedback", "https://figma.com/file/orbit-mobile", "Prototype", "figma.com", "figma"),
    ("research-plan", "https://dovetail.com/projects/mobile-onboarding", "Research repository", "dovetail.com", "dovetail"),
    ("metrics", "https://amplitude.com/northstar/dashboard/activation", "Activation dashboard", "amplitude.com", "amplitude"),
    ("incident", "https://github.com/northstar/orbit-mobile/issues/842", "Incident issue", "github.com", "github"),
    ("gtm", "https://hubspot.com/northstar/campaigns/orbit", "Launch campaign", "hubspot.com", "hubspot"),
    ("support", "https://zendesk.com/northstar/orbit-mobile", "Support queue", "zendesk.com", "zendesk"),
]


def reset_demo_database(path=DEMO_DB_PATH, now=None):
    """Replace the demo database with a deterministic product-team scenario."""
    now = now or datetime.now(timezone.utc)
    for candidate in (path, f"{path}-wal", f"{path}-shm"):
        if os.path.exists(candidate):
            os.remove(candidate)
    conn = connect(path)
    init(conn)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    for person_id, email, name in PEOPLE:
        conn.execute(
            "INSERT INTO persons (id, email, display_name) VALUES (?, ?, ?)",
            (person_id, email, name),
        )

    for doc_id, title, owner, mime, age_days in DOCUMENTS:
        created = now - timedelta(days=age_days)
        modified = now - timedelta(days=min(age_days, (age_days % 19) + 1))
        conn.execute("""
            INSERT INTO documents (
                id, title, owner_email, mime_type, created_at, modified_at,
                last_indexed_at, web_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            doc_id, title, owner, mime, created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            modified.strftime("%Y-%m-%dT%H:%M:%SZ"), now_str,
            f"https://example.com/northstar/docs/{doc_id}",
        ))

    for src, dst in LINKS:
        conn.execute(
            "INSERT INTO doc_links (src_id, dst_id, first_seen, last_seen) VALUES (?, ?, ?, ?)",
            (src, dst, now_str, now_str),
        )

    for src, url, anchor, domain, resource_type in EXTERNALS:
        conn.execute("""
            INSERT INTO external_resources (id, url, domain, apex_domain, resource_type)
            VALUES (?, ?, ?, ?, ?)
        """, (url, url, domain, domain, resource_type))
        conn.execute("""
            INSERT INTO external_links (src_id, resource_id, anchor_text, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
        """, (src, url, anchor, now_str, now_str))

    _seed_activity(conn, now)
    _seed_people_activity(conn, now_str)
    conn.commit()

    refresh_findings(conn, now=now_str)
    findings = list_findings(conn, active=True, limit=100)
    rising = next((item for item in findings if item["signal_type"] == "rising"), None)
    if rising:
        update_review(conn, rising["id"], {
            "status": "resolved",
            "disposition": "monitor",
            "reviewer": "Devon Brooks",
            "assignee": "Maya Chen",
            "note": "Leadership reviewed the launch-plan spike; the owner will monitor readiness daily.",
            "follow_up_date": (now.date() + timedelta(days=7)).isoformat(),
        }, now=now_str)
    generate_brief(conn, days=7, now=now)
    conn.close()
    return path


def _seed_activity(conn, now):
    patterns = {
        "launch-plan": ([2, 3, 2, 4, 3, 2, 3], [8, 10, 12, 15, 18, 20, 24]),
        "beta-feedback": ([1, 2, 1, 2, 1, 2, 2], [6, 8, 9, 11, 13, 15, 18]),
        "onboarding-spec": ([2, 2, 3, 2, 3, 3, 2], [5, 6, 8, 8, 10, 12, 13]),
        "incident": ([0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 3, 12, 18, 7]),
        "weekly": ([0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 4, 14]),
        "product-strategy": ([4, 3, 5, 4, 3, 4, 3], [0, 0, 0, 0, 0, 0, 0]),
        "metrics": ([5, 6, 4, 5, 6, 5, 4], [0, 0, 0, 0, 0, 0, 0]),
        "api-decision": ([3, 4, 4, 3, 5, 4, 3], [0, 0, 0, 0, 0, 0, 0]),
    }
    for doc_id, (prior, recent) in patterns.items():
        for offset, total in enumerate(prior + recent):
            date = (now.date() - timedelta(days=13 - offset)).isoformat()
            conn.execute("""
                INSERT INTO activity_snapshots (document_id, date, views, edits, comments)
                VALUES (?, ?, ?, ?, ?)
            """, (doc_id, date, max(0, total - 2), 1 if total else 0, 1 if total > 4 else 0))

    for offset in range(31, 121):
        date = (now.date() - timedelta(days=offset)).isoformat()
        conn.execute("""
            INSERT INTO activity_snapshots (document_id, date, views, edits, comments)
            VALUES ('retro', ?, 3, 1, 0)
        """, (date,))


def _seed_people_activity(conn, now_str):
    assignments = [
        ("person-maya", "launch-plan", 18), ("person-devon", "launch-plan", 25),
        ("person-priya", "beta-feedback", 32), ("person-priya", "research-plan", 21),
        ("person-luis", "metrics", 28), ("person-luis", "experiment", 14),
        ("person-sam", "incident", 19), ("person-sam", "api-decision", 16),
        ("person-elena", "gtm", 17), ("person-elena", "customer-brief", 12),
    ]
    for person_id, doc_id, count in assignments:
        conn.execute("""
            INSERT INTO person_activity (person_id, document_id, action, last_seen, count)
            VALUES (?, ?, 'edit', ?, ?)
        """, (person_id, doc_id, now_str, count))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset the fictional product-team demo database")
    parser.add_argument("--path", default=DEMO_DB_PATH, help="Demo SQLite path")
    args = parser.parse_args()
    reset_demo_database(args.path)
    print(f"Demo database ready: {args.path}")
