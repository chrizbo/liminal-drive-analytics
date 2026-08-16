"""OAuth flow for Google Drive APIs."""

import argparse
import json
import os
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.activity.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_FILE = os.path.join(ROOT, "credentials.json")
TOKEN_FILE = os.path.join(ROOT, "token.json")
OAUTH_CLIENT_CONFIG_ENV = "DRIVE_ANALYTICS_GOOGLE_OAUTH_CLIENT_CONFIG"
OAUTH_CLIENT_CONFIG_FILE_ENV = "DRIVE_ANALYTICS_GOOGLE_OAUTH_CLIENT_CONFIG_FILE"


def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                creds = None
        if not creds or not creds.valid:
            creds = run_oauth_flow()
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def run_oauth_flow():
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            "credentials.json not found. "
            "Follow docs/google-setup.md to download it from Google Cloud Console."
        )
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    return flow.run_local_server(port=0)


def load_oauth_client_config():
    raw = os.environ.get(OAUTH_CLIENT_CONFIG_ENV, "").strip()
    if raw:
        return json.loads(raw)
    path = os.environ.get(OAUTH_CLIENT_CONFIG_FILE_ENV, "").strip() or CREDENTIALS_FILE
    if not os.path.exists(path):
        raise FileNotFoundError(
            "Google OAuth client config not found. Configure "
            f"{OAUTH_CLIENT_CONFIG_ENV}, {OAUTH_CLIENT_CONFIG_FILE_ENV}, or credentials.json."
        )
    with open(path) as f:
        return json.load(f)


def build_web_oauth_flow(redirect_uri, state=None):
    flow = Flow.from_client_config(load_oauth_client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = redirect_uri
    return flow


def credentials_from_json(credentials_json):
    return Credentials.from_authorized_user_info(json.loads(credentials_json), SCOPES)


def build_services(creds):
    drive = build("drive", "v3", credentials=creds)
    docs = build("docs", "v1", credentials=creds)
    slides = build("slides", "v1", credentials=creds)
    activity = build("driveactivity", "v2", credentials=creds)
    people = build("people", "v1", credentials=creds)
    return drive, docs, slides, activity, people


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="List recent docs to confirm access")
    args = parser.parse_args()

    creds = get_credentials()
    print("Authentication successful.")

    if args.verify:
        drive, _, _, _, _ = build_services(creds)
        results = drive.files().list(
            q="mimeType='application/vnd.google-apps.document' and trashed=false",
            orderBy="modifiedTime desc",
            pageSize=10,
            fields="files(id, name, modifiedTime)",
        ).execute()
        files = results.get("files", [])
        if not files:
            print("No Google Docs found.")
        else:
            print(f"\n{len(files)} most recently modified Google Docs:")
            for f in files:
                print(f"  [{f['modifiedTime'][:10]}] {f['name']}  ({f['id']})")
