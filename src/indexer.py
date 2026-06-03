"""Indexes Google Drive Docs and Slides: links + activity."""

import argparse
import re
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from auth import get_credentials, build_services
from db import connect, init

DRIVE_FILE_RE = re.compile(r"https://(?:docs|drive|slides|sheets)\.google\.com/.+?/d/([a-zA-Z0-9_-]+)")

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


def classify_domain(url):
    """Returns (domain, resource_type). resource_type is a known category if
    the domain matches the map, otherwise the domain itself is used as the type
    so nothing is lost as a generic 'external' bucket."""
    try:
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return url, "unknown"
    if not host:
        return "", "unknown"
    for key, rtype in EXTERNAL_TYPE_MAP.items():
        if key in host:
            return host, rtype
    return host, host  # domain is its own type when not in the map


def normalize_url(url):
    """Strip tracking params and fragments for stable external node IDs."""
    try:
        p = urllib.parse.urlparse(url)
        # keep scheme + netloc + path only for external resources
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


def index_file(file_meta, drive_svc, docs_svc, slides_svc, activity_svc, conn, now_str, verbose):
    file_id = file_meta["id"]
    mime = file_meta.get("mimeType", "")
    title = file_meta.get("name", "")
    owner = (file_meta.get("owners") or [{}])[0].get("emailAddress", "")
    created = file_meta.get("createdTime", "")
    modified = file_meta.get("modifiedTime", "")
    web_url = file_meta.get("webViewLink", "")

    if verbose:
        print(f"  Indexing: {title}")

    # Upsert document node
    conn.execute("""
        INSERT INTO documents (id, title, owner_email, mime_type, created_at, modified_at, last_indexed_at, web_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title, modified_at=excluded.modified_at,
            last_indexed_at=excluded.last_indexed_at, web_url=excluded.web_url
    """, (file_id, title, owner, mime, created, modified, now_str, web_url))

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
            conn.execute("""
                INSERT INTO doc_links (src_id, dst_id, first_seen, last_seen)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(src_id, dst_id) DO UPDATE SET last_seen=excluded.last_seen
            """, (file_id, target, now_str, now_str))
        elif kind == "external" and target:
            domain, rtype = classify_domain(target)
            resource_id = target
            conn.execute("""
                INSERT INTO external_resources (id, url, domain, resource_type)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
            """, (resource_id, target, domain, rtype))
            conn.execute("""
                INSERT INTO external_links (src_id, resource_id, anchor_text, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(src_id, resource_id) DO UPDATE SET last_seen=excluded.last_seen
            """, (file_id, resource_id, anchor[:200] if anchor else "", now_str, now_str))

    # Fetch activity
    try:
        snapshots, person_actions = fetch_activity(activity_svc, file_id)
        for date, counts in snapshots.items():
            conn.execute("""
                INSERT INTO activity_snapshots (document_id, date, views, edits, comments)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(document_id, date) DO UPDATE SET
                    views=excluded.views, edits=excluded.edits, comments=excluded.comments
            """, (file_id, date, counts["views"], counts["edits"], counts["comments"]))
        for person_id, action, ts in person_actions:
            conn.execute("""
                INSERT INTO persons (id, email, display_name) VALUES (?, ?, ?)
                ON CONFLICT(id) DO NOTHING
            """, (person_id, "", person_id))
            conn.execute("""
                INSERT INTO person_activity (person_id, document_id, action, last_seen, count)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(person_id, document_id, action) DO UPDATE SET
                    count=count+1, last_seen=MAX(last_seen, excluded.last_seen)
            """, (person_id, file_id, action, ts[:19] if ts else ""))
    except Exception as e:
        print(f"    Warning: could not fetch activity for {title}: {e}")

    conn.commit()


def fetch_file_meta(drive_svc, file_id):
    try:
        return drive_svc.files().get(
            fileId=file_id,
            fields="id, name, mimeType, createdTime, modifiedTime, owners, webViewLink",
        ).execute()
    except Exception:
        return None


def run(days, verbose, expand=False):
    creds = get_credentials()
    drive_svc, docs_svc, slides_svc, activity_svc = build_services(creds)
    conn = connect()
    init(conn)

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    mime_filter = (
        "mimeType='application/vnd.google-apps.document' or "
        "mimeType='application/vnd.google-apps.presentation'"
    )
    query = f"({mime_filter}) and modifiedTime > '{since}' and trashed=false"

    print(f"Fetching files modified in the last {days} days...")
    files = []
    page_token = None
    while True:
        resp = drive_svc.files().list(
            q=query,
            pageSize=100,
            fields="nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, owners, webViewLink)",
            pageToken=page_token,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    print(f"Found {len(files)} files. Indexing...")
    for i, f in enumerate(files, 1):
        if verbose:
            print(f"[{i}/{len(files)}]", end=" ")
        index_file(f, drive_svc, docs_svc, slides_svc, activity_svc, conn, now_str, verbose)

    if expand:
        # Follow doc→doc links to index referenced docs not in the date window
        unindexed = [
            row["dst_id"] for row in conn.execute("""
                SELECT DISTINCT dl.dst_id FROM doc_links dl
                LEFT JOIN documents d ON dl.dst_id = d.id
                WHERE d.id IS NULL
            """)
        ]
        if unindexed:
            print(f"\nExpanding: found {len(unindexed)} linked-but-unindexed docs. Fetching...")
            for i, file_id in enumerate(unindexed, 1):
                meta = fetch_file_meta(drive_svc, file_id)
                if not meta:
                    continue
                mime = meta.get("mimeType", "")
                if mime not in ("application/vnd.google-apps.document", "application/vnd.google-apps.presentation"):
                    continue
                if verbose:
                    print(f"  [expand {i}/{len(unindexed)}]", end=" ")
                index_file(meta, drive_svc, docs_svc, slides_svc, activity_svc, conn, now_str, verbose)
        else:
            print("\nNo unindexed linked docs found.")

    conn.close()
    print(f"\nDone. data/graph.db is up to date.")


def reclassify(verbose=False):
    """Re-run domain classification over all existing external_resources."""
    conn = connect()
    rows = list(conn.execute("SELECT id, url FROM external_resources"))
    updated = 0
    for row in rows:
        domain, rtype = classify_domain(row["url"])
        conn.execute(
            "UPDATE external_resources SET domain=?, resource_type=? WHERE id=?",
            (domain, rtype, row["id"])
        )
        if verbose and rtype != "external":
            print(f"  {rtype:<20} {domain}")
        updated += 1
    conn.commit()
    conn.close()
    print(f"Reclassified {updated} external resources.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index Google Drive Docs and Slides")
    parser.add_argument("--days", type=int, default=90, help="How many days back to index (default: 90)")
    parser.add_argument("--expand", action="store_true", help="Follow links to index referenced docs outside the date window")
    parser.add_argument("--reclassify", action="store_true", help="Re-run domain classification on all stored external links")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show each file as it's indexed")
    args = parser.parse_args()
    if args.reclassify:
        reclassify(args.verbose)
    else:
        run(args.days, args.verbose, args.expand)
