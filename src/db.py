"""SQLite schema and helpers."""

import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "graph.db")


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    """)
    conn.commit()

    # Migrations — safe to run on existing DBs
    migrations = [
        "ALTER TABLE documents ADD COLUMN web_url TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass  # column already exists
