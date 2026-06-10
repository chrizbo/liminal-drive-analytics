"""Workspace source helpers for isolated Shared Drive indexes."""

import json
import os
import re
from datetime import datetime, timezone

from db import ROOT


SOURCES_PATH = os.path.join(ROOT, "data", "sources.json")
DRIVE_ID_RE = re.compile(r"/folders/([a-zA-Z0-9_-]+)")


def extract_drive_item_id(value):
    """Return a Shared Drive or folder ID from a raw ID or Drive folder URL."""
    match = DRIVE_ID_RE.search(value or "")
    return match.group(1) if match else (value or "").strip()


def shared_drive_db_path(drive_id):
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", drive_id)
    return os.path.join(ROOT, "data", f"shared_drive_{safe_id}.db")


def resolve_shared_drive(drive_svc, value):
    """Resolve a Shared Drive root URL/ID or a folder inside a Shared Drive."""
    item_id = extract_drive_item_id(value)
    if not item_id:
        raise ValueError("Shared Drive URL or ID is required")
    try:
        drive = drive_svc.drives().get(driveId=item_id, fields="id,name").execute()
        return {"id": drive["id"], "name": drive["name"]}
    except Exception:
        item = drive_svc.files().get(
            fileId=item_id,
            fields="id,name,driveId",
            supportsAllDrives=True,
        ).execute()
        drive_id = item.get("driveId")
        if not drive_id:
            raise ValueError("The selected folder is not inside a Shared Drive")
        drive = drive_svc.drives().get(driveId=drive_id, fields="id,name").execute()
        return {"id": drive["id"], "name": drive["name"]}


def load_sources(path=SOURCES_PATH):
    try:
        with open(path) as source_file:
            return json.load(source_file).get("shared_drives", [])
    except Exception:
        return []


def register_shared_drive(drive_id, name, database_path=None, registry_path=SOURCES_PATH):
    sources = load_sources(registry_path)
    entry = {
        "id": drive_id,
        "name": name,
        "database_path": database_path or shared_drive_db_path(drive_id),
        "indexed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    sources = [source for source in sources if source.get("id") != drive_id]
    sources.append(entry)
    sources.sort(key=lambda source: source.get("name", "").lower())
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    with open(registry_path, "w") as source_file:
        json.dump({"shared_drives": sources}, source_file, indent=2)
    return entry
