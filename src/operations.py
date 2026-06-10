"""Persistent operational findings, review workflow, and leader briefs."""

import json
import os
import uuid
from datetime import datetime, timezone, timedelta

from analytics import (
    activity_by_doc, stale_activity, title_map, rising_docs, stale_docs,
    STALE_WINDOW_DAYS, STALE_RECENT_MAX,
)
from graph import build_doc_graph, in_degree_rank
from utils import doc_url, direness_score, severity_label


FINDING_STATUSES = {"new", "in_review", "resolved", "dismissed"}
DISPOSITIONS = {
    "current_no_action", "update_needed", "deprecate", "superseded",
    "false_positive", "monitor",
}
SIGNAL_TYPES = {"stale_hub", "rising", "went_quiet"}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _document_maps(conn):
    rows = conn.execute("SELECT id, title, mime_type, web_url FROM documents").fetchall()
    return {
        row["id"]: {
            "title": row["title"],
            "url": doc_url(row["id"], row["web_url"] or "", row["mime_type"] or ""),
        }
        for row in rows
    }


def detect_findings(conn, recent_days=7, prior_days=7):
    """Return current operational signals with structured supporting evidence."""
    docs = _document_maps(conn)
    titles = title_map(conn)
    activity = activity_by_doc(conn, days_recent=recent_days, days_prior=prior_days)
    stale_act = stale_activity(conn)
    in_deg = dict(in_degree_rank(build_doc_graph(conn)))
    detected = []
    seen = set()

    for doc_id, degree in sorted(in_deg.items(), key=lambda item: item[1], reverse=True):
        if doc_id not in docs or degree == 0:
            continue
        counts = activity.get(doc_id, {"recent": 0, "prior": 0})
        if counts["recent"] == 0:
            score = direness_score("high", in_deg_count=degree)
            detected.append(_finding_payload(
                doc_id, docs[doc_id], "stale_hub", score,
                f"Stale hub - {degree} doc{'s' if degree != 1 else ''} link here",
                "Review accuracy or add a deprecation notice",
                {
                    "recent_activity": counts["recent"],
                    "prior_activity": counts["prior"],
                    "recent_days": recent_days,
                    "prior_days": prior_days,
                    "inbound_links": degree,
                },
            ))
            seen.add(doc_id)

    for doc_id, gain, recent, prior in rising_docs(activity, titles, top_n=9999):
        if doc_id in seen or doc_id not in docs:
            continue
        score = direness_score("medium", gain=gain)
        detected.append(_finding_payload(
            doc_id, docs[doc_id], "rising", score,
            f"Rising - +{gain} activity ({prior} to {recent})",
            "Review, update, or link from an index document",
            {
                "recent_activity": recent,
                "prior_activity": prior,
                "gain": gain,
                "recent_days": recent_days,
                "prior_days": prior_days,
                "inbound_links": in_deg.get(doc_id, 0),
            },
        ))
        seen.add(doc_id)

    for doc_id, recent, history_total, degree, dropoff in stale_docs(
        stale_act, list(in_deg.items()), titles, top_n=9999
    ):
        if doc_id in seen or doc_id not in docs:
            continue
        score = direness_score("low", prior_act=history_total)
        detected.append(_finding_payload(
            doc_id, docs[doc_id], "went_quiet", score,
            f"Went quiet - was {stale_act[doc_id]['history_daily_avg']:.1f}/day, "
            f"now <= {STALE_RECENT_MAX} in {STALE_WINDOW_DAYS}d",
            "Archive, update, or confirm the work is complete",
            {
                "recent_activity": recent,
                "history_total": history_total,
                "history_daily_avg": stale_act[doc_id]["history_daily_avg"],
                "dropoff_score": round(dropoff, 1),
                "inbound_links": degree,
                "stale_window_days": STALE_WINDOW_DAYS,
            },
        ))
        seen.add(doc_id)

    return detected


def _finding_payload(doc_id, doc, signal_type, score, signal, action, metrics):
    return {
        "document_id": doc_id,
        "document_title": doc["title"],
        "document_url": doc["url"],
        "signal_type": signal_type,
        "signal": signal,
        "score": score,
        "severity": severity_label(score),
        "suggested_action": action,
        "metrics": metrics,
    }


def refresh_findings(conn, recent_days=7, prior_days=7, now=None):
    """Synchronize current analytics into persistent findings."""
    now = now or utc_now()
    detected = detect_findings(conn, recent_days, prior_days)
    current_keys = {(item["document_id"], item["signal_type"]) for item in detected}
    created = 0
    updated = 0

    for item in detected:
        evidence_json = json.dumps(item, sort_keys=True)
        existing = conn.execute("""
            SELECT id FROM findings
            WHERE document_id = ? AND signal_type = ? AND active = 1
        """, (item["document_id"], item["signal_type"])).fetchone()
        if existing:
            conn.execute("""
                UPDATE findings SET score=?, severity=?, suggested_action=?,
                    evidence_json=?, last_detected_at=?, updated_at=?
                WHERE id=?
            """, (
                item["score"], item["severity"], item["suggested_action"],
                evidence_json, now, now, existing["id"],
            ))
            updated += 1
        else:
            conn.execute("""
                INSERT INTO findings (
                    id, document_id, signal_type, score, severity, suggested_action,
                    evidence_json, first_detected_at, last_detected_at, active,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'new', ?, ?)
            """, (
                str(uuid.uuid4()), item["document_id"], item["signal_type"],
                item["score"], item["severity"], item["suggested_action"],
                evidence_json, now, now, now, now,
            ))
            created += 1

    deactivated = 0
    active_rows = conn.execute(
        "SELECT id, document_id, signal_type FROM findings WHERE active = 1"
    ).fetchall()
    for row in active_rows:
        if (row["document_id"], row["signal_type"]) not in current_keys:
            conn.execute(
                "UPDATE findings SET active=0, updated_at=? WHERE id=?",
                (now, row["id"]),
            )
            deactivated += 1

    conn.commit()
    return {"created": created, "updated": updated, "deactivated": deactivated}


def list_findings(conn, status=None, active=None, signal_type=None, assignee=None,
                  severity=None, limit=100):
    clauses = []
    params = []
    for column, value in (
        ("status", status), ("signal_type", signal_type),
        ("assignee", assignee), ("severity", severity),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if active is not None:
        clauses.append("active = ?")
        params.append(1 if active else 0)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.execute(f"""
        SELECT * FROM findings {where}
        ORDER BY active DESC, score DESC, last_detected_at DESC LIMIT ?
    """, params).fetchall()
    return [_decode_finding(row) for row in rows]


def get_finding(conn, finding_id):
    row = conn.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone()
    if not row:
        return None
    finding = _decode_finding(row)
    finding["review_history"] = [
        dict(event) for event in conn.execute("""
            SELECT status, disposition, reviewer, assignee, note, follow_up_date, created_at
            FROM finding_review_events WHERE finding_id=? ORDER BY id DESC
        """, (finding_id,))
    ]
    return finding


def _decode_finding(row):
    result = dict(row)
    result["active"] = bool(result["active"])
    result["evidence"] = json.loads(result.pop("evidence_json"))
    return result


def update_review(conn, finding_id, values, now=None):
    now = now or utc_now()
    existing = conn.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone()
    if not existing:
        return None
    status = values.get("status", existing["status"])
    disposition = values.get("disposition", existing["disposition"])
    if status not in FINDING_STATUSES:
        raise ValueError("Invalid review status")
    if disposition and disposition not in DISPOSITIONS:
        raise ValueError("Invalid disposition")
    merged = {
        key: values.get(key, existing[key])
        for key in ("reviewer", "assignee", "note", "follow_up_date")
    }
    reviewed_at = now if status in {"resolved", "dismissed"} else existing["reviewed_at"]
    conn.execute("""
        UPDATE findings SET status=?, disposition=?, reviewer=?, assignee=?, note=?,
            follow_up_date=?, reviewed_at=?, updated_at=? WHERE id=?
    """, (
        status, disposition, merged["reviewer"], merged["assignee"], merged["note"],
        merged["follow_up_date"], reviewed_at, now, finding_id,
    ))
    conn.execute("""
        INSERT INTO finding_review_events (
            finding_id, status, disposition, reviewer, assignee, note,
            follow_up_date, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        finding_id, status, disposition, merged["reviewer"], merged["assignee"],
        merged["note"], merged["follow_up_date"], now,
    ))
    conn.commit()
    return get_finding(conn, finding_id)


def generate_brief(conn, days=7, polish=False, now=None, openai_client=None, model=None):
    now_dt = now or datetime.now(timezone.utc)
    window_end = now_dt.date().isoformat()
    window_start = (now_dt.date() - timedelta(days=days)).isoformat()
    findings = list_findings(conn, active=True, limit=500)
    recently_reviewed = [
        _decode_finding(row) for row in conn.execute("""
            SELECT * FROM findings
            WHERE reviewed_at >= ? ORDER BY reviewed_at DESC
        """, (f"{window_start}T00:00:00Z",)).fetchall()
    ]
    deterministic = _build_brief_sections(findings, recently_reviewed, days)
    polished = None
    used_model = None
    if polish:
        used_model = model or os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")
        polished = polish_brief(deterministic, openai_client=openai_client, model=used_model)

    brief_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO briefs (
            id, window_start, window_end, deterministic_json, polished_json, model, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        brief_id, window_start, window_end, json.dumps(deterministic),
        json.dumps(polished) if polished else None, used_model if polished else None,
        utc_now(),
    ))
    conn.commit()
    return get_brief(conn, brief_id)


def _claim(text, findings):
    return {"text": text, "evidence_ids": [finding["id"] for finding in findings]}


def _build_brief_sections(findings, recently_reviewed, days):
    rising = [f for f in findings if f["signal_type"] == "rising"]
    stale_hubs = [f for f in findings if f["signal_type"] == "stale_hub"]
    quiet = [f for f in findings if f["signal_type"] == "went_quiet"]
    followups = [f for f in findings if f["status"] in {"new", "in_review"}]
    reviewed = [f for f in recently_reviewed if f["status"] in {"resolved", "dismissed"}]

    sections = {
        "what_changed": [],
        "follow_ups": [],
        "knowledge_risks": [],
        "recently_reviewed": [],
    }
    if rising:
        sections["what_changed"].append(_claim(
            f"{len(rising)} document{'s are' if len(rising) != 1 else ' is'} gaining activity "
            f"over the last {days} days.", rising,
        ))
    if not rising:
        sections["what_changed"].append(_claim(
            f"No documents are currently gaining significant activity over the last {days} days.", []
        ))
    if followups:
        sections["follow_ups"].append(_claim(
            f"{len(followups)} active finding{'s need' if len(followups) != 1 else ' needs'} "
            "an operations review.", followups,
        ))
    if stale_hubs:
        sections["knowledge_risks"].append(_claim(
            f"{len(stale_hubs)} linked hub document{'s are' if len(stale_hubs) != 1 else ' is'} "
            "inactive and may expose readers to outdated guidance.", stale_hubs,
        ))
    if quiet:
        sections["knowledge_risks"].append(_claim(
            f"{len(quiet)} previously active document{'s have' if len(quiet) != 1 else ' has'} "
            "gone quiet.", quiet,
        ))
    if reviewed:
        sections["recently_reviewed"].append(_claim(
            f"{len(reviewed)} finding{'s were' if len(reviewed) != 1 else ' was'} resolved or "
            f"dismissed in the last {days} days.", reviewed,
        ))
    return {"sections": sections}


def polish_brief(deterministic, openai_client=None, model="gpt-5.4-mini"):
    """Rewrite claim text while requiring the same evidence IDs."""
    if openai_client is None:
        if not os.environ.get("OPENAI_API_KEY"):
            return None
        try:
            from openai import OpenAI
            openai_client = OpenAI()
        except Exception:
            return None
    try:
        response = openai_client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Rewrite this leadership brief for clarity and brevity. Preserve every "
                        "section and evidence_ids list exactly. Do not add claims. Return JSON only."
                    ),
                },
                {"role": "user", "content": json.dumps(deterministic)},
            ],
            text={"format": {
                "type": "json_schema",
                "name": "leader_brief",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "sections": {
                            "type": "object",
                            "properties": {
                                section: {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "text": {"type": "string"},
                                            "evidence_ids": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                        "required": ["text", "evidence_ids"],
                                        "additionalProperties": False,
                                    },
                                }
                                for section in (
                                    "what_changed", "follow_ups",
                                    "knowledge_risks", "recently_reviewed",
                                )
                            },
                            "required": [
                                "what_changed", "follow_ups",
                                "knowledge_risks", "recently_reviewed",
                            ],
                            "additionalProperties": False,
                        }
                    },
                    "required": ["sections"],
                    "additionalProperties": False,
                },
            }},
        )
        candidate = json.loads(response.output_text)
        if _evidence_signature(candidate) != _evidence_signature(deterministic):
            return None
        return candidate
    except Exception:
        return None


def _evidence_signature(brief):
    try:
        return {
            section: [tuple(claim["evidence_ids"]) for claim in claims]
            for section, claims in brief["sections"].items()
        }
    except Exception:
        return None


def get_brief(conn, brief_id):
    row = conn.execute("SELECT * FROM briefs WHERE id=?", (brief_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["deterministic"] = json.loads(result.pop("deterministic_json"))
    polished_json = result.pop("polished_json")
    result["polished"] = json.loads(polished_json) if polished_json else None
    return result


def latest_brief(conn):
    row = conn.execute("SELECT id FROM briefs ORDER BY created_at DESC LIMIT 1").fetchone()
    return get_brief(conn, row["id"]) if row else None
