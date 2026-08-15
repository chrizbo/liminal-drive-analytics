"""Tests for DB schema, migrations, and graph construction."""
import sys, os, sqlite3, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Redirect DB_PATH to a temp file for each test."""
    import db as db_module
    db_path = str(tmp_path / "test_graph.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    return db_path


# ── Schema init ───────────────────────────────────────────────────────────────

def test_init_creates_tables(tmp_db):
    import db
    conn = db.connect()
    db.init(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "users" in tables
    assert "tenants" in tables
    assert "memberships" in tables
    assert "workspaces" in tables
    assert "documents" in tables
    assert "doc_links" in tables
    assert "external_resources" in tables
    assert "activity_snapshots" in tables
    assert "persons" in tables
    assert "findings" in tables
    assert "finding_review_events" in tables
    assert "briefs" in tables
    assert "indexing_jobs" in tables
    assert "crawl_schedules" in tables
    assert "analytics_events" in tables
    assert "google_connections" in tables
    conn.close()


def test_customer_owned_tables_have_tenant_workspace_columns(tmp_db):
    import db
    conn = db.connect()
    db.init(conn)
    for table in (
        "documents", "persons", "external_resources", "doc_links",
        "external_links", "activity_snapshots", "person_activity",
        "findings", "finding_review_events", "briefs", "doc_terms",
        "doc_alignment", "indexing_jobs", "crawl_schedules",
        "analytics_events", "google_connections",
    ):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert {"tenant_id", "workspace_id"} <= cols
    conn.close()


def test_ensure_service_context_seeds_local_workspace(tmp_db):
    import db
    conn = db.connect()
    db.init(conn)
    db.ensure_service_context(conn, {
        "id": "live",
        "tenant_id": db.LOCAL_TENANT_ID,
        "tenant_name": "Local development",
        "tenant_kind": "local",
        "name": "Live Drive",
        "kind": "live",
        "database_path": tmp_db,
    })
    tenant = conn.execute("SELECT * FROM tenants WHERE id=?", (db.LOCAL_TENANT_ID,)).fetchone()
    workspace = conn.execute("SELECT * FROM workspaces WHERE id='live'").fetchone()
    membership = conn.execute("SELECT * FROM memberships WHERE tenant_id=?", (db.LOCAL_TENANT_ID,)).fetchone()
    assert tenant["name"] == "Local development"
    assert workspace["tenant_id"] == db.LOCAL_TENANT_ID
    assert membership["role"] == "owner"
    conn.close()


def test_storage_sql_placeholder_translation():
    from storage import dialect, sql_for_connection

    class FakePostgresConnection:
        dialect = "postgresql"

    class FakeSqliteConnection:
        dialect = "sqlite"

    sql = "SELECT * FROM documents WHERE tenant_id=? AND workspace_id=?"
    assert sql_for_connection(FakePostgresConnection(), sql).count("%s") == 2
    assert sql_for_connection(FakeSqliteConnection(), sql) == sql
    assert dialect(FakePostgresConnection()) == "postgresql"


def test_storage_sql_rewrites_sqlite_scalar_max_for_postgres():
    from storage import sql_for_connection

    class FakePostgresConnection:
        dialect = "postgresql"

    sql = "UPDATE person_activity SET last_seen=MAX(last_seen, excluded.last_seen) WHERE id=?"
    translated = sql_for_connection(FakePostgresConnection(), sql)
    assert "GREATEST(last_seen, excluded.last_seen)" in translated
    assert "%s" in translated


def test_storage_upserts_use_scoped_conflicts_for_postgres():
    from storage import StorageScope, upsert_activity_snapshot, upsert_doc_link, upsert_document

    class FakePostgresConnection:
        dialect = "postgresql"

        def __init__(self):
            self.statements = []

        def execute(self, sql, params=()):
            self.statements.append((sql, params))

    conn = FakePostgresConnection()
    scope = StorageScope("tenant-a", "workspace-a")

    upsert_document(conn, {
        "id": "doc-1",
        "title": "Doc",
        "owner_email": "owner@example.com",
        "mime_type": "application/vnd.google-apps.document",
        "created_at": "2026-01-01",
        "modified_at": "2026-01-02",
        "last_indexed_at": "2026-01-03",
        "web_url": "https://docs.google.com/document/d/doc-1",
    }, scope)
    upsert_doc_link(conn, "doc-1", "doc-2", "2026-01-01", "2026-01-02", scope)
    upsert_activity_snapshot(conn, "doc-1", "2026-01-03", {"views": 1, "edits": 2, "comments": 3}, scope)

    sql = "\n".join(statement for statement, _ in conn.statements)
    assert "ON CONFLICT(tenant_id, workspace_id, id)" in sql
    assert "ON CONFLICT(tenant_id, workspace_id, src_id, dst_id)" in sql
    assert "ON CONFLICT(tenant_id, workspace_id, document_id, date)" in sql
    assert "%s" in sql


def test_schema_sql_uses_postgres_identity_for_review_events():
    import db

    class FakePostgresConnection:
        dialect = "postgresql"

    sql = db.schema_sql(FakePostgresConnection())
    assert "BIGSERIAL PRIMARY KEY" in sql
    assert "AUTOINCREMENT" not in sql


def test_schema_sql_scopes_customer_uniqueness_for_postgres():
    import db

    class FakePostgresConnection:
        dialect = "postgresql"

    sql = db.schema_sql(FakePostgresConnection())

    assert "CREATE TABLE IF NOT EXISTS documents (\n            id TEXT," in sql
    assert "ON findings(tenant_id, workspace_id, document_id, signal_type) WHERE active = 1" in sql
    assert "ON findings(document_id, signal_type) WHERE active = 1" not in sql
    assert "ON documents(tenant_id, workspace_id, id)" in sql
    assert "ON doc_links(tenant_id, workspace_id, src_id, dst_id)" in sql
    assert "ON activity_snapshots(tenant_id, workspace_id, document_id, date)" in sql
    assert "PRIMARY KEY (src_id, dst_id)" not in sql


def test_connect_service_database_uses_database_url(monkeypatch):
    import db

    calls = []

    class FakePostgresConnection:
        dialect = "postgresql"

    monkeypatch.setenv(db.DATABASE_URL_ENV, "postgresql://localhost/drive_analytics")
    monkeypatch.setattr(db, "connect_postgres", lambda url: calls.append(url) or FakePostgresConnection())

    conn = db.connect_service_database()

    assert conn.dialect == "postgresql"
    assert calls == ["postgresql://localhost/drive_analytics"]


def test_init_skips_legacy_migrations_for_postgres():
    import db

    class FakePostgresConnection:
        dialect = "postgresql"

        def __init__(self):
            self.statements = []
            self.commits = 0

        def execute(self, sql, params=()):
            self.statements.append(sql)

        def commit(self):
            self.commits += 1

    conn = FakePostgresConnection()
    db.init(conn)

    assert any(statement.startswith("CREATE TABLE") for statement in conn.statements)
    assert not any(statement.startswith("ALTER TABLE") for statement in conn.statements)
    assert conn.commits == 1


def test_storage_helpers_scope_document_reads(tmp_db):
    import db
    from storage import (
        StorageScope, get_document_detail, list_workspace_documents,
        overview_counts,
    )

    conn = db.connect()
    db.init(conn)
    scope_a = StorageScope("tenant-a", "workspace-a")
    scope_b = StorageScope("tenant-b", "workspace-b")
    conn.execute("""
        INSERT INTO documents (
            id, tenant_id, workspace_id, title, mime_type, modified_at, web_url
        ) VALUES (
            'doc-a', 'tenant-a', 'workspace-a', 'Doc A',
            'application/vnd.google-apps.document', '2026-01-02',
            'https://docs.google.com/document/d/doc-a'
        )
    """)
    conn.execute("""
        INSERT INTO documents (
            id, tenant_id, workspace_id, title, modified_at
        ) VALUES ('doc-b', 'tenant-b', 'workspace-b', 'Doc B', '2026-01-03')
    """)
    conn.execute("""
        INSERT INTO persons (id, tenant_id, workspace_id, email, display_name)
        VALUES ('person-a', 'tenant-a', 'workspace-a', 'a@example.com', 'Person A')
    """)
    conn.execute("""
        INSERT INTO person_activity (
            tenant_id, workspace_id, person_id, document_id, action, last_seen, count
        ) VALUES ('tenant-a', 'workspace-a', 'person-a', 'doc-a', 'view', '2026-01-04', 3)
    """)
    conn.execute("""
        INSERT INTO activity_snapshots (
            tenant_id, workspace_id, document_id, date, views, edits, comments
        ) VALUES ('tenant-a', 'workspace-a', 'doc-a', '2026-01-04', 3, 1, 0)
    """)
    conn.execute("""
        INSERT INTO external_resources (
            id, tenant_id, workspace_id, url, domain, apex_domain, resource_type
        ) VALUES (
            'resource-a', 'tenant-a', 'workspace-a',
            'https://example.com/path', 'example.com', 'example.com', 'web'
        )
    """)
    conn.execute("""
        INSERT INTO external_links (
            tenant_id, workspace_id, src_id, resource_id, anchor_text, first_seen, last_seen
        ) VALUES ('tenant-a', 'workspace-a', 'doc-a', 'resource-a', 'Example', '', '')
    """)
    conn.commit()

    assert overview_counts(conn, scope_a)["documents_indexed"] == 1
    assert overview_counts(conn, scope_b)["documents_indexed"] == 1
    assert [doc["id"] for doc in list_workspace_documents(conn, scope_a)] == ["doc-a"]
    assert [doc["id"] for doc in list_workspace_documents(conn, scope_b)] == ["doc-b"]

    detail = get_document_detail(conn, "doc-a", scope_a)
    assert detail["title"] == "Doc A"
    assert detail["contributors"][0]["display_name"] == "Person A"
    assert detail["activity_history"][0]["views"] == 3
    assert detail["external_links"][0]["domain"] == "example.com"
    assert get_document_detail(conn, "doc-a", scope_b) is None
    conn.close()

def test_init_is_idempotent(tmp_db):
    import db
    conn = db.connect()
    db.init(conn)
    db.init(conn)  # second call should not raise
    conn.close()

def test_migration_adds_web_url(tmp_db):
    import db
    # Create old-style DB without web_url
    conn = sqlite3.connect(tmp_db)
    conn.execute("""CREATE TABLE documents (
        id TEXT PRIMARY KEY, title TEXT, owner_email TEXT,
        mime_type TEXT, created_at TEXT, modified_at TEXT, last_indexed_at TEXT
    )""")
    conn.commit()
    conn.close()
    # Now init should add the column via migration
    conn = db.connect()
    db.init(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    assert "web_url" in cols
    conn.close()

def test_migration_adds_apex_domain(tmp_db):
    import db
    conn = sqlite3.connect(tmp_db)
    conn.execute("""CREATE TABLE external_resources (
        id TEXT PRIMARY KEY, url TEXT, domain TEXT, resource_type TEXT
    )""")
    conn.commit()
    conn.close()
    conn = db.connect()
    db.init(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(external_resources)")}
    assert "apex_domain" in cols
    conn.close()


# ── Graph construction ────────────────────────────────────────────────────────

def test_graph_builds_from_db(tmp_db):
    import db, graph as graph_module
    conn = db.connect()
    db.init(conn)

    # Insert two docs and a link between them
    conn.execute("""INSERT INTO documents (id, title, mime_type, created_at, modified_at, last_indexed_at)
                    VALUES ('doc1','Doc One','application/vnd.google-apps.document','','','')""")
    conn.execute("""INSERT INTO documents (id, title, mime_type, created_at, modified_at, last_indexed_at)
                    VALUES ('doc2','Doc Two','application/vnd.google-apps.document','','','')""")
    conn.execute("INSERT INTO doc_links (src_id, dst_id, first_seen, last_seen) VALUES ('doc1','doc2','','') ")
    conn.commit()

    G = graph_module.build_doc_graph(conn)
    assert G.number_of_nodes() >= 2
    assert G.has_edge("doc1", "doc2")
    conn.close()

def test_in_degree_rank_ordering(tmp_db):
    import db, graph as graph_module
    conn = db.connect()
    db.init(conn)

    for i in range(4):
        conn.execute(f"""INSERT INTO documents (id,title,mime_type,created_at,modified_at,last_indexed_at)
                         VALUES ('d{i}','Doc {i}','','','','')""")
    # d3 gets 2 inbound links, d2 gets 1
    conn.execute("INSERT INTO doc_links (src_id, dst_id, first_seen, last_seen) VALUES ('d0','d3','','') ")
    conn.execute("INSERT INTO doc_links (src_id, dst_id, first_seen, last_seen) VALUES ('d1','d3','','') ")
    conn.execute("INSERT INTO doc_links (src_id, dst_id, first_seen, last_seen) VALUES ('d0','d2','','') ")
    conn.commit()

    G = graph_module.build_doc_graph(conn)
    ranked = graph_module.in_degree_rank(G)
    top_id, top_deg = ranked[0]
    assert top_id == "d3"
    assert top_deg == 2
    conn.close()

def test_empty_graph(tmp_db):
    import db, graph as graph_module
    conn = db.connect()
    db.init(conn)
    G = graph_module.build_doc_graph(conn)
    assert G.number_of_nodes() == 0
    conn.close()


def test_connect_accepts_explicit_database_path(tmp_path):
    import db
    explicit = str(tmp_path / "explicit.db")
    conn = db.connect(explicit)
    db.init(conn)
    conn.execute("INSERT INTO persons (id, email, display_name) VALUES ('p', '', 'Person')")
    conn.commit()
    conn.close()
    assert os.path.exists(explicit)
