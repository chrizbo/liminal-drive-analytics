"""Streamlit dashboard for Liminal Drive Analytics."""

import os
import re
import sys
import tempfile
from datetime import datetime, timezone, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from pyvis.network import Network

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import DB_PATH, DEMO_DB_PATH, connect, init
from demo_data import reset_demo_database
from graph import build_doc_graph, in_degree_rank, communities
from analytics import (activity_by_doc, stale_activity, title_map,
                       rising_docs, stale_docs,
                       STALE_WINDOW_DAYS, STALE_RECENT_MAX)
from utils import doc_url, mime_icon
from operations import (
    DISPOSITIONS, FINDING_STATUSES, SIGNAL_DISPLAY_NAMES, generate_brief, get_finding,
    latest_brief, list_findings, refresh_findings, update_review,
)
from sources import load_sources

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Liminal Drive Analytics",
    page_icon="🔗",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def doc_table(rows, link_col, url_col, extra_cols, id_col=None, context="", data=None):
    """Render a dataframe where doc titles link to Drive, plus an inline inspect picker."""
    if not rows:
        return
    df = pd.DataFrame(rows)
    col_cfg = {url_col: st.column_config.LinkColumn("↗", display_text="↗", width="small")}
    display_cols = [link_col, url_col] + extra_cols
    st.dataframe(df[display_cols], width="stretch", hide_index=True, column_config=col_cfg)

    if id_col and data:
        options = ["—"] + [str(r.get(link_col, "")) for r in rows]
        choice = st.selectbox("🔍 Inspect a doc from this list",
                              options, key=f"inspect_{context}", label_visibility="collapsed")
        if choice != "—":
            selected = next((r for r in rows if str(r.get(link_col, "")) == choice), None)
            if selected:
                _render_doc_detail_inline(selected[id_col], data, context)

def _render_doc_detail_inline(selected_id, data, context):
    """Render doc detail in an expander, inline below a table."""
    titles = data["titles"]; urls = data["urls"]; mimes = data["mimes"]
    title   = titles.get(selected_id, selected_id)
    url     = doc_url(selected_id, urls.get(selected_id, ""), mimes.get(selected_id, ""))
    mime    = mimes.get(selected_id, "")
    mod     = data["modified"].get(selected_id, "")[:10]
    in_deg  = data["in_deg"]
    deg     = in_deg.get(selected_id, 0)
    cluster = data["community_map"].get(selected_id, -1)
    cl_label= data["cluster_labels"].get(cluster, "—")
    act     = data["activity"].get(selected_id, {"recent": 0, "prior": 0})
    status  = ("🔴 Stale hub" if selected_id in data["stale_hub_ids"] else
               "🟢 Rising"    if selected_id in data["rising_ids"]    else
               "🟡 Hub"       if selected_id in data["hub_ids"]       else
               "🔵 Stale"     if selected_id in data["stale_ids"]     else "⚫ Normal")

    with st.expander(f"{mime_icon(mime)} {title}", expanded=True):
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**Status:** {status}")
        c2.markdown(f"**Cluster:** {cl_label}")
        if url: c3.markdown(f"[Open in Drive →]({url})")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Inbound links",   deg)
        m2.metric("Recent activity", act["recent"])
        m3.metric("Prior activity",  act["prior"])
        m4.metric("Last modified",   mod)

        col_in, col_out = st.columns(2)
        with col_in:
            st.markdown("**📥 Linked from**")
            inbound = data["inbound_links"].get(selected_id, [])
            if inbound:
                for src in inbound:
                    t = titles.get(src, "[unindexed]")
                    u = doc_url(src, urls.get(src, ""), mimes.get(src, ""))
                    st.markdown(f"- [{t}]({u})" if u else f"- {t}")
            else:
                st.caption("Nothing links here.")
        with col_out:
            st.markdown("**📤 Links to**")
            outbound = data["outbound_links"].get(selected_id, [])
            if outbound:
                for dst in outbound:
                    t = titles.get(dst, "[unindexed]")
                    u = doc_url(dst, urls.get(dst, ""), mimes.get(dst, ""))
                    st.markdown(f"- [{t}]({u})" if u else f"- {t}")
            else:
                st.caption("No outbound links.")

        history = data["all_activity_history"].get(selected_id)
        if history:
            df_h = pd.DataFrame(history)
            df_h["date"] = pd.to_datetime(df_h["date"])
            fig = px.bar(df_h, x="date", y=["views","edits","comments"],
                         labels={"date":"","value":"Events","variable":"Type"},
                         color_discrete_map={"views":"#4C72B0","edits":"#55A868","comments":"#DD8452"})
            st.plotly_chart(fig, use_container_width=True)


# ── Load data (cached) ────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_data(recent_days, prior_days, database_path):
    conn = connect(database_path)
    init(conn)
    refresh_findings(conn, recent_days=recent_days, prior_days=prior_days)

    titles = title_map(conn)
    mimes = {row["id"]: row["mime_type"] or "" for row in conn.execute(
        "SELECT id, mime_type FROM documents"
    )}
    urls = {row["id"]: doc_url(row["id"], row["web_url"] or "", mimes.get(row["id"], ""))
            for row in conn.execute("SELECT id, web_url FROM documents")}
    modified = {row["id"]: row["modified_at"] or "" for row in conn.execute(
        "SELECT id, modified_at FROM documents"
    )}

    activity  = activity_by_doc(conn, days_recent=recent_days, days_prior=prior_days)
    stale_act = stale_activity(conn)
    G = build_doc_graph(conn)
    in_deg = dict(in_degree_rank(G))
    comms = communities(G)
    community_map = {}
    for i, cluster in enumerate(comms):
        for node in cluster:
            community_map[node] = i

    doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    link_count = conn.execute("SELECT COUNT(*) FROM doc_links").fetchone()[0]
    ext_count  = conn.execute("SELECT COUNT(*) FROM external_links").fetchone()[0]
    act_days   = conn.execute("SELECT COUNT(DISTINCT date) FROM activity_snapshots").fetchone()[0]

    # Chart: grouped by apex_domain for clean rollups (substack.com not split across subdomains)
    ext_by_apex = [
        {"domain": r["apex_domain"] or r["domain"], "links": r["cnt"]}
        for r in conn.execute("""
            SELECT COALESCE(NULLIF(er.apex_domain,''), er.domain) as apex_domain,
                   COUNT(*) as cnt
            FROM external_links el
            JOIN external_resources er ON el.resource_id = er.id
            WHERE er.domain != '' AND er.domain != 'unknown'
            GROUP BY apex_domain ORDER BY cnt DESC LIMIT 40
        """)
    ]
    # Full table: individual subdomains for detail
    ext_domains = [
        {"domain": r["domain"], "apex": r["apex_domain"] or "", "links": r["cnt"]}
        for r in conn.execute("""
            SELECT er.domain, er.apex_domain, COUNT(*) as cnt
            FROM external_links el
            JOIN external_resources er ON el.resource_id = er.id
            WHERE er.domain != '' AND er.domain != 'unknown'
            GROUP BY er.domain ORDER BY cnt DESC LIMIT 100
        """)
    ]

    # Activity time series for top 10 docs by recent activity
    top_ids = sorted(activity, key=lambda d: activity[d]["recent"], reverse=True)[:10]
    time_series = []
    for doc_id in top_ids:
        for row in conn.execute("""
            SELECT date, views + edits + comments as total
            FROM activity_snapshots WHERE document_id = ? ORDER BY date
        """, (doc_id,)):
            time_series.append({
                "date": row["date"],
                "activity": row["total"],
                "doc": titles.get(doc_id, doc_id)[:40],
            })

    # Per-doc activity history for detail view
    all_activity_history = {}
    for doc_id in titles:
        rows = conn.execute("""
            SELECT date, views, edits, comments
            FROM activity_snapshots WHERE document_id = ? ORDER BY date
        """, (doc_id,)).fetchall()
        if rows:
            all_activity_history[doc_id] = [dict(r) for r in rows]

    # Inbound/outbound links per doc
    inbound_links = {}
    for row in conn.execute("SELECT dst_id, src_id FROM doc_links"):
        inbound_links.setdefault(row["dst_id"], []).append(row["src_id"])

    outbound_links = {}
    for row in conn.execute("SELECT src_id, dst_id FROM doc_links"):
        outbound_links.setdefault(row["src_id"], []).append(row["dst_id"])

    # External links per doc
    doc_external = {}
    for row in conn.execute("""
        SELECT el.src_id, er.domain, er.url, el.anchor_text
        FROM external_links el JOIN external_resources er ON el.resource_id = er.id
        ORDER BY er.domain
    """):
        doc_external.setdefault(row["src_id"], []).append({
            "domain": row["domain"], "url": row["url"], "anchor": row["anchor_text"]
        })

    # Resolved person names
    person_labels = {}
    for row in conn.execute("SELECT id, display_name, email FROM persons"):
        name  = row["display_name"] or ""
        email = row["email"] or ""
        if name and email:
            person_labels[row["id"]] = f"{name} ({email})"
        elif name:
            person_labels[row["id"]] = name
        elif email:
            person_labels[row["id"]] = email
        else:
            person_labels[row["id"]] = row["id"]  # fallback to raw ID

    owner_by_email = {}
    for row in conn.execute("SELECT owner_email, COUNT(*) as cnt FROM documents WHERE owner_email != '' GROUP BY owner_email ORDER BY cnt DESC"):
        owner_by_email[row["owner_email"]] = row["cnt"]

    top_editors = []
    for row in conn.execute("""
        SELECT person_id,
               COUNT(DISTINCT document_id) as doc_count,
               SUM(count) as total_edits
        FROM person_activity
        WHERE action = 'edit'
        GROUP BY person_id
        ORDER BY total_edits DESC
        LIMIT 20
    """):
        top_editors.append({
            "Editor": person_labels.get(row["person_id"], row["person_id"]),
            "Docs edited": row["doc_count"],
            "Total edits": row["total_edits"],
        })

    # Per-doc editors for detail view
    doc_editors = {}
    for row in conn.execute("""
        SELECT document_id, person_id, action, count, last_seen
        FROM person_activity
        ORDER BY count DESC
    """):
        doc_editors.setdefault(row["document_id"], []).append({
            "Person": person_labels.get(row["person_id"], row["person_id"]),
            "Action": row["action"],
            "Count": row["count"],
            "Last seen": row["last_seen"][:10] if row["last_seen"] else "",
        })

    operational_findings = [
        get_finding(conn, finding["id"])
        for finding in list_findings(conn, limit=1000)
    ]
    current_brief = latest_brief(conn)

    # ── Node status sets for graph coloring ──────────────────────────────────
    rising_ids = {d for d, *_ in rising_docs(activity, titles, top_n=9999)}
    stale_hub_ids = set()
    stale_ids = set()
    for doc_id, deg in dict(in_degree_rank(G)).items():
        counts = activity.get(doc_id, {"recent": 0})
        if deg > 0 and counts["recent"] == 0:
            stale_hub_ids.add(doc_id)
    for doc_id, *_ in stale_docs(stale_act, list(dict(in_degree_rank(G)).items()), titles, top_n=9999):
        stale_ids.add(doc_id)
    hub_ids = {n for n, d in dict(in_degree_rank(G)).items() if d >= 2}

    # ── Cluster labels from most frequent title words ─────────────────────────
    STOPWORDS = {"the","a","an","and","or","of","in","to","for","on","at","by",
                 "with","from","is","it","its","this","that","as","are","was",
                 "be","been","our","we","my","i","you","your","their","has",
                 "have","how","what","when","who","which","not","but","can",
                 "will","do","does","would","could","should","may","might",
                 "-","&","—","part","new","old","draft","v1","v2","v3"}
    cluster_labels = {}
    for i, cluster in enumerate(comms):
        words = []
        for n in cluster:
            t = titles.get(n, "")
            for w in re.sub(r"[^\w\s]", " ", t).lower().split():
                if w not in STOPWORDS and len(w) > 2:
                    words.append(w)
        freq = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        top = sorted(freq, key=freq.get, reverse=True)[:3]
        cluster_labels[i] = " · ".join(top) if top else f"Cluster {i+1}"

    conn.close()
    return {
        "titles": titles, "urls": urls, "mimes": mimes, "modified": modified,
        "activity": activity, "stale_act": stale_act, "G": G, "in_deg": in_deg,
        "rising_ids": rising_ids, "stale_hub_ids": stale_hub_ids,
        "stale_ids": stale_ids, "hub_ids": hub_ids,
        "cluster_labels": cluster_labels,
        "community_map": community_map, "comms": comms,
        "doc_count": doc_count, "link_count": link_count,
        "ext_count": ext_count, "act_days": act_days,
        "ext_domains": ext_domains, "ext_by_apex": ext_by_apex, "time_series": time_series,
        "all_activity_history": all_activity_history,
        "inbound_links": inbound_links, "outbound_links": outbound_links,
        "doc_external": doc_external,
        "owner_by_email": owner_by_email,
        "top_editors": top_editors,
        "doc_editors": doc_editors,
        "operational_findings": operational_findings,
        "findings_by_id": {finding["id"]: finding for finding in operational_findings},
        "current_brief": current_brief,
    }
BRIEF_SECTION_LABELS = {
    "what_changed": "What changed",
    "follow_ups": "Decisions and follow-ups",
    "knowledge_risks": "Knowledge risks",
    "terminology_drift": "Terminology drift",
    "duplicate_candidates": "Possible duplicates",
    "orphaned_meetings": "Orphaned meeting notes",
}


def render_team_digest(brief, findings_by_id):
    if not brief:
        st.info("No Team Digest has been generated yet.")
        return
    content = brief["polished"] or brief["deterministic"]
    source = f"Polished with {brief['model']}" if brief["polished"] else "Deterministic"
    st.caption(
        f"{brief['window_start']} to {brief['window_end']} · {source} · "
        f"generated {brief['created_at'][:16].replace('T', ' ')} UTC"
    )
    for section, label in BRIEF_SECTION_LABELS.items():
        claims = content.get("sections", {}).get(section, [])
        if not claims:
            continue
        st.markdown(f"**{label}**")
        for index, claim in enumerate(claims):
            evidence_ids = claim.get("evidence_ids", [])
            st.markdown(f"- {claim['text']}")
            if evidence_ids:
                with st.expander(f"Evidence · {len(evidence_ids)} item(s)", expanded=False):
                    for finding_id in evidence_ids:
                        finding = findings_by_id.get(finding_id)
                        if not finding:
                            st.caption(f"Evidence record {finding_id} is unavailable.")
                            continue
                        evidence = finding["evidence"]
                        title = evidence.get("document_title", finding["document_id"])
                        url = evidence.get("document_url", "")
                        signal = evidence.get("signal", finding["signal_type"])
                        st.markdown(f"**[{title}]({url})** — {signal}" if url else f"**{title}** — {signal}")
                        st.json(evidence.get("metrics", {}), expanded=False)


# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.title("🔗 Liminal Drive Analytics")
st.sidebar.markdown("---")

shared_drive_sources = [
    source for source in load_sources()
    if os.path.exists(source.get("database_path", ""))
]
workspace_paths = {
    "Demo product team": DEMO_DB_PATH,
    "Live Drive": DB_PATH,
}
for source in shared_drive_sources:
    workspace_paths[f"Shared Drive · {source['name']}"] = source["database_path"]

data_mode = st.sidebar.radio(
    "Workspace",
    list(workspace_paths),
    help="Demo mode uses a separate fictional dataset and never reads or changes your Drive data.",
)
database_path = workspace_paths[data_mode]
is_demo = data_mode == "Demo product team"
is_shared_drive = data_mode.startswith("Shared Drive · ")

if is_demo and not os.path.exists(DEMO_DB_PATH):
    reset_demo_database()

if is_demo:
    st.sidebar.caption("Fictional Northstar product team · Orbit Mobile launch")
    if st.sidebar.button("Reset demo data", use_container_width=True):
        reset_demo_database()
        load_data.clear()
        st.rerun()
elif is_shared_drive:
    selected_source = next(
        source for source in shared_drive_sources
        if source["database_path"] == database_path
    )
    st.sidebar.caption(
        f"Shared Drive ID: {selected_source['id']} · indexed "
        f"{selected_source.get('indexed_at', '')[:10]}"
    )

st.sidebar.markdown("---")
recent_days = st.sidebar.slider("Recent window (days)", 3, 30, 7)
prior_days  = st.sidebar.slider("Comparison window (days)", 3, 30, 7)
top_n       = st.sidebar.slider("Results per section", 5, 25, 10)

st.sidebar.markdown("---")

# ── Path-significant domains config ──────────────────────────────────────────
import json as _json

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return _json.load(f)
    except Exception:
        return {"path_significant_domains": []}

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        _json.dump(cfg, f, indent=2)

cfg = load_config()
current_domains = "\n".join(cfg.get("path_significant_domains", []))

if not is_demo:
    with st.sidebar.expander("⚙️ Path-significant domains"):
        st.caption("Domains where the URL path identifies a specific resource (e.g. github.com/org/repo). One domain per line.")
        new_domains = st.text_area("Domains", value=current_domains, height=180, label_visibility="collapsed")
        if st.button("Save", key="save_path_domains"):
            updated = [d.strip() for d in new_domains.splitlines() if d.strip()]
            cfg["path_significant_domains"] = updated
            save_config(cfg)
            st.success(f"Saved {len(updated)} domains. Re-run --reclassify to apply.")

st.sidebar.markdown("---")
if is_demo:
    st.sidebar.caption("Demo data is isolated from your Drive and can be reset at any time.")
elif is_shared_drive:
    st.sidebar.caption("Re-run the indexer with this Shared Drive URL or ID to refresh its data.")
else:
    st.sidebar.caption("Data refreshes every 5 minutes. Re-run the indexer to pull latest Drive activity.")

data = load_data(recent_days, prior_days, database_path)
titles  = data["titles"]
urls    = data["urls"]
mimes   = data["mimes"]

# ── Session state for doc detail ──────────────────────────────────────────────

if "detail_doc_id" not in st.session_state:
    st.session_state["detail_doc_id"] = None
if "graph_focus_id" not in st.session_state:
    st.session_state["graph_focus_id"] = None

def open_detail(doc_id):
    st.session_state["detail_doc_id"] = doc_id

def close_detail():
    st.session_state["detail_doc_id"] = None

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_overview, tab_attention, tab_graph, tab_external, tab_detail = st.tabs([
    "📊 Overview", "🔍 Doc Audit", "🕸️ Graph", "🌐 External Links", "📄 Doc Detail"
])

activity      = data["activity"]
G             = data["G"]
in_deg        = data["in_deg"]
community_map = data["community_map"]

# ── Overview tab ──────────────────────────────────────────────────────────────

with tab_overview:
    st.header("Overview")
    if is_demo:
        st.info(
            "**Demo workspace:** Northstar's product team is preparing the Orbit Mobile launch. "
            "Explore the brief, review queue, graph, and document details using fictional data."
        )
    brief_col, deterministic_col, polished_col = st.columns([6, 2, 2])
    with brief_col:
        st.subheader("Team Digest")
    with deterministic_col:
        if st.button("Generate brief", use_container_width=True):
            conn = connect(database_path)
            init(conn)
            generate_brief(conn, days=recent_days)
            conn.close()
            load_data.clear()
            st.rerun()
    with polished_col:
        if st.button("Generate + polish", use_container_width=True):
            conn = connect(database_path)
            init(conn)
            generate_brief(
                conn, days=recent_days, polish=True,
                model=cfg.get("openai_model", "gpt-5.4-mini"),
            )
            conn.close()
            load_data.clear()
            st.rerun()

    render_team_digest(data["current_brief"], data["findings_by_id"])

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("Documents indexed", data["doc_count"])
    c2.metric("Doc → doc links",   data["link_count"])
    c3.metric("External links",    data["ext_count"])

    st.markdown("---")
    st.subheader(f"📈 Rising (last {recent_days}d vs prior {prior_days}d)")
    rising = rising_docs(activity, titles, top_n)
    if rising:
        rows = [{"Document": titles.get(d, d), "_url": urls.get(d, ""), "_id": d,
                 "Recent": rec, "Prior": pri, "Change": f"+{gain}"}
                for d, gain, rec, pri in rising]
        doc_table(rows, "Document", "_url", ["Recent", "Prior", "Change"],
                  id_col="_id", context="rising", data=data)
    else:
        st.info("No rising documents in this window.")

    st.markdown("---")
    st.subheader(f"📉 Stale (≤{STALE_RECENT_MAX} activity in last {STALE_WINDOW_DAYS}d)")
    stale = stale_docs(data["stale_act"], list(in_deg.items()), titles, top_n)
    if stale:
        rows = []
        for doc_id, recent, hist_total, indeg, dropoff in stale:
            hist_avg = data["stale_act"][doc_id]["history_daily_avg"]
            flags = []
            if indeg > 0: flags.append(f"{indeg} inbound links")
            flags.append(f"{hist_avg:.1f}/day historically")
            rows.append({"Document": titles.get(doc_id, doc_id),
                         "_url": urls.get(doc_id, ""),
                         "_id": doc_id,
                         "Why it matters": ", ".join(flags)})
        doc_table(rows, "Document", "_url", ["Why it matters"],
                  id_col="_id", context="stale", data=data)
    else:
        st.info("No stale documents detected.")

    st.markdown("---")
    st.subheader("🏛️ Hub Documents (most inbound links)")
    hub_rows = []
    for doc_id, deg in sorted(in_deg.items(), key=lambda x: x[1], reverse=True):
        if deg == 0 or doc_id not in titles: continue
        hub_rows.append({"Document": titles[doc_id], "_url": urls.get(doc_id, ""),
                         "_id": doc_id, "Inbound links": deg})
        if len(hub_rows) >= top_n: break
    if hub_rows:
        doc_table(hub_rows, "Document", "_url", ["Inbound links"], id_col="_id", context="hub", data=data)
    else:
        st.info("No hub documents found. Try running the indexer with --expand or --days 365.")

    st.markdown("---")
    col_owners, col_editors = st.columns(2)

    with col_owners:
        st.subheader("✍️ Top Document Owners")
        owner_rows = [{"Owner": email, "Docs owned": cnt}
                      for email, cnt in data["owner_by_email"].items()]
        if owner_rows:
            st.dataframe(pd.DataFrame(owner_rows[:top_n]), width="stretch", hide_index=True)
        else:
            st.caption("No owner data available.")

    with col_editors:
        st.subheader("🖊️ Top Editors")
        if data["top_editors"]:
            st.dataframe(pd.DataFrame(data["top_editors"][:top_n]),
                         width="stretch", hide_index=True)
        else:
            st.caption("No editor activity recorded yet.")

    st.markdown("---")
    st.subheader("📅 Activity over time (top docs)")
    if data["time_series"]:
        df_ts = pd.DataFrame(data["time_series"])
        df_ts["date"] = pd.to_datetime(df_ts["date"])
        fig = px.line(df_ts, x="date", y="activity", color="doc",
                      labels={"date": "", "activity": "Activity", "doc": "Document"})
        fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(fig, use_container_width=True)


# ── Needs Attention tab ───────────────────────────────────────────────────────

with tab_attention:
    st.header("Doc Audit")
    st.caption("Review and resolve persistent operational findings. Source documents are never modified.")

    all_signal_types = ["stale_hub", "rising", "went_quiet", "terminology_drift", "duplicate_candidate", "orphaned_meeting_doc"]
    signal_display = [SIGNAL_DISPLAY_NAMES.get(s, s) for s in all_signal_types]
    signal_name_to_type = {SIGNAL_DISPLAY_NAMES.get(s, s): s for s in all_signal_types}

    filter_status, filter_signal, filter_activity = st.columns(3)
    status_filter = filter_status.multiselect(
        "Status", sorted(FINDING_STATUSES), default=["new", "in_review"]
    )
    selected_signal_labels = filter_signal.multiselect(
        "Signal", signal_display, default=signal_display,
    )
    signal_filter = [signal_name_to_type[label] for label in selected_signal_labels]
    activity_filter = filter_activity.radio(
        "Activity", ["Active", "All", "Inactive"], horizontal=True
    )

    queue = []
    for finding in data["operational_findings"]:
        if status_filter and finding["status"] not in status_filter:
            continue
        if signal_filter and finding["signal_type"] not in signal_filter:
            continue
        if activity_filter == "Active" and not finding["active"]:
            continue
        if activity_filter == "Inactive" and finding["active"]:
            continue
        queue.append(finding)

    if not queue:
        st.success("No findings match the current filters.")
    for finding in queue[:top_n * 2]:
        evidence = finding["evidence"]
        title = evidence.get("document_title", finding["document_id"])
        signal = evidence.get("signal", finding["signal_type"])
        signal_label = SIGNAL_DISPLAY_NAMES.get(finding["signal_type"], finding["signal_type"])
        marker = "Active" if finding["active"] else "Inactive"
        with st.expander(
            f"{finding['severity']} · {signal_label} · {title} · {finding['status']} · {marker}",
            expanded=False,
        ):
            left, right = st.columns([2, 1])
            with left:
                url = evidence.get("document_url", "")
                st.markdown(f"**[{title}]({url})**" if url else f"**{title}**")
                st.write(signal)
                st.caption(f"Suggested action: {finding['suggested_action']}")
            with right:
                st.metric("Score", finding["score"])
                st.caption(
                    f"First detected {finding['first_detected_at'][:10]} · "
                    f"last detected {finding['last_detected_at'][:10]}"
                )
            st.json(evidence.get("metrics", {}), expanded=False)

            with st.form(f"review_{finding['id']}"):
                c_status, c_disposition = st.columns(2)
                status_options = sorted(FINDING_STATUSES)
                status = c_status.selectbox(
                    "Status", status_options,
                    index=status_options.index(finding["status"]),
                )
                disposition_options = [""] + sorted(DISPOSITIONS)
                current_disposition = finding.get("disposition") or ""
                disposition = c_disposition.selectbox(
                    "Disposition", disposition_options,
                    index=disposition_options.index(current_disposition),
                )
                c_reviewer, c_assignee, c_followup = st.columns(3)
                reviewer = c_reviewer.text_input("Reviewer", value=finding.get("reviewer") or "")
                assignee = c_assignee.text_input("Assignee", value=finding.get("assignee") or "")
                follow_up = c_followup.text_input(
                    "Follow-up date", value=finding.get("follow_up_date") or "",
                    placeholder="YYYY-MM-DD",
                )
                note = st.text_area("Review note", value=finding.get("note") or "")
                submitted = st.form_submit_button("Save review")
                if submitted:
                    conn = connect(database_path)
                    init(conn)
                    update_review(conn, finding["id"], {
                        "status": status,
                        "disposition": disposition or None,
                        "reviewer": reviewer,
                        "assignee": assignee,
                        "follow_up_date": follow_up,
                        "note": note,
                    })
                    conn.close()
                    load_data.clear()
                    st.rerun()

            history = finding.get("review_history", [])
            if history:
                st.dataframe(pd.DataFrame(history), width="stretch", hide_index=True)


# ── Graph tab ─────────────────────────────────────────────────────────────────

with tab_graph:
    st.header("Document Graph")

    # Controls
    ca, cb, cc, cd = st.columns(4)
    min_degree   = ca.slider("Min inbound links", 0, 5, 0)
    show_unknown = cb.checkbox("Show unindexed nodes", value=False)
    physics      = cc.checkbox("Physics simulation", value=True)
    color_mode   = cd.radio("Color by", ["Status", "Cluster"], horizontal=True)

    # Neighborhood focus
    focus_id = st.session_state.get("graph_focus_id")
    sorted_doc_titles = sorted([(v, k) for k, v in titles.items()])
    focus_options = ["(full graph)"] + [f"{t} [{i[:8]}]" for t, i in sorted_doc_titles]
    focus_label = st.selectbox("Focus on document (shows 2-hop neighborhood)",
                               focus_options,
                               index=0 if not focus_id else
                               next((i+1 for i,(t,di) in enumerate(sorted_doc_titles)
                                     if di == focus_id), 0))
    if focus_label != "(full graph)":
        bracket = focus_label.rfind("[")
        prefix  = focus_label[bracket+1:bracket+9]
        focus_id = next((di for t, di in sorted_doc_titles if di.startswith(prefix)), None)
        st.session_state["graph_focus_id"] = focus_id
    else:
        focus_id = None
        st.session_state["graph_focus_id"] = None

    # Build node set
    if focus_id and focus_id in G.nodes():
        # 2-hop neighborhood
        neighbors_1 = set(G.successors(focus_id)) | set(G.predecessors(focus_id))
        neighbors_2 = set()
        for n in neighbors_1:
            neighbors_2 |= set(G.successors(n)) | set(G.predecessors(n))
        nodes_to_show = ({focus_id} | neighbors_1 | neighbors_2)
        if not show_unknown:
            nodes_to_show = {n for n in nodes_to_show if n in titles}
    else:
        nodes_to_show = {n for n in G.nodes()
                         if (show_unknown or n in titles) and in_deg.get(n, 0) >= min_degree}

    subG = G.subgraph(nodes_to_show)

    # Status color map
    STATUS_COLORS = {
        "stale_hub": "#E63946",   # red
        "rising":    "#2DC653",   # green
        "hub":       "#F4A261",   # gold
        "stale":     "#A8DADC",   # muted blue
        "normal":    "#457B9D",   # steel blue
        "unknown":   "#555555",   # grey
    }

    def node_status_color(node_id):
        if node_id in data["stale_hub_ids"]:  return STATUS_COLORS["stale_hub"]
        if node_id in data["rising_ids"]:     return STATUS_COLORS["rising"]
        if node_id in data["hub_ids"]:        return STATUS_COLORS["hub"]
        if node_id in data["stale_ids"]:      return STATUS_COLORS["stale"]
        if node_id in titles:                 return STATUS_COLORS["normal"]
        return STATUS_COLORS["unknown"]

    CLUSTER_COLORS = ["#4C72B0","#DD8452","#55A868","#C44E52","#8172B3",
                      "#937860","#DA8BC3","#CCB974","#64B5CD","#E63946"]

    if len(subG) == 0:
        st.warning("No nodes to display with current filters.")
    else:
        net = Network(height="600px", width="100%", directed=True,
                      bgcolor="#0e1117", font_color="white")
        net.barnes_hut(gravity=-8000, central_gravity=0.3, spring_length=120)
        if not physics:
            net.toggle_physics(False)

        max_deg = max((in_deg.get(n, 0) for n in subG.nodes()), default=1)

        for node in subG.nodes():
            label     = titles.get(node, "[unindexed]")
            short     = label[:30] + ("…" if len(label) > 30 else "")
            deg       = in_deg.get(node, 0)
            community = community_map.get(node, -1)
            cl_label  = data["cluster_labels"].get(community, f"cluster {community}")

            if color_mode == "Status":
                color = node_status_color(node)
                status = ("stale hub" if node in data["stale_hub_ids"] else
                          "rising"    if node in data["rising_ids"]    else
                          "hub"       if node in data["hub_ids"]       else
                          "stale"     if node in data["stale_ids"]     else "normal")
                tooltip = f"{label}\nStatus: {status}\nInbound links: {deg}\nCluster: {cl_label}"
            else:
                color   = CLUSTER_COLORS[community % len(CLUSTER_COLORS)] if community >= 0 else "#555555"
                tooltip = f"{label}\nCluster: {cl_label}\nInbound links: {deg}"

            # Highlight focus node
            border = "#FFFFFF" if node == focus_id else color
            size   = 10 + (deg / max(max_deg, 1)) * 30
            if node == focus_id:
                size = max(size, 25)

            net.add_node(node, label=short, title=tooltip, color={"background": color, "border": border},
                         size=size, shape="dot")

        for src, dst in subG.edges():
            highlight = focus_id and (src == focus_id or dst == focus_id)
            net.add_edge(src, dst,
                         color="#FFFFFF" if highlight else "#333333",
                         width=2 if highlight else 1,
                         arrows="to")

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
            net.save_graph(f.name)
            html = open(f.name).read()

        st.components.v1.html(html, height=620, scrolling=False)

        if color_mode == "Status":
            st.caption(
                "🔴 Stale hub — linked but inactive  "
                "🟢 Rising  "
                "🟡 Hub (healthy)  "
                "🔵 Stale  "
                "⚫ Normal  "
                f"· {len(subG.nodes())} nodes · {len(subG.edges())} edges"
            )
        else:
            st.caption(f"Color = cluster · {len(subG.nodes())} nodes · {len(subG.edges())} edges")

    # Cluster table with labels
    st.markdown("---")
    st.subheader("Clusters")
    cluster_rows = []
    for i, cluster in enumerate(sorted(data["comms"], key=len, reverse=True)[:10]):
        known   = [titles[n] for n in cluster if n in titles]
        label   = data["cluster_labels"].get(
            next((k for k, c in enumerate(data["comms"]) if c == cluster), -1), "—")
        sample  = ", ".join(t[:28] for t in known[:3])
        stale_h = sum(1 for n in cluster if n in data["stale_hub_ids"])
        rising  = sum(1 for n in cluster if n in data["rising_ids"])
        cluster_rows.append({
            "Label":        label,
            "Docs":         len(cluster),
            "🔴 Stale hubs": stale_h,
            "🟢 Rising":     rising,
            "Sample docs":  sample + ("…" if len(known) > 3 else ""),
        })
    if cluster_rows:
        st.dataframe(pd.DataFrame(cluster_rows), width="stretch", hide_index=True)


# ── External links tab ────────────────────────────────────────────────────────

with tab_external:
    st.header("External Link Map")
    st.caption("Every URL linked from your indexed documents, grouped by domain.")
    if data["ext_by_apex"]:
        df_apex = pd.DataFrame(data["ext_by_apex"])
        fig = px.bar(df_apex.head(30), x="links", y="domain", orientation="h",
                     labels={"links": "Link count", "domain": "Domain"},
                     color="links", color_continuous_scale="Blues")
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, coloraxis_showscale=False,
                          height=600)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Grouped by apex domain — all subdomains rolled up (e.g. chrisbutler.substack.com → substack.com).")
        st.markdown("---")
        st.subheader("Full table (by subdomain)")
        st.dataframe(pd.DataFrame(data["ext_domains"]), width="stretch", hide_index=True)
    else:
        st.info("No external links found.")


# ── Doc Detail tab ────────────────────────────────────────────────────────────

with tab_detail:
    selected_id = st.session_state.get("detail_doc_id")

    if not selected_id:
        st.info("Click 🔍 on any document in the other tabs to view its detail here.")
        # Fallback: searchable dropdown
        sorted_docs = sorted(titles.items(), key=lambda x: x[1])
        options = ["—"] + [f"{v}" for k, v in sorted_docs]
        choice = st.selectbox("Or search for a document:", options)
        if choice != "—":
            selected_id = next((k for k, v in sorted_docs if v == choice), None)
            if selected_id:
                st.session_state["detail_doc_id"] = selected_id
                st.rerun()
    else:
        title   = titles.get(selected_id, selected_id)
        url     = doc_url(selected_id, urls.get(selected_id, ""), mimes.get(selected_id, ""))
        mime    = mimes.get(selected_id, "")
        mod     = data["modified"].get(selected_id, "")[:10]
        deg     = in_deg.get(selected_id, 0)
        cluster = community_map.get(selected_id, -1)
        cl_label = data["cluster_labels"].get(cluster, "—")
        act     = activity.get(selected_id, {"recent": 0, "prior": 0})

        # Status badge
        status = ("🔴 Stale hub" if selected_id in data["stale_hub_ids"] else
                  "🟢 Rising"    if selected_id in data["rising_ids"]    else
                  "🟡 Hub"       if selected_id in data["hub_ids"]       else
                  "🔵 Stale"     if selected_id in data["stale_ids"]     else "⚫ Normal")

        hcol, xcol = st.columns([11, 1])
        with hcol:
            st.header(f"{mime_icon(mime)} {title}")
            cols = st.columns(3)
            cols[0].markdown(f"**Status:** {status}")
            cols[1].markdown(f"**Cluster:** {cl_label}")
            if url:
                cols[2].markdown(f"[Open in Google Drive →]({url})")
        with xcol:
            if st.button("✕", key="close_detail", help="Clear selection"):
                st.session_state["detail_doc_id"] = None
                st.rerun()

        st.markdown("---")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Inbound links",   deg)
        m2.metric("Recent activity", act["recent"])
        m3.metric("Prior activity",  act["prior"])
        m4.metric("Last modified",   mod)

        st.markdown("---")
        col_in, col_out = st.columns(2)
        with col_in:
            st.subheader("📥 Linked from")
            inbound = data["inbound_links"].get(selected_id, [])
            if inbound:
                for src_id in inbound:
                    src_title = titles.get(src_id, "[unindexed]")
                    src_url   = doc_url(src_id, urls.get(src_id, ""), mimes.get(src_id, ""))
                    st.markdown(f"- [{src_title}]({src_url})" if src_url else f"- {src_title}")
            else:
                st.caption("No indexed documents link to this one.")
        with col_out:
            st.subheader("📤 Links to")
            outbound = data["outbound_links"].get(selected_id, [])
            if outbound:
                for dst_id in outbound:
                    dst_title = titles.get(dst_id, "[unindexed]")
                    dst_url   = doc_url(dst_id, urls.get(dst_id, ""), mimes.get(dst_id, ""))
                    st.markdown(f"- [{dst_title}]({dst_url})" if dst_url else f"- {dst_title}")
            else:
                st.caption("No outbound links to indexed documents found.")

        st.markdown("---")
        st.subheader("📅 Activity history")
        history = data["all_activity_history"].get(selected_id)
        if history:
            df_h = pd.DataFrame(history)
            df_h["date"] = pd.to_datetime(df_h["date"])
            fig = px.bar(df_h, x="date", y=["views", "edits", "comments"],
                         labels={"date": "", "value": "Events", "variable": "Type"},
                         color_discrete_map={"views": "#4C72B0", "edits": "#55A868", "comments": "#DD8452"})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No activity history for this document.")

        col_contrib, col_ext = st.columns(2)
        with col_contrib:
            st.subheader("👤 Contributors")
            editors = data["doc_editors"].get(selected_id, [])
            if editors:
                st.dataframe(pd.DataFrame(editors), width="stretch", hide_index=True)
            else:
                st.caption("No contributor activity recorded.")
        with col_ext:
            st.subheader("🌐 External links")
            ext = data["doc_external"].get(selected_id, [])
            if ext:
                for e in ext[:20]:
                    lbl = e["anchor"] or e["domain"]
                    st.markdown(f"- [{lbl}]({e['url']})" if e["url"] else f"- {lbl}")
                if len(ext) > 20:
                    st.caption(f"…and {len(ext)-20} more")
            else:
                st.caption("No external links found in this document.")
