"""Database schema and connection helpers."""

import os
import sqlite3

from storage import dialect, execute

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "graph.db")
DEMO_DB_PATH = os.path.join(ROOT, "data", "demo_graph.db")
DATABASE_URL_ENV = "DRIVE_ANALYTICS_DATABASE_URL"

LOCAL_TENANT_ID = "tenant:local"
DEMO_TENANT_ID = "tenant:demo"
LOCAL_USER_ID = "user:local"

CUSTOMER_TABLES = (
    "documents",
    "persons",
    "external_resources",
    "doc_links",
    "external_links",
    "activity_snapshots",
    "person_activity",
    "findings",
    "finding_review_events",
    "briefs",
    "indexing_jobs",
    "crawl_schedules",
    "analytics_events",
    "google_connections",
    "doc_terms",
    "doc_alignment",
)


def connect(path=None):
    db_path = path or DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def service_database_url():
    return os.environ.get(DATABASE_URL_ENV, "").strip()


class PostgresConnection:
    dialect = "postgresql"

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        return self._conn.execute(sql, params)

    def commit(self):
        return self._conn.commit()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def connect_postgres(url):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL support requires psycopg. Install dependencies with "
            "`pip3 install -r requirements.txt`."
        ) from exc
    return PostgresConnection(psycopg.connect(url, row_factory=dict_row))


def connect_service_database():
    url = service_database_url()
    if url:
        return connect_postgres(url)
    return connect()


def _sqlite_schema_sql():
    return """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT,
            display_name TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'local',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS memberships (
            user_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT,
            PRIMARY KEY (user_id, tenant_id)
        );

        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            database_path TEXT,
            source_id TEXT,
            indexed_at TEXT,
            last_successful_crawl_at TEXT,
            last_attempted_crawl_at TEXT,
            next_scheduled_crawl_at TEXT,
            crawl_cursor TEXT,
            crawl_mode TEXT,
            crawl_health TEXT,
            failure_reason TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS indexing_jobs (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            workspace_id TEXT,
            workspace_name TEXT,
            status TEXT NOT NULL,
            phase TEXT,
            message TEXT,
            current INTEGER,
            total INTEGER,
            progress INTEGER,
            document_title TEXT,
            days INTEGER,
            expand INTEGER,
            result_json TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS crawl_schedules (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            workspace_id TEXT,
            enabled INTEGER NOT NULL DEFAULT 0,
            schedule_cron TEXT,
            schedule_timezone TEXT,
            crawl_mode TEXT,
            next_run_at TEXT,
            paused_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_crawl_schedules_workspace
        ON crawl_schedules(tenant_id, workspace_id);

        CREATE TABLE IF NOT EXISTS analytics_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            workspace_id TEXT,
            event_type TEXT NOT NULL,
            finding_id TEXT,
            document_id TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS google_connections (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            workspace_id TEXT,
            provider TEXT NOT NULL DEFAULT 'google',
            account_email TEXT,
            status TEXT NOT NULL DEFAULT 'disconnected',
            granted_scopes_json TEXT,
            token_encrypted TEXT,
            token_version TEXT,
            connected_at TEXT,
            disconnected_at TEXT,
            last_checked_at TEXT,
            health TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_google_connections_workspace_provider
        ON google_connections(tenant_id, workspace_id, provider);

        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            workspace_id TEXT,
            title TEXT,
            owner_email TEXT,
            mime_type TEXT,
            created_at TEXT,
            modified_at TEXT,
            last_indexed_at TEXT,
            web_url TEXT
        );

        CREATE TABLE IF NOT EXISTS persons (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            workspace_id TEXT,
            email TEXT,
            display_name TEXT
        );

        CREATE TABLE IF NOT EXISTS external_resources (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            workspace_id TEXT,
            url TEXT,
            domain TEXT,
            apex_domain TEXT,
            resource_type TEXT
        );

        CREATE TABLE IF NOT EXISTS doc_links (
            tenant_id TEXT,
            workspace_id TEXT,
            src_id TEXT,
            dst_id TEXT,
            first_seen TEXT,
            last_seen TEXT,
            PRIMARY KEY (src_id, dst_id)
        );

        CREATE TABLE IF NOT EXISTS external_links (
            tenant_id TEXT,
            workspace_id TEXT,
            src_id TEXT,
            resource_id TEXT,
            anchor_text TEXT,
            first_seen TEXT,
            last_seen TEXT,
            PRIMARY KEY (src_id, resource_id)
        );

        CREATE TABLE IF NOT EXISTS activity_snapshots (
            tenant_id TEXT,
            workspace_id TEXT,
            document_id TEXT,
            date TEXT,
            views INTEGER DEFAULT 0,
            edits INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            PRIMARY KEY (document_id, date)
        );

        CREATE TABLE IF NOT EXISTS person_activity (
            tenant_id TEXT,
            workspace_id TEXT,
            person_id TEXT,
            document_id TEXT,
            action TEXT,
            last_seen TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (person_id, document_id, action)
        );

        CREATE TABLE IF NOT EXISTS findings (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            workspace_id TEXT,
            document_id TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            score INTEGER NOT NULL,
            severity TEXT NOT NULL,
            suggested_action TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            first_detected_at TEXT NOT NULL,
            last_detected_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'new',
            disposition TEXT,
            reviewer TEXT,
            assignee TEXT,
            note TEXT,
            follow_up_date TEXT,
            reviewed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_findings_active_signal
        ON findings(document_id, signal_type) WHERE active = 1;

        CREATE TABLE IF NOT EXISTS finding_review_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT,
            workspace_id TEXT,
            finding_id TEXT NOT NULL,
            status TEXT NOT NULL,
            disposition TEXT,
            reviewer TEXT,
            assignee TEXT,
            note TEXT,
            follow_up_date TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS briefs (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            workspace_id TEXT,
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            deterministic_json TEXT NOT NULL,
            polished_json TEXT,
            model TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS doc_terms (
            tenant_id TEXT,
            workspace_id TEXT,
            doc_id    TEXT NOT NULL,
            term      TEXT NOT NULL,
            frequency INTEGER DEFAULT 1,
            term_type TEXT,
            PRIMARY KEY (doc_id, term)
        );

        CREATE TABLE IF NOT EXISTS doc_alignment (
            tenant_id TEXT,
            workspace_id TEXT,
            src_id          TEXT NOT NULL,
            dst_id          TEXT NOT NULL,
            alignment_score REAL,
            shared_terms    TEXT,
            divergent_terms TEXT,
            computed_at     TEXT,
            PRIMARY KEY (src_id, dst_id)
        );
    """


POSTGRES_SCOPED_UNIQUE_INDEXES = """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_scope_id
        ON documents(tenant_id, workspace_id, id);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_persons_scope_id
        ON persons(tenant_id, workspace_id, id);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_external_resources_scope_id
        ON external_resources(tenant_id, workspace_id, id);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_links_scope_pair
        ON doc_links(tenant_id, workspace_id, src_id, dst_id);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_external_links_scope_pair
        ON external_links(tenant_id, workspace_id, src_id, resource_id);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_activity_snapshots_scope_doc_date
        ON activity_snapshots(tenant_id, workspace_id, document_id, date);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_person_activity_scope_action
        ON person_activity(tenant_id, workspace_id, person_id, document_id, action);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_terms_scope_term
        ON doc_terms(tenant_id, workspace_id, doc_id, term);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_alignment_scope_pair
        ON doc_alignment(tenant_id, workspace_id, src_id, dst_id);
"""


def _postgres_schema_sql():
    sql = _sqlite_schema_sql()
    replacements = {
        "CREATE TABLE IF NOT EXISTS documents (\n            id TEXT PRIMARY KEY,":
            "CREATE TABLE IF NOT EXISTS documents (\n            id TEXT,",
        "CREATE TABLE IF NOT EXISTS persons (\n            id TEXT PRIMARY KEY,":
            "CREATE TABLE IF NOT EXISTS persons (\n            id TEXT,",
        "CREATE TABLE IF NOT EXISTS external_resources (\n            id TEXT PRIMARY KEY,":
            "CREATE TABLE IF NOT EXISTS external_resources (\n            id TEXT,",
        ",\n            PRIMARY KEY (src_id, dst_id)": "",
        ",\n            PRIMARY KEY (src_id, resource_id)": "",
        ",\n            PRIMARY KEY (document_id, date)": "",
        ",\n            PRIMARY KEY (person_id, document_id, action)": "",
        ",\n            PRIMARY KEY (doc_id, term)": "",
        "id INTEGER PRIMARY KEY AUTOINCREMENT": "id BIGSERIAL PRIMARY KEY",
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_findings_active_signal
        ON findings(document_id, signal_type) WHERE active = 1;""":
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_findings_active_signal
        ON findings(tenant_id, workspace_id, document_id, signal_type) WHERE active = 1;""",
    }
    for old, new in replacements.items():
        sql = sql.replace(old, new)
    return f"{sql}\n{POSTGRES_SCOPED_UNIQUE_INDEXES}"


def schema_sql(conn):
    if dialect(conn) in {"postgres", "postgresql"}:
        return _postgres_schema_sql()
    return _sqlite_schema_sql()


def init(conn):
    if dialect(conn) == "sqlite":
        conn.executescript(schema_sql(conn))
    else:
        statements = [statement.strip() for statement in schema_sql(conn).split(";") if statement.strip()]
        for statement in statements:
            execute(conn, statement)
    conn.commit()

    if dialect(conn) != "sqlite":
        return

    # SQLite migrations — safe to run on existing local DBs.
    migrations = sqlite_migrations()
    for sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass  # column already exists


def sqlite_migrations():
    return [
        "ALTER TABLE documents ADD COLUMN web_url TEXT",
        "ALTER TABLE external_resources ADD COLUMN apex_domain TEXT",
        "ALTER TABLE documents ADD COLUMN tenant_id TEXT",
        "ALTER TABLE documents ADD COLUMN workspace_id TEXT",
        "ALTER TABLE persons ADD COLUMN tenant_id TEXT",
        "ALTER TABLE persons ADD COLUMN workspace_id TEXT",
        "ALTER TABLE external_resources ADD COLUMN tenant_id TEXT",
        "ALTER TABLE external_resources ADD COLUMN workspace_id TEXT",
        "ALTER TABLE doc_links ADD COLUMN tenant_id TEXT",
        "ALTER TABLE doc_links ADD COLUMN workspace_id TEXT",
        "ALTER TABLE external_links ADD COLUMN tenant_id TEXT",
        "ALTER TABLE external_links ADD COLUMN workspace_id TEXT",
        "ALTER TABLE activity_snapshots ADD COLUMN tenant_id TEXT",
        "ALTER TABLE activity_snapshots ADD COLUMN workspace_id TEXT",
        "ALTER TABLE person_activity ADD COLUMN tenant_id TEXT",
        "ALTER TABLE person_activity ADD COLUMN workspace_id TEXT",
        "ALTER TABLE findings ADD COLUMN tenant_id TEXT",
        "ALTER TABLE findings ADD COLUMN workspace_id TEXT",
        "ALTER TABLE finding_review_events ADD COLUMN tenant_id TEXT",
        "ALTER TABLE finding_review_events ADD COLUMN workspace_id TEXT",
        "ALTER TABLE briefs ADD COLUMN tenant_id TEXT",
        "ALTER TABLE briefs ADD COLUMN workspace_id TEXT",
        "ALTER TABLE indexing_jobs ADD COLUMN tenant_id TEXT",
        "ALTER TABLE indexing_jobs ADD COLUMN workspace_id TEXT",
        "ALTER TABLE workspaces ADD COLUMN last_successful_crawl_at TEXT",
        "ALTER TABLE workspaces ADD COLUMN last_attempted_crawl_at TEXT",
        "ALTER TABLE workspaces ADD COLUMN next_scheduled_crawl_at TEXT",
        "ALTER TABLE workspaces ADD COLUMN crawl_cursor TEXT",
        "ALTER TABLE workspaces ADD COLUMN crawl_mode TEXT",
        "ALTER TABLE workspaces ADD COLUMN crawl_health TEXT",
        "ALTER TABLE workspaces ADD COLUMN failure_reason TEXT",
        "ALTER TABLE crawl_schedules ADD COLUMN tenant_id TEXT",
        "ALTER TABLE crawl_schedules ADD COLUMN workspace_id TEXT",
        "ALTER TABLE analytics_events ADD COLUMN tenant_id TEXT",
        "ALTER TABLE analytics_events ADD COLUMN workspace_id TEXT",
        "ALTER TABLE google_connections ADD COLUMN tenant_id TEXT",
        "ALTER TABLE google_connections ADD COLUMN workspace_id TEXT",
        "ALTER TABLE doc_terms ADD COLUMN tenant_id TEXT",
        "ALTER TABLE doc_terms ADD COLUMN workspace_id TEXT",
        "ALTER TABLE doc_alignment ADD COLUMN tenant_id TEXT",
        "ALTER TABLE doc_alignment ADD COLUMN workspace_id TEXT",
    ]


def ensure_service_context(conn, workspace):
    """Seed local service-model rows for a workspace-backed SQLite database."""
    tenant_id = workspace.get("tenant_id") or LOCAL_TENANT_ID
    workspace_id = workspace["id"]
    now = workspace.get("indexed_at") or ""
    execute(conn, """
        INSERT INTO tenants (id, name, kind, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO NOTHING
    """, (tenant_id, workspace.get("tenant_name") or "Local development", workspace.get("tenant_kind") or "local", now))
    execute(conn, """
        INSERT INTO users (id, email, display_name, created_at)
        VALUES (?, '', 'Local user', ?)
        ON CONFLICT(id) DO NOTHING
    """, (LOCAL_USER_ID, now))
    execute(conn, """
        INSERT INTO memberships (user_id, tenant_id, role, created_at)
        VALUES (?, ?, 'owner', ?)
        ON CONFLICT(user_id, tenant_id) DO NOTHING
    """, (LOCAL_USER_ID, tenant_id, now))
    execute(conn, """
        INSERT INTO workspaces (
            id, tenant_id, name, kind, database_path, source_id, indexed_at,
            last_successful_crawl_at, crawl_health, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            tenant_id=excluded.tenant_id,
            name=excluded.name,
            kind=excluded.kind,
            database_path=excluded.database_path,
            source_id=excluded.source_id,
            indexed_at=COALESCE(excluded.indexed_at, workspaces.indexed_at),
            last_successful_crawl_at=COALESCE(
                excluded.last_successful_crawl_at,
                workspaces.last_successful_crawl_at
            ),
            crawl_health=COALESCE(workspaces.crawl_health, excluded.crawl_health)
    """, (
        workspace_id, tenant_id, workspace["name"], workspace["kind"],
        workspace.get("database_path"), workspace.get("source_id"),
        workspace.get("indexed_at"), workspace.get("indexed_at"),
        workspace.get("crawl_health") or "healthy", now,
    ))
    conn.commit()


def update_workspace_crawl_state(conn, tenant_id, workspace_id, values):
    allowed = {
        "indexed_at", "last_successful_crawl_at", "last_attempted_crawl_at",
        "next_scheduled_crawl_at", "crawl_cursor", "crawl_mode",
        "crawl_health", "failure_reason",
    }
    columns = []
    params = []
    for key, value in values.items():
        if key not in allowed:
            continue
        columns.append(f"{key} = ?")
        params.append(value)
    if not columns:
        return
    execute(conn, f"""
        UPDATE workspaces
        SET {", ".join(columns)}
        WHERE tenant_id = ? AND id = ?
    """, params + [tenant_id, workspace_id])
    conn.commit()


def workspace_state(conn, tenant_id, workspace_id):
    row = execute(conn, """
        SELECT indexed_at, last_successful_crawl_at, last_attempted_crawl_at,
               next_scheduled_crawl_at, crawl_cursor, crawl_mode, crawl_health,
               failure_reason
        FROM workspaces
        WHERE tenant_id = ? AND id = ?
    """, (tenant_id, workspace_id)).fetchone()
    return dict(row) if row else {}


def stamp_workspace_rows(conn, tenant_id, workspace_id):
    """Backfill tenant/workspace IDs on legacy rows in a workspace database."""
    for table in CUSTOMER_TABLES:
        execute(conn, f"""
            UPDATE {table}
            SET tenant_id = COALESCE(tenant_id, ?),
                workspace_id = COALESCE(workspace_id, ?)
            WHERE tenant_id IS NULL OR workspace_id IS NULL
        """, (tenant_id, workspace_id))
    conn.commit()
