"""Create a realistic fictional product-team dataset for dashboard demos."""

import argparse
import os
from datetime import datetime, timezone, timedelta

from db import DEMO_DB_PATH, connect, init
from operations import generate_brief, list_findings, refresh_findings, update_review
from ontology import index_doc_terms, refresh_ontology


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

DOC_CONTENT = {
    "product-strategy": """
        Northstar Product Strategy 2026. Our mission is to build a trusted platform for enterprise
        teams that enables sustainable growth through deep user activation. We are enterprise-first
        in every decision: security, reliability, and compliance come before consumer convenience.
        Our three pillars are: trusted platform, user activation, and sustainable growth. User
        activation means a user has completed the core workflow and returned within seven days.
        Enterprise-first means we will not ship a feature that does not meet our enterprise security
        bar. Sustainable growth means we do not chase vanity metrics — we chase retention and
        expansion revenue. Every product decision must trace back to one of these three pillars.
        The strategy is owned by product leadership and reviewed quarterly. All roadmap items must
        reference this document and justify alignment with the three pillars. Misalignment between
        roadmap items and this strategy is a signal to pause and re-evaluate.
    """,
    "roadmap": """
        Q3 Product Roadmap. This roadmap operationalizes the product strategy for Q3. Our primary
        bets this quarter: improve user activation rates for new enterprise accounts, increase
        platform reliability to 99.9% uptime, and grow expansion revenue in existing accounts.
        User activation is our leading indicator — we target 60% of new enterprise accounts
        completing the core workflow within 14 days of contract start. Platform reliability work
        includes the mobile API hardening project and the auth layer rewrite. Growth this quarter
        means deepening usage within accounts, not net new logos. Each initiative below has an
        owner, a metric, and a link to the supporting spec or decision doc. The roadmap references
        the product strategy pillars: trusted platform, user activation, sustainable growth.
    """,
    "metrics": """
        Product Metrics Dictionary. This document defines the canonical metrics used across all
        Northstar product reporting. Activation rate: percentage of new accounts that complete the
        core workflow within 14 days. D7 retention: percentage of activated users who return on
        day 7. Trust score: composite of security audit results, uptime, and support resolution
        time. NPS: net promoter score collected quarterly from enterprise accounts. DAU/MAU ratio:
        daily active users divided by monthly active users, a measure of engagement depth. MRR:
        monthly recurring revenue. Expansion MRR: revenue growth within existing accounts.
        Churn rate: percentage of ARR lost in a period. All product specs and experiments must use
        these definitions. Do not define activation, retention, or trust score locally in a spec —
        reference this document.
    """,
    "launch-plan": """
        Orbit Mobile Launch Plan. This document covers the go-live plan for Orbit Mobile. The
        rollout is phased: internal beta, design partner beta, general availability. User adoption
        is our primary success metric for launch — we target 40% of beta users adopting the mobile
        workflow within 30 days. The go-live date is contingent on the auth layer passing security
        review. Launch readiness includes: support playbook complete, GTM brief approved, pricing
        finalized. The rollout plan calls for a soft launch with five design partners before
        general availability. User adoption in beta will be tracked via the Amplitude dashboard.
        Post-launch, we will monitor adoption weekly and adjust the onboarding flow if adoption
        falls below 30%. This plan references the Q3 roadmap milestones and the pricing decision.
    """,
    "onboarding-spec": """
        Mobile Onboarding v2 Product Spec. This spec covers the redesigned onboarding flow for
        Orbit Mobile. The goal is to improve onboarding completion rate — the percentage of new
        users who finish the setup flow within the first session. Current completion rate is 42%;
        target is 65%. The setup flow has five steps: account creation, team invite, first project,
        first integration, and first use of the core feature. We are removing the team invite step
        from the critical path; it becomes optional. The spec references the mobile onboarding
        research plan for user research findings. Key design principle: progressive disclosure.
        Do not front-load configuration. The integration step is optional for individual accounts
        but required for enterprise. This spec references the mobile API architecture decision for
        backend constraints on the setup flow state machine.
    """,
    "old-requirements": """
        Orbit Mobile Requirements - Original Draft. This document captures the original
        requirements for the Orbit Mobile application. The primary goal was to increase user
        engagement across mobile devices. Key requirements: sign-up flow must complete in under
        three minutes, user onboarding must include team setup and integrations, engagement metrics
        will be tracked via daily active users. The product should support both individual and
        team use cases. Enterprise features include SSO and audit logging. The sign-up flow should
        be frictionless. User onboarding is the critical path to engagement. These requirements
        were drafted before the 2026 strategy reset and use the previous product language. Several
        terms here — engagement, sign-up flow, user onboarding — have since been superseded by
        the current strategy's vocabulary: user activation, trusted platform, enterprise-first.
        This document is retained for historical context.
    """,
    "api-decision": """
        Mobile API Architecture Decision. This document records the architectural decision for the
        Orbit Mobile API layer. We evaluated three options: REST with JWT, GraphQL, and gRPC.
        Decision: REST with JWT for the mobile client, with a separate internal gRPC layer for
        service-to-service calls. The auth layer uses short-lived JWT tokens with refresh token
        rotation. Session management is stateless on the client; the server validates tokens on
        every request. Rate limiting is enforced at the API gateway: 100 requests per minute per
        authenticated user, 10 per minute for unauthenticated. The decision prioritizes
        simplicity for mobile client development and operational observability. The auth layer
        design was driven by enterprise security requirements and the trusted platform pillar.
        This decision is referenced by the onboarding spec for the setup flow state machine.
    """,
    "experiment": """
        Activation Experiment Results. This document summarizes the results of the A/B experiment
        on the mobile onboarding flow, targeting activation rate improvement. Experiment ran for
        14 days with 800 new users split evenly between control and treatment. Treatment:
        progressive disclosure in the setup flow, with the integration step deferred. Results:
        activation rate in treatment group was 61% versus 43% in control — an 18 percentage point
        lift. D7 retention was 52% for treatment versus 44% for control. The trust score was
        unaffected. Statistical significance: p < 0.01. Recommendation: ship the treatment as
        the new default onboarding flow. This experiment references the metrics dictionary
        definitions for activation rate and D7 retention. The activation rate improvement
        directly supports the Q3 roadmap target of 60% activation for new enterprise accounts.
    """,
    "gtm": """
        Orbit Mobile GTM Brief. This brief outlines the go-to-market strategy for Orbit Mobile
        general availability. Our primary motion is product-led with enterprise sales overlay.
        User adoption in the SMB segment will be driven by self-serve activation. Enterprise
        accounts will be onboarded through a managed launch with customer success. The messaging
        platform: Orbit Mobile is the trusted mobile layer for enterprise teams. Key channels:
        in-app announcements, email to existing accounts, partner co-marketing. We will track
        adoption and user onboarding completion as the primary launch metrics. The launch campaign
        is live in HubSpot. Pricing is referenced from the packaging and pricing decision doc.
        The GTM brief aligns with the go-live plan in the launch plan document. Post-launch
        reporting will use activation and adoption rates as headline numbers.
    """,
    "launch-checklist": """
        Orbit Mobile Launch Readiness Checklist. This checklist tracks launch readiness across
        all workstreams. Engineering: auth layer security review complete, rate limiting tested,
        mobile API load tested at 10x expected traffic. Product: onboarding spec shipped,
        activation tracking instrumented in Amplitude, support playbook reviewed. GTM: launch
        campaign approved, design partner briefings complete, pricing page updated. Legal: terms
        of service updated for mobile, data processing agreement reviewed. The checklist is the
        go/no-go gate for the rollout. Each item must be marked complete by the responsible owner
        before the go-live date. The checklist references the launch plan for the rollout phases
        and the mobile repository for the engineering sign-offs.
    """,
    "beta-feedback": """
        Orbit Mobile Beta Feedback Synthesis. This document synthesizes feedback from the 12-week
        beta with five design partners. Top themes: onboarding flow too long (8 of 12 partners),
        integration setup confusing (6 of 12), mobile performance excellent (11 of 12). The
        onboarding feedback directly motivated the v2 onboarding spec. Design partners report high
        satisfaction with core feature performance but friction in the setup flow. Three partners
        flagged the sign-up flow as a barrier for inviting team members. One partner noted that
        the terminology in the app does not match their internal language for the same concepts.
        Recommended actions: shorten setup flow, add progressive disclosure, add skip options for
        optional steps. This synthesis references the mobile onboarding research plan for the
        broader user research context and the retrospective for lessons learned.
    """,
    "weekly": """
        Product Weekly - June 5. This week's highlights: launch plan is on track for go-live
        in three weeks. The activation experiment results are in — strong lift, recommending we
        ship the treatment. Onboarding spec is in final review. The incident review is complete
        and the auth fix is live. Metrics this week: activation rate up 4 points week-over-week,
        D7 retention stable. The roadmap is green across all Q3 initiatives. Open items: pricing
        page copy still in legal review, GTM launch campaign needs final approval. The weekly
        references the launch plan, roadmap, and beta feedback for context on current status.
        Next week: go/no-go review for the rollout with all workstream leads.
    """,
}

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
    for doc_id, text in DOC_CONTENT.items():
        index_doc_terms(conn, doc_id, text)
    refresh_ontology(conn)

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
