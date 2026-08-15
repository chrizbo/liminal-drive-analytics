"""Indexes Google Drive Docs and Slides: links + activity."""

import argparse
import json
import os
import re
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import signal
import sys
import warnings
warnings.filterwarnings("ignore")

from tqdm import tqdm
from auth import get_credentials, build_services
from db import connect, init
from demo_data import apply_demo_activity_fixture
from operations import refresh_findings
from sources import (
    register_drive_source, register_shared_drive, resolve_folder,
    resolve_shared_drive, shared_drive_db_path,
)
from storage import (
    ensure_external_resource, ensure_person, external_resource_rows,
    increment_person_activity, linked_unindexed_doc_ids,
    unresolved_person_ids,
    update_external_resource_classification, update_person_identity,
    upsert_activity_snapshot, upsert_doc_link, upsert_document,
    upsert_external_link,
)


def _handle_interrupt(sig, frame):
    print("\n\nInterrupted. Progress saved to data/graph.db.")
    sys.exit(0)

DRIVE_FILE_RE = re.compile(r"https://(?:docs|drive|slides|sheets)\.google\.com/.+?/d/([a-zA-Z0-9_-]+)")
DEMO_ACTIVITY_FOLDER_ID = "1DZJck2R33aEUkioWk7NSnh10NQhMa8eU"

def truncate(s, n=40):
    return s[:n-3] + "..." if len(s) > n else s

EXTERNAL_TYPE_MAP = {
    "notion.so": "notion",
    "github.com": "github",
    "gitlab.com": "gitlab",
    "confluence": "confluence",
    "atlassian.net": "jira",
    "docs.google.com": "google_docs",
    "drive.google.com": "google_drive",
    "slides.google.com": "google_slides",
    "sheets.google.com": "google_sheets",
    "forms.google.com": "google_forms",
    "calendar.google.com": "google_calendar",
    "meet.google.com": "google_meet",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "linkedin.com": "linkedin",
    "medium.com": "medium",
    "substack.com": "substack",
    "figma.com": "figma",
    "miro.com": "miro",
    "airtable.com": "airtable",
    "slack.com": "slack",
    "zoom.us": "zoom",
    "loom.com": "loom",
    "dropbox.com": "dropbox",
    "wikipedia.org": "wikipedia",
    "amazon.com": "amazon",
    "amazonaws.com": "aws",
    "azure.com": "azure",
    "microsoft.com": "microsoft",
    "office.com": "microsoft",
    "sharepoint.com": "sharepoint",
    "asana.com": "asana",
    "linear.app": "linear",
    "trello.com": "trello",
    "clickup.com": "clickup",
    "monday.com": "monday",
    "hubspot.com": "hubspot",
    "salesforce.com": "salesforce",
    "zendesk.com": "zendesk",
    "intercom.com": "intercom",
    "mixpanel.com": "mixpanel",
    "amplitude.com": "amplitude",
    "looker.com": "looker",
    "metabase.com": "metabase",
    "stripe.com": "stripe",
    "twilio.com": "twilio",
    "vercel.app": "vercel",
    "heroku.com": "heroku",
    "netlify.app": "netlify",
    # news & media
    "nytimes.com": "news",
    "theatlantic.com": "news",
    "theguardian.com": "news",
    "bbc.com": "news",
    "wired.com": "news",
    "wsj.com": "news",
    "economist.com": "news",
    "newyorker.com": "news",
    # research & tech writing
    "arxiv.org": "research",
    "simonwillison.net": "tech_blog",
    "stratechery.com": "tech_blog",
    "ben-evans.com": "tech_blog",
    "bsky.app": "bluesky",
    "goodreads.com": "goodreads",
    "maps.app.goo.gl": "google_maps",
    "app.avoma.com": "avoma",
    # flux newsletter sources
    "thejaymo.net": "flux_source",
    "read.fluxcollective.org": "flux_source",
    # news & tech media (long tail)
    "reuters.com": "news",
    "arstechnica.com": "news",
    "bloomberg.com": "news",
    "cnbc.com": "news",
    "msn.com": "news",
    "apnews.com": "news",
    "npr.org": "news",
    "theregister.com": "news",
    "theverge.com": "news",
    "techcrunch.com": "news",
    "reddit.com": "reddit",
    "komoroske.com": "tech_blog",
    "ired.com": "tech_blog",
    "securityweek.com": "news",
    "archive.ph": "archive",
    "bit.ly": "link_shortener",
}


def get_apex_domain(host):
    """Extract registrable apex domain from a full hostname.
    e.g. chrisbutler.substack.com -> substack.com
         en.wikipedia.org         -> wikipedia.org
         github.com               -> github.com
    """
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def classify_domain(url):
    """Returns (domain, apex_domain, resource_type).
    domain      = full subdomain (chrisbutler.substack.com)
    apex_domain = registrable domain (substack.com)
    resource_type = known category if in map, otherwise the apex_domain
    """
    try:
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return url, url, "unknown"
    if not host:
        return "", "", "unknown"
    apex = get_apex_domain(host)
    for key, rtype in EXTERNAL_TYPE_MAP.items():
        if key in host:
            return host, apex, rtype
    return host, apex, apex  # resource_type falls back to apex_domain


def _load_path_significant():
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
    try:
        import json
        with open(config_path) as f:
            return set(json.load(f).get("path_significant_domains", []))
    except Exception:
        return {"github.com", "arxiv.org", "amazon.com", "app.avoma.com", "reddit.com", "goodreads.com"}

# Domains where the path meaningfully identifies the resource
PATH_SIGNIFICANT = _load_path_significant()
# Domains where a specific query param is the resource ID
QUERY_PARAM_ID = {
    "youtube.com": "v",
    "youtu.be":    None,   # whole path is the ID
}


def normalize_url(url):
    """Stable external node ID. Preserves path for path-significant domains,
    and video ID for YouTube. Strips everything else."""
    try:
        p = urllib.parse.urlparse(url)
        host = p.netloc.lower().lstrip("www.")
        apex = get_apex_domain(host)

        if apex in PATH_SIGNIFICANT or host in PATH_SIGNIFICANT:
            # Keep scheme + netloc + path, strip query/fragment + trailing slash
            path = p.path.rstrip("/") or "/"
            # Remove trailing slash unless it's the root
            if path != "/" and path.endswith("/"):
                path = path.rstrip("/")
            return urllib.parse.urlunparse((p.scheme, p.netloc, path, "", "", ""))

        if apex == "youtube.com" or host == "youtu.be":
            # Preserve video ID as query param ?v=
            params = urllib.parse.parse_qs(p.query)
            vid = params.get("v", [None])[0]
            if vid:
                return f"https://www.youtube.com/watch?v={vid}"
            # youtu.be/VIDEO_ID
            if host == "youtu.be" and p.path:
                vid = p.path.lstrip("/")
                return f"https://www.youtube.com/watch?v={vid}"

        # Default: scheme + netloc + path, no query or fragment
        return urllib.parse.urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except Exception:
        return url


def extract_links_from_doc(doc_body):
    """Return list of (url, anchor_text) from a Docs API document body."""
    links = []
    content = doc_body.get("content", [])
    for block in content:
        paragraph = block.get("paragraph", {})
        for el in paragraph.get("elements", []):
            text_run = el.get("textRun", {})
            url = text_run.get("textStyle", {}).get("link", {}).get("url")
            if url:
                links.append((url, text_run.get("content", "").strip()))
    return links


def extract_links_from_slides(presentation):
    """Return list of (url, anchor_text) from a Slides API presentation."""
    links = []
    for slide in presentation.get("slides", []):
        for element in slide.get("pageElements", []):
            shape = element.get("shape", {})
            text = shape.get("text", {})
            for te in text.get("textElements", []):
                text_run = te.get("textRun", {})
                url = text_run.get("style", {}).get("link", {}).get("url")
                if url:
                    links.append((url, text_run.get("content", "").strip()))
    return links


def resolve_link(url, file_id):
    """Returns ('internal', drive_file_id) or ('external', normalized_url)."""
    m = DRIVE_FILE_RE.search(url)
    if m:
        linked_id = m.group(1)
        if linked_id != file_id:
            return "internal", linked_id
        return None, None
    return "external", normalize_url(url)


def fetch_activity(activity_svc, file_id):
    """Returns (snapshots_by_date, person_actions list)."""
    snapshots = defaultdict(lambda: {"views": 0, "edits": 0, "comments": 0})
    person_actions = []

    request_body = {
        "itemName": f"items/{file_id}",
        "consolidationStrategy": {"none": {}},
        "pageSize": 100,
    }

    while True:
        resp = activity_svc.activity().query(body=request_body).execute()
        for event in resp.get("activities", []):
            ts = event.get("timestamp") or event.get("timeRange", {}).get("endTime", "")
            date = ts[:10] if ts else None

            action_detail = {}
            actions = event.get("primaryActionDetail", {})
            if "edit" in actions:
                action_detail = "edit"
            elif "view" in actions:
                action_detail = "view"
            elif "comment" in actions:
                action_detail = "comment"
            else:
                # grab first key
                action_detail = next(iter(actions), "other")

            if date:
                if action_detail == "view":
                    snapshots[date]["views"] += 1
                elif action_detail == "edit":
                    snapshots[date]["edits"] += 1
                elif action_detail == "comment":
                    snapshots[date]["comments"] += 1

            for actor in event.get("actors", []):
                user = actor.get("user", {}).get("knownUser", {})
                person_id = user.get("personName", "")
                if person_id and date:
                    person_actions.append((person_id, action_detail, ts))

        page_token = resp.get("nextPageToken")
        if not page_token:
            break
        request_body["pageToken"] = page_token

    return snapshots, person_actions


def index_file(file_meta, drive_svc, docs_svc, slides_svc, activity_svc, conn, now_str, verbose, scope=None):
    file_id = file_meta["id"]
    mime = file_meta.get("mimeType", "")
    title = file_meta.get("name", "")
    owner = (file_meta.get("owners") or [{}])[0].get("emailAddress", "")
    created = file_meta.get("createdTime", "")
    modified = file_meta.get("modifiedTime", "")
    web_url = file_meta.get("webViewLink", "")

    if verbose:
        print(f"  Indexing: {title}")

    upsert_document(conn, {
        "id": file_id,
        "title": title,
        "owner_email": owner,
        "mime_type": mime,
        "created_at": created,
        "modified_at": modified,
        "last_indexed_at": now_str,
        "web_url": web_url,
    }, scope)

    # Extract links
    links = []
    try:
        if mime == "application/vnd.google-apps.document":
            doc = docs_svc.documents().get(documentId=file_id).execute()
            links = extract_links_from_doc(doc.get("body", {}))
        elif mime == "application/vnd.google-apps.presentation":
            pres = slides_svc.presentations().get(presentationId=file_id).execute()
            links = extract_links_from_slides(pres)
    except Exception as e:
        print(f"    Warning: could not read content for {title}: {e}")

    for url, anchor in links:
        kind, target = resolve_link(url, file_id)
        if kind == "internal":
            upsert_doc_link(conn, file_id, target, now_str, now_str, scope)
        elif kind == "external" and target:
            domain, apex, rtype = classify_domain(target)
            resource_id = target
            ensure_external_resource(conn, {
                "id": resource_id,
                "url": target,
                "domain": domain,
                "apex_domain": apex,
                "resource_type": rtype,
            }, scope)
            upsert_external_link(
                conn, file_id, resource_id, anchor[:200] if anchor else "",
                now_str, now_str, scope,
            )

    # Fetch activity
    try:
        snapshots, person_actions = fetch_activity(activity_svc, file_id)
        for date, counts in snapshots.items():
            upsert_activity_snapshot(conn, file_id, date, counts, scope)
        for person_id, action, ts in person_actions:
            ensure_person(conn, person_id, display_name=person_id, scope=scope)
            increment_person_activity(conn, person_id, file_id, action, ts[:19] if ts else "", scope)
    except Exception as e:
        print(f"    Warning: could not fetch activity for {title}: {e}")

    conn.commit()


def fetch_file_meta(drive_svc, file_id):
    try:
        return drive_svc.files().get(
            fileId=file_id,
            fields="id, name, mimeType, createdTime, modifiedTime, owners, webViewLink, driveId, parents",
            supportsAllDrives=True,
        ).execute()
    except Exception:
        return None


def drive_list_args(query, page_token=None, source=None):
    args = {
        "q": query,
        "pageSize": 100,
        "fields": (
            "nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, "
            "owners, webViewLink, driveId, parents)"
        ),
        "pageToken": page_token,
    }
    if source and source.get("kind") != "folder":
        args.update({
            "corpora": "drive",
            "driveId": source["id"],
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        })
    elif source and source.get("drive_id"):
        args.update({
            "corpora": "drive",
            "driveId": source["drive_id"],
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        })
    return args


def resolve_people(people_svc, conn, verbose=False, progress=None, scope=None):
    """Resolve people/XXXXX resource names → display name + email using People API.
    Only fetches records where email is still blank. Batches in groups of 50."""
    unresolved = unresolved_person_ids(conn, scope)
    if not unresolved:
        print("All persons already resolved.")
        if progress:
            progress({"phase": "people", "message": "All people already resolved", "current": 0, "total": 0})
        return

    print(f"Resolving {len(unresolved)} person IDs via People API...")
    if progress:
        progress({
            "phase": "people", "message": f"Resolving {len(unresolved)} people",
            "current": 0, "total": len(unresolved),
        })
    resolved = 0
    batch_size = 200
    batches = range(0, len(unresolved), batch_size)
    with tqdm(batches, desc="Resolving people", unit="batch", dynamic_ncols=True) as bar:
        for i in bar:
            batch = unresolved[i:i + batch_size]
            try:
                resp = people_svc.people().getBatchGet(
                    resourceNames=batch,
                    personFields="names,emailAddresses",
                ).execute()
            except Exception as e:
                print(f"\n  Warning: People API batch failed: {e}")
                continue

            for entry in resp.get("responses", []):
                resource_name = entry.get("requestedResourceName", "")
                person = entry.get("person", {})
                names = person.get("names", [])
                emails = person.get("emailAddresses", [])
                display_name = names[0].get("displayName", "") if names else ""
                email = emails[0].get("value", "") if emails else ""
                if display_name or email:
                    update_person_identity(conn, resource_name, display_name, email, scope)
                    if verbose:
                        tqdm.write(f"  {resource_name} → {display_name} <{email}>")
                    resolved += 1
            if progress:
                progress({
                    "phase": "people", "message": f"Resolved {resolved} of {len(unresolved)} people",
                    "current": min(i + len(batch), len(unresolved)), "total": len(unresolved),
                })

    conn.commit()
    print(f"Resolved {resolved} of {len(unresolved)} person IDs.")


def run(
    days, verbose, expand=False, shared_drive=None, folder=None,
    progress=None, conn=None, scope=None, database_path=None,
):
    def report(phase, message, current=None, total=None, **extra):
        if progress:
            progress({
                "phase": phase, "message": message, "current": current, "total": total, **extra,
            })

    report("authenticating", "Connecting to Google Drive")
    creds = get_credentials()
    drive_svc, docs_svc, slides_svc, activity_svc, people_svc = build_services(creds)
    report("authenticating", "Connected to Google Drive")
    source = None
    if shared_drive:
        source = resolve_shared_drive(drive_svc, shared_drive)
        source["kind"] = "shared_drive"
    elif folder:
        source = resolve_folder(drive_svc, folder)
    if database_path is None:
        database_path = shared_drive_db_path(source["id"]) if source else None
    owns_connection = conn is None
    conn = conn or connect(database_path)
    init(conn)

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    mime_filter = (
        "mimeType='application/vnd.google-apps.document' or "
        "mimeType='application/vnd.google-apps.presentation'"
    )
    query = f"({mime_filter}) and modifiedTime > '{since}' and trashed=false"
    if source and source.get("kind") == "folder":
        query = f"'{source['id']}' in parents and {query}"

    source_label = (
        f"{'Folder' if source.get('kind') == 'folder' else 'Shared Drive'} '{source['name']}'"
        if source else "Drive"
    )
    print(f"Fetching files from {source_label} modified in the last {days} days...")
    report("fetching", f"Fetching files from {source_label}")
    files = []
    page_token = None
    while True:
        list_args = drive_list_args(query, page_token, source)
        resp = drive_svc.files().list(**list_args).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        report("fetching", f"Found {len(files)} files so far", current=len(files))
        if not page_token:
            break

    print(f"Found {len(files)} files. Indexing...")
    report("indexing", f"Indexing {len(files)} files", current=0, total=len(files))
    with tqdm(files, unit="doc", dynamic_ncols=True) as bar:
        for index, f in enumerate(bar, 1):
            bar.set_postfix_str(truncate(f.get("name", "")).ljust(40), refresh=True)
            report(
                "indexing", f"Indexing {f.get('name', 'Untitled')}",
                current=index - 1, total=len(files), document_title=f.get("name", ""),
            )
            index_file(f, drive_svc, docs_svc, slides_svc, activity_svc, conn, now_str, verbose, scope)
            report(
                "indexing", f"Indexed {f.get('name', 'Untitled')}",
                current=index, total=len(files), document_title=f.get("name", ""),
            )

    if expand:
        # Follow doc→doc links to index referenced docs not in the date window
        unindexed = linked_unindexed_doc_ids(conn, scope)
        if unindexed:
            print(f"\nExpanding: found {len(unindexed)} linked-but-unindexed docs. Fetching...")
            report("expanding", f"Expanding {len(unindexed)} linked documents", current=0, total=len(unindexed))
            with tqdm(unindexed, desc="Expanding", unit="doc", dynamic_ncols=True) as bar:
                for index, file_id in enumerate(bar, 1):
                    meta = fetch_file_meta(drive_svc, file_id)
                    if not meta:
                        report("expanding", "Skipped unavailable linked document", current=index, total=len(unindexed))
                        continue
                    if source and source.get("kind") == "shared_drive" and meta.get("driveId") != source["id"]:
                        report("expanding", "Skipped linked document outside workspace", current=index, total=len(unindexed))
                        continue
                    if source and source.get("kind") == "folder" and source["id"] not in (meta.get("parents") or []):
                        report("expanding", "Skipped linked document outside workspace", current=index, total=len(unindexed))
                        continue
                    mime = meta.get("mimeType", "")
                    if mime not in ("application/vnd.google-apps.document", "application/vnd.google-apps.presentation"):
                        report("expanding", "Skipped unsupported linked document", current=index, total=len(unindexed))
                        continue
                    bar.set_postfix_str(truncate(meta.get("name", "")), refresh=True)
                    index_file(meta, drive_svc, docs_svc, slides_svc, activity_svc, conn, now_str, verbose, scope)
                    report(
                        "expanding", f"Indexed linked document {meta.get('name', 'Untitled')}",
                        current=index, total=len(unindexed), document_title=meta.get("name", ""),
                    )
        else:
            print("\nNo unindexed linked docs found.")
            report("expanding", "No linked documents need indexing", current=0, total=0)

    if source and source.get("kind") == "folder" and source["id"] == DEMO_ACTIVITY_FOLDER_ID:
        report("fixtures", "Applying demo activity fixture")
        apply_demo_activity_fixture(conn, scope=scope)

    resolve_people(people_svc, conn, verbose, progress, scope)
    report("findings", "Refreshing operational findings")
    result = refresh_findings(conn, scope=scope)
    print(
        f"Operational findings: {result['created']} created, "
        f"{result['updated']} updated, {result['deactivated']} deactivated."
    )
    if owns_connection:
        conn.close()
    if source:
        if source.get("kind") == "folder":
            register_drive_source(source["id"], source["name"], "folder", database_path)
        else:
            register_shared_drive(source["id"], source["name"], database_path)
    print(f"\nDone. {database_path or 'data/graph.db'} is up to date.")
    report(
        "complete", f"{source_label} is up to date",
        findings=result, database_path=database_path,
    )
    return {
        "source": source_label,
        "database_path": database_path,
        "files_found": len(files),
        "findings": result,
    }


def reclassify(verbose=False, scope=None):
    """Re-run domain classification over all existing external_resources."""
    conn = connect()
    rows = list(external_resource_rows(conn, scope))
    updated = 0
    for row in rows:
        domain, apex, rtype = classify_domain(row["url"])
        update_external_resource_classification(conn, row["id"], domain, apex, rtype, scope)
        if verbose and rtype != "external":
            print(f"  {rtype:<20} {domain}")
        updated += 1
    conn.commit()
    conn.close()
    print(f"Reclassified {updated} external resources.")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_interrupt)
    parser = argparse.ArgumentParser(description="Index Google Drive Docs and Slides")
    parser.add_argument("--days", type=int, default=90, help="How many days back to index (default: 90)")
    parser.add_argument("--expand", action="store_true", help="Follow links to index referenced docs outside the date window")
    parser.add_argument("--reclassify", action="store_true", help="Re-run domain classification on all stored external links")
    parser.add_argument("--resolve-people", action="store_true", help="Resolve person IDs to names/emails via People API")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show each file as it's indexed")
    parser.add_argument(
        "--shared-drive",
        help="Shared Drive root URL/ID, or a folder URL/ID inside a Shared Drive",
    )
    parser.add_argument(
        "--folder",
        help="Drive folder URL/ID to index as a bounded workspace",
    )
    args = parser.parse_args()
    if args.reclassify:
        reclassify(args.verbose)
    elif args.resolve_people:
        creds = get_credentials()
        _, _, _, _, people_svc = build_services(creds)
        conn = connect()
        init(conn)
        resolve_people(people_svc, conn, args.verbose)
        conn.close()
    else:
        run(args.days, args.verbose, args.expand, args.shared_drive, args.folder)
