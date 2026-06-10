"""SQLite schema and helpers."""

import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "graph.db")
DEMO_DB_PATH = os.path.join(ROOT, "data", "demo_graph.db")


def connect(path=None):
    db_path = path or DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
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
            email TEXT,
            display_name TEXT
        );

        CREATE TABLE IF NOT EXISTS external_resources (
            id TEXT PRIMARY KEY,
            url TEXT,
            domain TEXT,
            apex_domain TEXT,
            resource_type TEXT
        );

        CREATE TABLE IF NOT EXISTS doc_links (
            src_id TEXT,
            dst_id TEXT,
            first_seen TEXT,
            last_seen TEXT,
            PRIMARY KEY (src_id, dst_id)
        );

        CREATE TABLE IF NOT EXISTS external_links (
            src_id TEXT,
            resource_id TEXT,
            anchor_text TEXT,
            first_seen TEXT,
            last_seen TEXT,
            PRIMARY KEY (src_id, resource_id)
        );

        CREATE TABLE IF NOT EXISTS activity_snapshots (
            document_id TEXT,
            date TEXT,
            views INTEGER DEFAULT 0,
            edits INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            PRIMARY KEY (document_id, date)
        );

        CREATE TABLE IF NOT EXISTS person_activity (
            person_id TEXT,
            document_id TEXT,
            action TEXT,
            last_seen TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (person_id, document_id, action)
        );

        CREATE TABLE IF NOT EXISTS findings (
            id TEXT PRIMARY KEY,
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
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            deterministic_json TEXT NOT NULL,
            polished_json TEXT,
            model TEXT,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()

    # Migrations — safe to run on existing DBs
    migrations = [
        "ALTER TABLE documents ADD COLUMN web_url TEXT",
        "ALTER TABLE external_resources ADD COLUMN apex_domain TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass  # column already exists
