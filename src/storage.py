"""Tenant/workspace scoping helpers for the local-to-hosted migration."""

from dataclasses import dataclass
import json

from utils import doc_url


def dialect(conn):
    """Best-effort SQL dialect detection for the storage boundary."""
    explicit = getattr(conn, "dialect", None)
    if explicit:
        return explicit
    module = type(conn).__module__
    if module.startswith("sqlite3"):
        return "sqlite"
    if module.startswith("psycopg") or module.startswith("psycopg2"):
        return "postgresql"
    return "sqlite"


def postgres_sql(sql):
    return (
        sql
        .replace("?", "%s")
        .replace("last_seen=MAX(last_seen, excluded.last_seen)", "last_seen=GREATEST(last_seen, excluded.last_seen)")
    )


def sql_for_connection(conn, sql):
    """Translate storage SQL placeholders for the target connection."""
    if dialect(conn) in {"postgres", "postgresql"}:
        return postgres_sql(sql)
    return sql


def execute(conn, sql, params=()):
    return conn.execute(sql_for_connection(conn, sql), params)


def conflict_target(conn, sqlite_columns, scoped_columns):
    """Return the ON CONFLICT target that matches this storage backend."""
    columns = scoped_columns if dialect(conn) in {"postgres", "postgresql"} else sqlite_columns
    return f"({', '.join(columns)})"


@dataclass(frozen=True)
class StorageScope:
    tenant_id: str
    workspace_id: str

    @property
    def params(self):
        return [self.tenant_id, self.workspace_id]


def from_workspace(workspace):
    if not workspace:
        return None
    return StorageScope(workspace["tenant_id"], workspace["id"])


def where_scope(scope, alias=None, prefix="WHERE"):
    if not scope:
        return "", []
    column = lambda name: f"{alias}.{name}" if alias else name
    return (
        f"{prefix} {column('tenant_id')} = ? AND {column('workspace_id')} = ?",
        scope.params,
    )


def and_scope(scope, alias=None):
    return where_scope(scope, alias=alias, prefix="AND")


def count_rows(conn, table, scope=None, distinct=None):
    scope_sql, params = where_scope(scope)
    expression = f"COUNT(DISTINCT {distinct})" if distinct else "COUNT(*)"
    row = execute(conn, f"SELECT {expression} AS count_value FROM {table} {scope_sql}", params).fetchone()
    return row["count_value"]


def overview_counts(conn, scope=None):
    return {
        "documents_indexed": count_rows(conn, "documents", scope),
        "doc_links": count_rows(conn, "doc_links", scope),
        "external_links": count_rows(conn, "external_links", scope),
        "activity_days": count_rows(conn, "activity_snapshots", scope, distinct="date"),
        "persons_indexed": count_rows(conn, "persons", scope),
    }


def list_workspace_documents(conn, scope=None, limit=100, offset=0):
    scope_sql, params = where_scope(scope)
    rows = execute(conn, """
        SELECT id, title, mime_type, owner_email, modified_at, web_url
        FROM documents {scope_sql} ORDER BY modified_at DESC LIMIT ? OFFSET ?
    """.format(scope_sql=scope_sql), params + [limit, offset]).fetchall()
    return [dict(row) for row in rows]


def document_lookup_maps(conn, scope=None):
    scope_sql, params = where_scope(scope)
    titles = {}
    mimes = {}
    web_urls = {}
    for row in execute(conn,
        f"SELECT id, title, mime_type, web_url FROM documents {scope_sql}",
        params,
    ):
        titles[row["id"]] = row["title"]
        mimes[row["id"]] = row["mime_type"] or ""
        web_urls[row["id"]] = row["web_url"] or ""
    return titles, mimes, web_urls


def document_title_rows(conn, scope=None):
    scope_sql, params = where_scope(scope)
    rows = execute(conn, f"SELECT id, title FROM documents {scope_sql}", params).fetchall()
    return [dict(row) for row in rows]


def graph_document_rows(conn, scope=None):
    scope_sql, params = where_scope(scope)
    return execute(conn,
        f"SELECT id, title, mime_type, modified_at FROM documents {scope_sql}",
        params,
    ).fetchall()


def graph_link_rows(conn, scope=None):
    scope_sql, params = where_scope(scope)
    return execute(conn, f"SELECT src_id, dst_id FROM doc_links {scope_sql}", params).fetchall()


def activity_totals_by_doc(conn, start_date, end_date=None, scope=None):
    scope_sql, scope_params = and_scope(scope)
    end_clause = "AND date < ?" if end_date else ""
    params = [start_date] + ([end_date] if end_date else []) + scope_params
    rows = execute(conn, """
        SELECT document_id, SUM(views + edits + comments) as total
        FROM activity_snapshots
        WHERE date >= ? {end_clause} {scope_sql}
        GROUP BY document_id
    """.format(end_clause=end_clause, scope_sql=scope_sql), params).fetchall()
    return {row["document_id"]: row["total"] or 0 for row in rows}


def external_link_summary_rows(conn, by="category", top_n=20, scope=None):
    col = "er.resource_type" if by == "category" else "er.domain"
    link_scope_sql, link_scope_params = and_scope(scope, alias="el")
    rows = execute(conn, f"""
        SELECT {col} as label, COUNT(*) as cnt
        FROM external_links el
        JOIN external_resources er ON el.resource_id = er.id
            AND (el.tenant_id IS NULL OR er.tenant_id = el.tenant_id)
            AND (el.workspace_id IS NULL OR er.workspace_id = el.workspace_id)
        WHERE er.domain != '' AND er.domain != 'unknown' {link_scope_sql}
        GROUP BY label
        ORDER BY cnt DESC
        LIMIT ?
    """, link_scope_params + [top_n]).fetchall()
    return [dict(row) for row in rows]


def document_dashboard_maps(conn, scope=None):
    scope_sql, params = where_scope(scope)
    rows = execute(conn,
        f"SELECT id, title, mime_type, web_url, modified_at FROM documents {scope_sql}",
        params,
    ).fetchall()
    titles = {}
    mimes = {}
    urls = {}
    modified = {}
    for row in rows:
        doc_id = row["id"]
        mime = row["mime_type"] or ""
        titles[doc_id] = row["title"]
        mimes[doc_id] = mime
        urls[doc_id] = doc_url(doc_id, row["web_url"] or "", mime)
        modified[doc_id] = row["modified_at"] or ""
    return titles, mimes, urls, modified


def external_domain_rollups(conn, scope=None):
    link_scope_sql, link_scope_params = and_scope(scope, alias="el")
    ext_by_apex = [
        {"domain": row["apex_domain"], "links": row["cnt"]}
        for row in execute(conn, """
            SELECT COALESCE(NULLIF(er.apex_domain,''), er.domain) as apex_domain,
                   COUNT(*) as cnt
            FROM external_links el
            JOIN external_resources er ON el.resource_id = er.id
                AND (el.tenant_id IS NULL OR er.tenant_id = el.tenant_id)
                AND (el.workspace_id IS NULL OR er.workspace_id = el.workspace_id)
            WHERE er.domain != '' AND er.domain != 'unknown' {scope_sql}
            GROUP BY apex_domain ORDER BY cnt DESC LIMIT 40
        """.format(scope_sql=link_scope_sql), link_scope_params).fetchall()
    ]
    ext_domains = [
        {"domain": row["domain"], "apex": row["apex_domain"] or "", "links": row["cnt"]}
        for row in execute(conn, """
            SELECT er.domain, er.apex_domain, COUNT(*) as cnt
            FROM external_links el
            JOIN external_resources er ON el.resource_id = er.id
                AND (el.tenant_id IS NULL OR er.tenant_id = el.tenant_id)
                AND (el.workspace_id IS NULL OR er.workspace_id = el.workspace_id)
            WHERE er.domain != '' AND er.domain != 'unknown' {scope_sql}
            GROUP BY er.domain, er.apex_domain ORDER BY cnt DESC LIMIT 100
        """.format(scope_sql=link_scope_sql), link_scope_params).fetchall()
    ]
    return ext_by_apex, ext_domains


def activity_history_rows(conn, doc_id=None, scope=None):
    scope_sql, scope_params = and_scope(scope)
    doc_clause = "document_id = ?" if doc_id else "1=1"
    params = ([doc_id] if doc_id else []) + scope_params
    rows = execute(conn, """
        SELECT document_id, date, views, edits, comments
        FROM activity_snapshots
        WHERE {doc_clause} {scope_sql}
        ORDER BY document_id, date
    """.format(doc_clause=doc_clause, scope_sql=scope_sql), params).fetchall()
    return [dict(row) for row in rows]


def document_link_maps(conn, scope=None):
    inbound_links = {}
    outbound_links = {}
    for row in graph_link_rows(conn, scope):
        inbound_links.setdefault(row["dst_id"], []).append(row["src_id"])
        outbound_links.setdefault(row["src_id"], []).append(row["dst_id"])
    return inbound_links, outbound_links


def document_external_link_rows(conn, scope=None):
    link_scope_sql, link_scope_params = and_scope(scope, alias="el")
    rows = execute(conn, """
        SELECT el.src_id, er.domain, er.url, el.anchor_text
        FROM external_links el
        JOIN external_resources er ON el.resource_id = er.id
            AND (el.tenant_id IS NULL OR er.tenant_id = el.tenant_id)
            AND (el.workspace_id IS NULL OR er.workspace_id = el.workspace_id)
        WHERE 1=1 {scope_sql}
        ORDER BY er.domain
    """.format(scope_sql=link_scope_sql), link_scope_params).fetchall()
    return [dict(row) for row in rows]


def person_rows(conn, scope=None):
    scope_sql, params = where_scope(scope)
    return execute(conn, f"SELECT id, display_name, email FROM persons {scope_sql}", params).fetchall()


def owner_count_rows(conn, scope=None):
    scope_sql, params = and_scope(scope)
    rows = execute(conn, """
        SELECT owner_email, COUNT(*) as cnt
        FROM documents
        WHERE owner_email != '' {scope_sql}
        GROUP BY owner_email
        ORDER BY cnt DESC
    """.format(scope_sql=scope_sql), params).fetchall()
    return [dict(row) for row in rows]


def top_editor_rows(conn, limit=20, scope=None):
    scope_sql, params = and_scope(scope)
    rows = execute(conn, """
        SELECT person_id,
               COUNT(DISTINCT document_id) as doc_count,
               SUM(count) as total_edits
        FROM person_activity
        WHERE action = 'edit' {scope_sql}
        GROUP BY person_id
        ORDER BY total_edits DESC
        LIMIT ?
    """.format(scope_sql=scope_sql), params + [limit]).fetchall()
    return [dict(row) for row in rows]


def person_activity_rows(conn, scope=None):
    scope_sql, params = where_scope(scope)
    rows = execute(conn, """
        SELECT document_id, person_id, action, count, last_seen
        FROM person_activity
        {scope_sql}
        ORDER BY count DESC
    """.format(scope_sql=scope_sql), params).fetchall()
    return [dict(row) for row in rows]


def get_document_detail(conn, doc_id, scope=None):
    doc_scope_sql, doc_scope_params = and_scope(scope)
    row = execute(conn,
        "SELECT * FROM documents WHERE id = ? {scope_sql}".format(scope_sql=doc_scope_sql),
        [doc_id] + doc_scope_params,
    ).fetchone()
    if not row:
        return None

    doc = dict(row)
    doc["url"] = doc_url(doc_id, doc.get("web_url") or "", doc.get("mime_type") or "")

    def title_for(document_id):
        title_row = execute(conn,
            "SELECT title FROM documents WHERE id=? {scope_sql}".format(scope_sql=doc_scope_sql),
            [document_id] + doc_scope_params,
        ).fetchone()
        return title_row["title"] if title_row else None

    link_scope_sql, link_scope_params = and_scope(scope)
    doc["inbound_links"] = [
        {"src_id": link["src_id"], "title": title_for(link["src_id"])}
        for link in execute(conn,
            "SELECT src_id FROM doc_links WHERE dst_id=? {scope_sql}".format(scope_sql=link_scope_sql),
            [doc_id] + link_scope_params,
        ).fetchall()
    ]
    doc["outbound_links"] = [
        {"dst_id": link["dst_id"], "title": title_for(link["dst_id"])}
        for link in execute(conn,
            "SELECT src_id, dst_id FROM doc_links WHERE src_id=? {scope_sql}".format(scope_sql=link_scope_sql),
            [doc_id] + link_scope_params,
        ).fetchall()
    ]
    doc["activity_history"] = [
        dict(row) for row in execute(conn, """
            SELECT date, views, edits, comments
            FROM activity_snapshots WHERE document_id=? {scope_sql} ORDER BY date
        """.format(scope_sql=link_scope_sql), [doc_id] + link_scope_params).fetchall()
    ]

    person_scope_sql, person_scope_params = and_scope(scope, alias="pa")
    doc["contributors"] = [
        {
            "person_id": row["person_id"],
            "display_name": row["display_name"],
            "email": row["email"],
            "action": row["action"],
            "count": row["count"],
            "last_seen": row["last_seen"],
        }
        for row in execute(conn, """
            SELECT pa.person_id, p.display_name, p.email, pa.action, pa.count, pa.last_seen
            FROM person_activity pa
            LEFT JOIN persons p ON pa.person_id = p.id
                AND pa.tenant_id = p.tenant_id AND pa.workspace_id = p.workspace_id
            WHERE pa.document_id=? {scope_sql}
            ORDER BY pa.count DESC
        """.format(scope_sql=person_scope_sql), [doc_id] + person_scope_params).fetchall()
    ]

    external_scope_sql, external_scope_params = and_scope(scope, alias="el")
    doc["external_links"] = [
        {
            "domain": row["domain"],
            "apex_domain": row["apex_domain"],
            "url": row["url"],
            "anchor_text": row["anchor_text"],
        }
        for row in execute(conn, """
            SELECT er.domain, er.apex_domain, er.url, el.anchor_text
            FROM external_links el
            JOIN external_resources er ON el.resource_id = er.id
                AND el.tenant_id = er.tenant_id AND el.workspace_id = er.workspace_id
            WHERE el.src_id=? {scope_sql}
        """.format(scope_sql=external_scope_sql), [doc_id] + external_scope_params).fetchall()
    ]
    return doc


def person_viewed_document_ids(conn, person_id, scope=None):
    scope_sql, scope_params = and_scope(scope)
    rows = execute(conn, """
        SELECT document_id, count FROM person_activity
        WHERE person_id=? AND action='view' {scope_sql}
    """.format(scope_sql=scope_sql), [person_id] + scope_params).fetchall()
    return {row["document_id"] for row in rows}, sum(row["count"] for row in rows)


def attributed_view_count(conn, scope=None):
    scope_sql, scope_params = and_scope(scope)
    row = execute(conn,
        "SELECT COUNT(*) AS count_value FROM person_activity WHERE action='view' {scope_sql}".format(scope_sql=scope_sql),
        scope_params,
    ).fetchone()
    return row["count_value"]


def list_people(conn, scope=None):
    scope_sql, scope_params = where_scope(scope, alias="p")
    rows = execute(conn, """
        SELECT p.id, p.display_name, p.email,
               SUM(CASE WHEN pa.action='view' THEN pa.count ELSE 0 END) as attributed_views
        FROM persons p
        LEFT JOIN person_activity pa ON pa.person_id = p.id
            AND pa.tenant_id = p.tenant_id AND pa.workspace_id = p.workspace_id
        {scope_sql}
        GROUP BY p.id
        ORDER BY COALESCE(NULLIF(p.display_name,''), NULLIF(p.email,''), p.id)
    """.format(scope_sql=scope_sql), scope_params).fetchall()
    return [dict(row) for row in rows]


def external_link_summary(conn, scope=None, group_by="apex", limit=50):
    link_scope_sql, link_scope_params = and_scope(scope, alias="el")
    col = "er.apex_domain" if group_by == "apex" else "er.domain"
    rows = execute(conn, f"""
        SELECT COALESCE(NULLIF({col},''), er.domain) as label, COUNT(*) as cnt
        FROM external_links el
        JOIN external_resources er ON el.resource_id = er.id
            AND el.tenant_id = er.tenant_id AND el.workspace_id = er.workspace_id
        WHERE er.domain != '' AND er.domain IS NOT NULL
            {link_scope_sql}
        GROUP BY label ORDER BY cnt DESC LIMIT ?
    """, link_scope_params + [limit]).fetchall()
    return [{"domain": row["label"], "links": row["cnt"]} for row in rows]


def ontology_terms(conn, doc_id, scope=None):
    term_scope_sql, term_scope_params = and_scope(scope)
    rows = execute(conn,
        "SELECT term, frequency, term_type FROM doc_terms WHERE doc_id = ? {scope_sql} ORDER BY frequency DESC".format(scope_sql=term_scope_sql),
        [doc_id] + term_scope_params,
    ).fetchall()
    return [dict(row) for row in rows]


def ontology_alignment_rows(conn, doc_id, scope=None):
    alignment_scope_sql, alignment_scope_params = and_scope(scope)
    rows = execute(conn,
        """SELECT src_id, dst_id, alignment_score, shared_terms, divergent_terms
           FROM doc_alignment WHERE (src_id = ? OR dst_id = ?) {scope_sql}""".format(scope_sql=alignment_scope_sql),
        [doc_id, doc_id] + alignment_scope_params,
    ).fetchall()
    return [dict(row) for row in rows]


def ontology_drift_rows(conn, threshold, scope=None):
    alignment_scope_sql, alignment_scope_params = and_scope(scope)
    rows = execute(conn,
        """SELECT src_id, dst_id, alignment_score, divergent_terms
           FROM doc_alignment WHERE alignment_score IS NOT NULL AND alignment_score < ?
           {scope_sql}
           ORDER BY alignment_score ASC""".format(scope_sql=alignment_scope_sql),
        [threshold] + alignment_scope_params,
    ).fetchall()
    return [dict(row) for row in rows]


def active_finding_row(conn, document_id, signal_type, scope=None):
    scope_sql, scope_params = and_scope(scope)
    return execute(conn, """
        SELECT id FROM findings
        WHERE document_id = ? AND signal_type = ? AND active = 1 {scope_sql}
    """.format(scope_sql=scope_sql), [document_id, signal_type] + scope_params).fetchone()


def update_finding_detection(conn, finding_id, values, scope=None):
    scope_sql, scope_params = and_scope(scope)
    execute(conn, """
        UPDATE findings SET score=?, severity=?, suggested_action=?,
            evidence_json=?, last_detected_at=?, updated_at=?
        WHERE id=? {scope_sql}
    """.format(scope_sql=scope_sql), [
        values["score"], values["severity"], values["suggested_action"],
        values["evidence_json"], values["last_detected_at"], values["updated_at"],
        finding_id,
    ] + scope_params)


def insert_finding(conn, values):
    execute(conn, """
        INSERT INTO findings (
            id, tenant_id, workspace_id, document_id, signal_type, score, severity, suggested_action,
            evidence_json, first_detected_at, last_detected_at, active,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'new', ?, ?)
    """, (
        values["id"], values.get("tenant_id"), values.get("workspace_id"),
        values["document_id"], values["signal_type"], values["score"],
        values["severity"], values["suggested_action"], values["evidence_json"],
        values["first_detected_at"], values["last_detected_at"],
        values["created_at"], values["updated_at"],
    ))


def active_finding_rows(conn, scope=None):
    scope_sql, scope_params = and_scope(scope)
    return execute(conn,
        "SELECT id, document_id, signal_type FROM findings WHERE active = 1 {scope_sql}".format(scope_sql=scope_sql),
        scope_params,
    ).fetchall()


def deactivate_finding(conn, finding_id, updated_at, scope=None):
    scope_sql, scope_params = and_scope(scope)
    execute(conn,
        "UPDATE findings SET active=0, updated_at=? WHERE id=? {scope_sql}".format(scope_sql=scope_sql),
        [updated_at, finding_id] + scope_params,
    )


def finding_rows(conn, status=None, active=None, signal_type=None, assignee=None,
                 severity=None, limit=100, scope=None):
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
    if scope:
        clauses.append("tenant_id = ?")
        clauses.append("workspace_id = ?")
        params.extend(scope.params)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return execute(conn, f"""
        SELECT * FROM findings {where}
        ORDER BY active DESC, score DESC, last_detected_at DESC LIMIT ?
    """, params).fetchall()


def finding_row(conn, finding_id, scope=None):
    scope_sql, scope_params = and_scope(scope)
    return execute(conn,
        "SELECT * FROM findings WHERE id=? {scope_sql}".format(scope_sql=scope_sql),
        [finding_id] + scope_params,
    ).fetchone()


def finding_review_event_rows(conn, finding_id, scope=None):
    scope_sql, scope_params = and_scope(scope)
    return execute(conn, """
        SELECT status, disposition, reviewer, assignee, note, follow_up_date, created_at
        FROM finding_review_events WHERE finding_id=? {scope_sql} ORDER BY id DESC
    """.format(scope_sql=scope_sql), [finding_id] + scope_params).fetchall()


def update_finding_review(conn, finding_id, values, scope=None):
    scope_sql, scope_params = and_scope(scope)
    execute(conn, """
        UPDATE findings SET status=?, disposition=?, reviewer=?, assignee=?, note=?,
            follow_up_date=?, reviewed_at=?, updated_at=? WHERE id=? {scope_sql}
    """.format(scope_sql=scope_sql), [
        values["status"], values["disposition"], values["reviewer"],
        values["assignee"], values["note"], values["follow_up_date"],
        values["reviewed_at"], values["updated_at"], finding_id,
    ] + scope_params)


def insert_finding_review_event(conn, values):
    execute(conn, """
        INSERT INTO finding_review_events (
            tenant_id, workspace_id, finding_id, status, disposition, reviewer, assignee, note,
            follow_up_date, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        values.get("tenant_id"), values.get("workspace_id"), values["finding_id"],
        values["status"], values["disposition"], values["reviewer"],
        values["assignee"], values["note"], values["follow_up_date"],
        values["created_at"],
    ))


def recently_reviewed_finding_rows(conn, window_start, scope=None):
    scope_sql, scope_params = and_scope(scope)
    return execute(conn, """
        SELECT * FROM findings
        WHERE reviewed_at >= ? {scope_sql} ORDER BY reviewed_at DESC
    """.format(scope_sql=scope_sql), [window_start] + scope_params).fetchall()


def insert_brief(conn, values):
    execute(conn, """
        INSERT INTO briefs (
            id, tenant_id, workspace_id, window_start, window_end,
            deterministic_json, polished_json, model, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        values["id"], values.get("tenant_id"), values.get("workspace_id"),
        values["window_start"], values["window_end"], values["deterministic_json"],
        values.get("polished_json"), values.get("model"), values["created_at"],
    ))


def brief_row(conn, brief_id, scope=None):
    scope_sql, scope_params = and_scope(scope)
    return execute(conn,
        "SELECT * FROM briefs WHERE id=? {scope_sql}".format(scope_sql=scope_sql),
        [brief_id] + scope_params,
    ).fetchone()


def latest_brief_id(conn, scope=None):
    scope_sql, scope_params = where_scope(scope)
    row = execute(conn,
        f"SELECT id FROM briefs {scope_sql} ORDER BY created_at DESC LIMIT 1",
        scope_params,
    ).fetchone()
    return row["id"] if row else None


def _decode_indexing_job(row):
    if not row:
        return None
    job = dict(row)
    result_json = job.pop("result_json", None)
    job["result"] = json.loads(result_json) if result_json else None
    job["expand"] = bool(job["expand"])
    return job


def insert_indexing_job(conn, values, scope=None):
    execute(conn, """
        INSERT INTO indexing_jobs (
            id, tenant_id, workspace_id, workspace_name, status, phase, message,
            current, total, progress, document_title, days, expand, result_json,
            error, created_at, updated_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        values["id"],
        scope.tenant_id if scope else values.get("tenant_id"),
        scope.workspace_id if scope else values.get("workspace_id"),
        values.get("workspace_name"),
        values["status"],
        values.get("phase"),
        values.get("message"),
        values.get("current"),
        values.get("total"),
        values.get("progress"),
        values.get("document_title"),
        values.get("days"),
        1 if values.get("expand") else 0,
        json.dumps(values["result"], sort_keys=True) if values.get("result") is not None else None,
        values.get("error"),
        values["created_at"],
        values["updated_at"],
        values.get("completed_at"),
    ))
    conn.commit()


def update_indexing_job(conn, job_id, values, scope=None):
    allowed = {
        "status", "phase", "message", "current", "total", "progress",
        "document_title", "days", "expand", "result", "error",
        "updated_at", "completed_at",
    }
    columns = []
    params = []
    for key, value in values.items():
        if key not in allowed:
            continue
        if key == "result":
            columns.append("result_json = ?")
            params.append(json.dumps(value, sort_keys=True) if value is not None else None)
        elif key == "expand":
            columns.append("expand = ?")
            params.append(1 if value else 0)
        else:
            columns.append(f"{key} = ?")
            params.append(value)
    if not columns:
        return
    scope_sql, scope_params = and_scope(scope)
    execute(conn, """
        UPDATE indexing_jobs
        SET {assignments}
        WHERE id = ? {scope_sql}
    """.format(assignments=", ".join(columns), scope_sql=scope_sql), params + [job_id] + scope_params)
    conn.commit()


def indexing_job_row(conn, job_id, scope=None):
    scope_sql, scope_params = and_scope(scope)
    row = execute(conn, """
        SELECT * FROM indexing_jobs
        WHERE id = ? {scope_sql}
    """.format(scope_sql=scope_sql), [job_id] + scope_params).fetchone()
    return _decode_indexing_job(row)


def latest_indexing_job_row(conn, scope=None):
    scope_sql, scope_params = where_scope(scope)
    row = execute(conn, """
        SELECT * FROM indexing_jobs
        {scope_sql}
        ORDER BY created_at DESC
        LIMIT 1
    """.format(scope_sql=scope_sql), scope_params).fetchone()
    return _decode_indexing_job(row)


def active_indexing_job_row(conn, scope=None):
    scope_sql, scope_params = and_scope(scope)
    row = execute(conn, """
        SELECT * FROM indexing_jobs
        WHERE status IN ('queued', 'running') {scope_sql}
        ORDER BY created_at DESC
        LIMIT 1
    """.format(scope_sql=scope_sql), scope_params).fetchone()
    return _decode_indexing_job(row)


def crawl_schedule_row(conn, scope=None):
    scope_sql, scope_params = where_scope(scope)
    row = execute(conn, """
        SELECT * FROM crawl_schedules
        {scope_sql}
        LIMIT 1
    """.format(scope_sql=scope_sql), scope_params).fetchone()
    return dict(row) if row else None


def upsert_crawl_schedule(conn, values, scope=None):
    conflict = conflict_target(conn, ["tenant_id", "workspace_id"], ["tenant_id", "workspace_id"])
    execute(conn, f"""
        INSERT INTO crawl_schedules (
            id, tenant_id, workspace_id, enabled, schedule_cron,
            schedule_timezone, crawl_mode, next_run_at, paused_at,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT{conflict} DO UPDATE SET
            enabled=excluded.enabled,
            schedule_cron=excluded.schedule_cron,
            schedule_timezone=excluded.schedule_timezone,
            crawl_mode=excluded.crawl_mode,
            next_run_at=excluded.next_run_at,
            paused_at=excluded.paused_at,
            updated_at=excluded.updated_at
    """, (
        values["id"],
        scope.tenant_id if scope else values.get("tenant_id"),
        scope.workspace_id if scope else values.get("workspace_id"),
        1 if values.get("enabled") else 0,
        values.get("schedule_cron"),
        values.get("schedule_timezone"),
        values.get("crawl_mode"),
        values.get("next_run_at"),
        values.get("paused_at"),
        values["created_at"],
        values["updated_at"],
    ))
    conn.commit()


def insert_analytics_event(conn, values, scope=None):
    execute(conn, """
        INSERT INTO analytics_events (
            id, tenant_id, workspace_id, event_type, finding_id,
            document_id, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        values["id"],
        scope.tenant_id if scope else values.get("tenant_id"),
        scope.workspace_id if scope else values.get("workspace_id"),
        values["event_type"],
        values.get("finding_id"),
        values.get("document_id"),
        json.dumps(values.get("metadata", {}), sort_keys=True),
        values["created_at"],
    ))
    conn.commit()


def google_connection_row(conn, scope=None, provider="google"):
    scope_sql, scope_params = and_scope(scope)
    row = execute(conn, """
        SELECT id, tenant_id, workspace_id, provider, account_email, status,
               granted_scopes_json, connected_at, disconnected_at,
               last_checked_at, health, error, created_at, updated_at
        FROM google_connections
        WHERE provider = ? {scope_sql}
        LIMIT 1
    """.format(scope_sql=scope_sql), [provider] + scope_params).fetchone()
    if not row:
        return None
    result = dict(row)
    scopes = result.pop("granted_scopes_json", None)
    result["granted_scopes"] = json.loads(scopes) if scopes else []
    return result


def upsert_google_connection(conn, values, scope=None):
    conflict = conflict_target(
        conn,
        ["tenant_id", "workspace_id", "provider"],
        ["tenant_id", "workspace_id", "provider"],
    )
    execute(conn, f"""
        INSERT INTO google_connections (
            id, tenant_id, workspace_id, provider, account_email, status,
            granted_scopes_json, token_encrypted, token_version, connected_at,
            disconnected_at, last_checked_at, health, error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT{conflict} DO UPDATE SET
            account_email=excluded.account_email,
            status=excluded.status,
            granted_scopes_json=excluded.granted_scopes_json,
            token_encrypted=excluded.token_encrypted,
            token_version=excluded.token_version,
            connected_at=excluded.connected_at,
            disconnected_at=excluded.disconnected_at,
            last_checked_at=excluded.last_checked_at,
            health=excluded.health,
            error=excluded.error,
            updated_at=excluded.updated_at
    """, (
        values["id"],
        scope.tenant_id if scope else values.get("tenant_id"),
        scope.workspace_id if scope else values.get("workspace_id"),
        values.get("provider", "google"),
        values.get("account_email"),
        values.get("status", "disconnected"),
        json.dumps(values.get("granted_scopes", []), sort_keys=True),
        values.get("token_encrypted"),
        values.get("token_version"),
        values.get("connected_at"),
        values.get("disconnected_at"),
        values.get("last_checked_at"),
        values.get("health"),
        values.get("error"),
        values["created_at"],
        values["updated_at"],
    ))
    conn.commit()


def delete_indexed_workspace_data(conn, scope):
    tables = (
        "documents", "persons", "external_resources", "doc_links",
        "external_links", "activity_snapshots", "person_activity",
        "findings", "finding_review_events", "briefs", "doc_terms",
        "doc_alignment", "analytics_events",
    )
    deleted = {}
    for table in tables:
        count = count_rows(conn, table, scope)
        scope_sql, scope_params = where_scope(scope)
        execute(conn, f"DELETE FROM {table} {scope_sql}", scope_params)
        deleted[table] = count
    conn.commit()
    return deleted


def drift_pair_rows(conn, threshold, scope=None, limit=3):
    rows = execute(conn, """
        SELECT da.src_id, da.dst_id, da.alignment_score, da.divergent_terms,
               s.title AS src_title, d.title AS dst_title,
               s.web_url AS src_url, d.web_url AS dst_url
        FROM doc_alignment da
        JOIN documents s ON s.id = da.src_id
            AND s.tenant_id = da.tenant_id AND s.workspace_id = da.workspace_id
        JOIN documents d ON d.id = da.dst_id
            AND d.tenant_id = da.tenant_id AND d.workspace_id = da.workspace_id
        WHERE da.alignment_score <= ?
            {scope_sql}
        ORDER BY da.alignment_score ASC
        LIMIT ?
    """.format(scope_sql=and_scope(scope, alias="da")[0]), [threshold] + and_scope(scope, alias="da")[1] + [limit]).fetchall()
    return [dict(row) for row in rows]


def max_alignment_score(conn, scope=None):
    scope_sql, scope_params = where_scope(scope, alias="da")
    row = execute(conn,
        f"SELECT MAX(alignment_score) AS m FROM doc_alignment da {scope_sql}",
        scope_params,
    ).fetchone()
    return row["m"] if row else None


def upsert_document(conn, values, scope=None):
    conflict = conflict_target(conn, ["id"], ["tenant_id", "workspace_id", "id"])
    execute(conn, f"""
        INSERT INTO documents (
            id, tenant_id, workspace_id, title, owner_email, mime_type,
            created_at, modified_at, last_indexed_at, web_url
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT{conflict} DO UPDATE SET
            title=excluded.title,
            owner_email=excluded.owner_email,
            mime_type=excluded.mime_type,
            created_at=excluded.created_at,
            modified_at=excluded.modified_at,
            last_indexed_at=excluded.last_indexed_at,
            web_url=excluded.web_url,
            tenant_id=COALESCE(documents.tenant_id, excluded.tenant_id),
            workspace_id=COALESCE(documents.workspace_id, excluded.workspace_id)
    """, (
        values["id"], scope.tenant_id if scope else values.get("tenant_id"),
        scope.workspace_id if scope else values.get("workspace_id"),
        values.get("title", ""), values.get("owner_email", ""),
        values.get("mime_type", ""), values.get("created_at", ""),
        values.get("modified_at", ""), values.get("last_indexed_at", ""),
        values.get("web_url", ""),
    ))


def upsert_doc_link(conn, src_id, dst_id, first_seen, last_seen, scope=None):
    conflict = conflict_target(conn, ["src_id", "dst_id"], ["tenant_id", "workspace_id", "src_id", "dst_id"])
    execute(conn, f"""
        INSERT INTO doc_links (tenant_id, workspace_id, src_id, dst_id, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT{conflict} DO UPDATE SET
            last_seen=excluded.last_seen,
            tenant_id=COALESCE(doc_links.tenant_id, excluded.tenant_id),
            workspace_id=COALESCE(doc_links.workspace_id, excluded.workspace_id)
    """, (
        scope.tenant_id if scope else None,
        scope.workspace_id if scope else None,
        src_id, dst_id, first_seen, last_seen,
    ))


def ensure_external_resource(conn, values, scope=None):
    conflict = conflict_target(conn, ["id"], ["tenant_id", "workspace_id", "id"])
    execute(conn, f"""
        INSERT INTO external_resources (
            id, tenant_id, workspace_id, url, domain, apex_domain, resource_type
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT{conflict} DO UPDATE SET
            url=excluded.url,
            domain=excluded.domain,
            apex_domain=excluded.apex_domain,
            resource_type=excluded.resource_type,
            tenant_id=COALESCE(external_resources.tenant_id, excluded.tenant_id),
            workspace_id=COALESCE(external_resources.workspace_id, excluded.workspace_id)
    """, (
        values["id"], scope.tenant_id if scope else values.get("tenant_id"),
        scope.workspace_id if scope else values.get("workspace_id"),
        values.get("url", ""), values.get("domain", ""),
        values.get("apex_domain", ""), values.get("resource_type", ""),
    ))


def upsert_external_link(conn, src_id, resource_id, anchor_text, first_seen, last_seen, scope=None):
    conflict = conflict_target(conn, ["src_id", "resource_id"], ["tenant_id", "workspace_id", "src_id", "resource_id"])
    execute(conn, f"""
        INSERT INTO external_links (
            tenant_id, workspace_id, src_id, resource_id, anchor_text, first_seen, last_seen
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT{conflict} DO UPDATE SET
            anchor_text=excluded.anchor_text,
            last_seen=excluded.last_seen,
            tenant_id=COALESCE(external_links.tenant_id, excluded.tenant_id),
            workspace_id=COALESCE(external_links.workspace_id, excluded.workspace_id)
    """, (
        scope.tenant_id if scope else None,
        scope.workspace_id if scope else None,
        src_id, resource_id, anchor_text, first_seen, last_seen,
    ))


def upsert_activity_snapshot(conn, document_id, date, counts, scope=None):
    conflict = conflict_target(conn, ["document_id", "date"], ["tenant_id", "workspace_id", "document_id", "date"])
    execute(conn, f"""
        INSERT INTO activity_snapshots (
            tenant_id, workspace_id, document_id, date, views, edits, comments
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT{conflict} DO UPDATE SET
            views=excluded.views,
            edits=excluded.edits,
            comments=excluded.comments,
            tenant_id=COALESCE(activity_snapshots.tenant_id, excluded.tenant_id),
            workspace_id=COALESCE(activity_snapshots.workspace_id, excluded.workspace_id)
    """, (
        scope.tenant_id if scope else None,
        scope.workspace_id if scope else None,
        document_id, date, counts["views"], counts["edits"], counts["comments"],
    ))


def ensure_person(conn, person_id, email="", display_name="", scope=None):
    conflict = conflict_target(conn, ["id"], ["tenant_id", "workspace_id", "id"])
    execute(conn, f"""
        INSERT INTO persons (id, tenant_id, workspace_id, email, display_name)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT{conflict} DO UPDATE SET
            email=COALESCE(NULLIF(excluded.email, ''), persons.email),
            display_name=COALESCE(NULLIF(excluded.display_name, ''), persons.display_name),
            tenant_id=COALESCE(persons.tenant_id, excluded.tenant_id),
            workspace_id=COALESCE(persons.workspace_id, excluded.workspace_id)
    """, (
        person_id, scope.tenant_id if scope else None,
        scope.workspace_id if scope else None, email, display_name,
    ))


def increment_person_activity(conn, person_id, document_id, action, last_seen, scope=None):
    conflict = conflict_target(
        conn,
        ["person_id", "document_id", "action"],
        ["tenant_id", "workspace_id", "person_id", "document_id", "action"],
    )
    execute(conn, f"""
        INSERT INTO person_activity (
            tenant_id, workspace_id, person_id, document_id, action, last_seen, count
        )
        VALUES (?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT{conflict} DO UPDATE SET
            count=count+1,
            last_seen=MAX(last_seen, excluded.last_seen),
            tenant_id=COALESCE(person_activity.tenant_id, excluded.tenant_id),
            workspace_id=COALESCE(person_activity.workspace_id, excluded.workspace_id)
    """, (
        scope.tenant_id if scope else None,
        scope.workspace_id if scope else None,
        person_id, document_id, action, last_seen,
    ))


def upsert_person_activity(conn, person_id, document_id, action, last_seen, count, scope=None):
    conflict = conflict_target(
        conn,
        ["person_id", "document_id", "action"],
        ["tenant_id", "workspace_id", "person_id", "document_id", "action"],
    )
    execute(conn, f"""
        INSERT INTO person_activity (
            tenant_id, workspace_id, person_id, document_id, action, last_seen, count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT{conflict} DO UPDATE SET
            count=excluded.count,
            last_seen=excluded.last_seen,
            tenant_id=COALESCE(person_activity.tenant_id, excluded.tenant_id),
            workspace_id=COALESCE(person_activity.workspace_id, excluded.workspace_id)
    """, (
        scope.tenant_id if scope else None,
        scope.workspace_id if scope else None,
        person_id, document_id, action, last_seen, count,
    ))


def linked_unindexed_doc_ids(conn, scope=None):
    if not scope:
        rows = execute(conn, """
            SELECT DISTINCT dl.dst_id FROM doc_links dl
            LEFT JOIN documents d ON dl.dst_id = d.id
            WHERE d.id IS NULL
        """).fetchall()
        return [row["dst_id"] for row in rows]
    scope_sql, scope_params = where_scope(scope, alias="dl")
    rows = execute(conn, """
        SELECT DISTINCT dl.dst_id FROM doc_links dl
        LEFT JOIN documents d ON dl.dst_id = d.id
            AND (dl.tenant_id IS NULL OR d.tenant_id = dl.tenant_id)
            AND (dl.workspace_id IS NULL OR d.workspace_id = dl.workspace_id)
        {scope_sql}
        AND d.id IS NULL
    """.format(scope_sql=scope_sql), scope_params).fetchall()
    return [row["dst_id"] for row in rows]


def unresolved_person_ids(conn, scope=None):
    scope_sql, scope_params = where_scope(scope)
    rows = execute(conn,
        "SELECT id FROM persons {scope_sql} AND (email='' OR display_name='')".format(scope_sql=scope_sql),
        scope_params,
    ).fetchall() if scope else execute(conn,
        "SELECT id FROM persons WHERE email='' OR display_name=''"
    ).fetchall()
    return [row["id"] for row in rows]


def update_person_identity(conn, person_id, display_name, email, scope=None):
    scope_sql, scope_params = and_scope(scope)
    execute(conn,
        "UPDATE persons SET display_name=?, email=? WHERE id=? {scope_sql}".format(scope_sql=scope_sql),
        [display_name, email, person_id] + scope_params,
    )


def external_resource_rows(conn, scope=None):
    scope_sql, scope_params = where_scope(scope)
    return execute(conn, f"SELECT id, url FROM external_resources {scope_sql}", scope_params).fetchall()


def update_external_resource_classification(conn, resource_id, domain, apex_domain, resource_type, scope=None):
    scope_sql, scope_params = and_scope(scope)
    execute(conn, """
        UPDATE external_resources
        SET domain=?, apex_domain=?, resource_type=?
        WHERE id=? {scope_sql}
    """.format(scope_sql=scope_sql), [domain, apex_domain, resource_type, resource_id] + scope_params)


def delete_doc_terms(conn, doc_id, scope=None):
    scope_sql, scope_params = and_scope(scope)
    execute(conn,
        "DELETE FROM doc_terms WHERE doc_id = ? {scope_sql}".format(scope_sql=scope_sql),
        [doc_id] + scope_params,
    )


def upsert_doc_term(conn, doc_id, term, frequency, term_type, scope=None):
    conflict = conflict_target(conn, ["doc_id", "term"], ["tenant_id", "workspace_id", "doc_id", "term"])
    execute(conn, f"""
        INSERT INTO doc_terms (tenant_id, workspace_id, doc_id, term, frequency, term_type)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT{conflict} DO UPDATE SET
            frequency=excluded.frequency,
            term_type=excluded.term_type,
            tenant_id=COALESCE(doc_terms.tenant_id, excluded.tenant_id),
            workspace_id=COALESCE(doc_terms.workspace_id, excluded.workspace_id)
    """, (
        scope.tenant_id if scope else None,
        scope.workspace_id if scope else None,
        doc_id, term, frequency, term_type,
    ))


def top_doc_terms(conn, doc_id, top_n=30, scope=None):
    scope_sql, scope_params = and_scope(scope)
    rows = execute(conn,
        "SELECT term FROM doc_terms WHERE doc_id = ? {scope_sql} ORDER BY frequency DESC LIMIT ?".format(scope_sql=scope_sql),
        [doc_id] + scope_params + [top_n],
    ).fetchall()
    return {row["term"] for row in rows}


def doc_term_frequencies(conn, doc_id, terms, scope=None):
    if not terms:
        return []
    scope_sql, scope_params = and_scope(scope)
    placeholders = ",".join("?" * len(terms))
    rows = execute(conn,
        f"SELECT term, frequency FROM doc_terms WHERE doc_id = ? AND term IN ({placeholders}) {scope_sql}",
        [doc_id] + list(terms) + scope_params,
    ).fetchall()
    return [dict(row) for row in rows]


def doc_link_pairs(conn, scope=None):
    scope_sql, scope_params = where_scope(scope)
    rows = execute(conn,
        f"SELECT DISTINCT src_id, dst_id FROM doc_links {scope_sql}",
        scope_params,
    ).fetchall()
    return [dict(row) for row in rows]


def inbound_link_counts(conn, scope=None):
    scope_sql, scope_params = where_scope(scope)
    rows = execute(conn,
        f"SELECT dst_id AS doc_id, COUNT(*) AS cnt FROM doc_links {scope_sql} GROUP BY dst_id",
        scope_params,
    ).fetchall()
    return {row["doc_id"]: row["cnt"] for row in rows}


def upsert_doc_alignment(conn, values, scope=None):
    conflict = conflict_target(conn, ["src_id", "dst_id"], ["tenant_id", "workspace_id", "src_id", "dst_id"])
    execute(conn, f"""
        INSERT INTO doc_alignment (
            tenant_id, workspace_id, src_id, dst_id, alignment_score,
            shared_terms, divergent_terms, computed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT{conflict} DO UPDATE SET
            alignment_score=excluded.alignment_score,
            shared_terms=excluded.shared_terms,
            divergent_terms=excluded.divergent_terms,
            computed_at=excluded.computed_at,
            tenant_id=COALESCE(doc_alignment.tenant_id, excluded.tenant_id),
            workspace_id=COALESCE(doc_alignment.workspace_id, excluded.workspace_id)
    """, (
        scope.tenant_id if scope else values.get("tenant_id"),
        scope.workspace_id if scope else values.get("workspace_id"),
        values["src_id"], values["dst_id"], values["alignment_score"],
        values["shared_terms"], values["divergent_terms"], values["computed_at"],
    ))
