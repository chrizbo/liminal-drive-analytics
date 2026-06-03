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
    assert "documents" in tables
    assert "doc_links" in tables
    assert "external_resources" in tables
    assert "activity_snapshots" in tables
    assert "persons" in tables
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
    conn.execute("INSERT INTO doc_links VALUES ('d0','d3','','') ")
    conn.execute("INSERT INTO doc_links VALUES ('d1','d3','','') ")
    conn.execute("INSERT INTO doc_links VALUES ('d0','d2','','') ")
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
