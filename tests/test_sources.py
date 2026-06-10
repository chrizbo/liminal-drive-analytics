"""Tests for Shared Drive selection and source registry helpers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from indexer import drive_list_args
from sources import (
    extract_drive_item_id, load_sources, register_shared_drive,
    resolve_shared_drive, shared_drive_db_path,
)


def test_extract_drive_item_id_from_folder_url():
    url = "https://drive.google.com/drive/folders/0AP6VPalWOTU-Uk9PVA"
    assert extract_drive_item_id(url) == "0AP6VPalWOTU-Uk9PVA"


def test_shared_drive_list_args_scope_to_drive():
    args = drive_list_args("trashed=false", source={"id": "drive-123"})
    assert args["corpora"] == "drive"
    assert args["driveId"] == "drive-123"
    assert args["includeItemsFromAllDrives"] is True
    assert args["supportsAllDrives"] is True


def test_personal_drive_list_args_do_not_add_shared_drive_scope():
    args = drive_list_args("trashed=false")
    assert "driveId" not in args
    assert "corpora" not in args


def test_register_shared_drive_is_idempotent(tmp_path):
    registry = str(tmp_path / "sources.json")
    database = str(tmp_path / "shared.db")
    register_shared_drive("drive-1", "Product", database, registry)
    register_shared_drive("drive-1", "Product Team", database, registry)
    sources = load_sources(registry)
    assert len(sources) == 1
    assert sources[0]["name"] == "Product Team"


class Executable:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.result


class FakeDrives:
    def __init__(self, drives):
        self.drives = drives

    def get(self, driveId, fields):
        result = self.drives.get(driveId)
        return Executable(result=result, error=KeyError(driveId) if not result else None)


class FakeFiles:
    def __init__(self, files):
        self.files = files

    def get(self, fileId, fields, supportsAllDrives):
        return Executable(result=self.files[fileId])


class FakeDriveService:
    def __init__(self, drives, files=None):
        self._drives = FakeDrives(drives)
        self._files = FakeFiles(files or {})

    def drives(self):
        return self._drives

    def files(self):
        return self._files


def test_resolve_shared_drive_root():
    service = FakeDriveService({"drive-1": {"id": "drive-1", "name": "Product"}})
    assert resolve_shared_drive(service, "drive-1") == {"id": "drive-1", "name": "Product"}


def test_resolve_folder_inside_shared_drive():
    service = FakeDriveService(
        {"drive-1": {"id": "drive-1", "name": "Product"}},
        {"folder-1": {"id": "folder-1", "name": "Launch", "driveId": "drive-1"}},
    )
    assert resolve_shared_drive(service, "folder-1") == {"id": "drive-1", "name": "Product"}
