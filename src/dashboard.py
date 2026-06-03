"""Streamlit dashboard for Liminal Drive Analytics."""

import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from pyvis.network import Network

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import connect
from graph import build_doc_graph, in_degree_rank, communities
from analytics import activity_by_doc, title_map, rising_docs, stale_docs

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Liminal Drive Analytics",
    page_icon="🔗",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def doc_link(title, url, max_len=55):
    short = title[:max_len] + ("…" if len(title) > max_len else "")
    if url:
        return f"[{short}]({url})"
    return short

def mime_icon(mime):
    if "document" in mime:
        return "📄"
    if "presentation" in mime:
        return "📊"
    return "📁"

# ── Load data (cached) ────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_data(recent_days, prior_days):
    conn = connect()

    titles = title_map(conn)
    urls = {row["id"]: row["web_url"] or "" for row in conn.execute(
        "SELECT id, web_url FROM documents"
    )}
    mimes = {row["id"]: row["mime_type"] or "" for row in conn.execute(
        "SELECT id, mime_type FROM documents"
    )}
    modified = {row["id"]: row["modified_at"] or "" for row in conn.execute(
        "SELECT id, modified_at FROM documents"
    )}

    activity = activity_by_doc(conn, days_recent=recent_days, days_prior=prior_days)
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

    ext_domains = [
        {"domain": r["domain"], "links": r["cnt"]}
        for r in conn.execute("""
            SELECT er.domain, COUNT(*) as cnt
            FROM external_links el
            JOIN external_resources er ON el.resource_id = er.id
            WHERE er.domain != '' AND er.domain != 'unknown'
            GROUP BY er.domain ORDER BY cnt DESC LIMIT 40
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

    # Top editors — by distinct docs touched and by total edit count
    # person_id is a Google People resource name (e.g. "people/12345").
    # We resolve to owner_email where possible; otherwise show the raw id.
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
            "person_id": row["person_id"],
            "docs_edited": row["doc_count"],
            "total_edits": row["total_edits"],
        })

    # Per-doc editors for detail view
    doc_editors = {}
    for row in conn.execute("""
        SELECT document_id, person_id, action, count, last_seen
        FROM person_activity
        ORDER BY count DESC
    """):
        doc_editors.setdefault(row["document_id"], []).append({
            "person_id": row["person_id"],
            "action": row["action"],
            "count": row["count"],
            "last_seen": row["last_seen"][:10] if row["last_seen"] else "",
        })

    conn.close()
    return {
        "titles": titles, "urls": urls, "mimes": mimes, "modified": modified,
        "activity": activity, "G": G, "in_deg": in_deg,
        "community_map": community_map, "comms": comms,
        "doc_count": doc_count, "link_count": link_count,
        "ext_count": ext_count, "act_days": act_days,
        "ext_domains": ext_domains, "time_series": time_series,
        "all_activity_history": all_activity_history,
        "inbound_links": inbound_links, "outbound_links": outbound_links,
        "doc_external": doc_external,
        "owner_by_email": owner_by_email,
        "top_editors": top_editors,
        "doc_editors": doc_editors,
    }


def direness_score(priority_tier, in_deg_count=0, gain=0, prior_act=0):
    """0–10 score indicating how urgent this item is."""
    if priority_tier == "high":
        # Stale hub: base 6, +1 per inbound link up to 10
        return min(10, 6 + in_deg_count)
    elif priority_tier == "medium":
        # Rising: base 4, scales with activity gain
        return min(7, 4 + round(gain / 10))
    else:
        # Went quiet: scales with prior activity
        return min(5, 2 + round(prior_act / 10))


def needs_attention(data, recent_days, top_n=15):
    """Single prioritized list combining stale hub, rising, and orphan signals."""
    activity = data["activity"]
    in_deg   = data["in_deg"]
    titles   = data["titles"]
    urls     = data["urls"]

    items = []
    seen  = set()

    # Stale hubs — highest priority
    for doc_id, deg in sorted(in_deg.items(), key=lambda x: x[1], reverse=True):
        if doc_id not in titles or deg == 0:
            continue
        counts = activity.get(doc_id, {"recent": 0, "prior": 0})
        if counts["recent"] == 0:
            score = direness_score("high", in_deg_count=deg)
            items.append({
                "_score": score,
                "_url": urls.get(doc_id, ""),
                "Score": f"{score}/10",
                "Priority": "🔴 High",
                "Document": titles[doc_id],
                "Signal": f"Stale hub — {deg} doc{'s' if deg != 1 else ''} link here",
                "Action": "Review accuracy or add a deprecation notice",
                "_id": doc_id,
            })
            seen.add(doc_id)

    # Rising docs
    rising = rising_docs(activity, titles, top_n * 2)
    for doc_id, gain, rec, pri in rising:
        if doc_id in seen or doc_id not in titles:
            continue
        score = direness_score("medium", gain=gain)
        items.append({
            "_score": score,
            "_url": urls.get(doc_id, ""),
            "Score": f"{score}/10",
            "Priority": "🟡 Medium",
            "Document": titles[doc_id],
            "Signal": f"Rising — +{gain} activity ({pri}→{rec})",
            "Action": "Good time to review, update, or link from an index doc",
            "_id": doc_id,
        })
        seen.add(doc_id)

    # Stale with prior activity
    stale = stale_docs(activity, list(in_deg.items()), titles, top_n * 2)
    for doc_id, prior_act, indeg in stale:
        if doc_id in seen or doc_id not in titles:
            continue
        if prior_act > 5:
            score = direness_score("low", prior_act=prior_act)
            items.append({
                "_score": score,
                "_url": urls.get(doc_id, ""),
                "Score": f"{score}/10",
                "Priority": "🔵 Low",
                "Document": titles[doc_id],
                "Signal": f"Went quiet — {prior_act} prior activity, none in {recent_days}d",
                "Action": "Archive, update, or leave as-is if complete",
                "_id": doc_id,
            })
            seen.add(doc_id)

    # Sort by score descending
    items.sort(key=lambda x: x["_score"], reverse=True)
    return items[:top_n]


# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.title("🔗 Liminal Drive Analytics")
st.sidebar.markdown("---")

recent_days = st.sidebar.slider("Recent window (days)", 3, 30, 7)
prior_days  = st.sidebar.slider("Comparison window (days)", 3, 30, 7)
top_n       = st.sidebar.slider("Results per section", 5, 25, 10)

st.sidebar.markdown("---")

# Doc detail selector in sidebar
data = load_data(recent_days, prior_days)
titles  = data["titles"]
urls    = data["urls"]
mimes   = data["mimes"]

sorted_titles = sorted(titles.items(), key=lambda x: x[1])
doc_options   = ["(none)"] + [f"{v} [{k[:8]}]" for k, v in sorted_titles]
selected_label = st.sidebar.selectbox("🔍 View doc detail", doc_options)

st.sidebar.markdown("---")
st.sidebar.caption("Data refreshes every 5 minutes. Re-run the indexer to pull latest Drive activity.")

# ── Tabs ──────────────────────────────────────────────────────────────────────

if selected_label != "(none)":
    tab_overview, tab_attention, tab_graph, tab_external, tab_detail = st.tabs([
        "📊 Overview", "🎯 Needs Attention", "🕸️ Graph", "🌐 External Links", "📄 Doc Detail"
    ])
else:
    tab_overview, tab_attention, tab_graph, tab_external = st.tabs([
        "📊 Overview", "🎯 Needs Attention", "🕸️ Graph", "🌐 External Links"
    ])
    tab_detail = None

activity      = data["activity"]
G             = data["G"]
in_deg        = data["in_deg"]
community_map = data["community_map"]

# ── Overview tab ──────────────────────────────────────────────────────────────

with tab_overview:
    st.header("Overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Documents indexed",    data["doc_count"])
    c2.metric("Doc → doc links",      data["link_count"])
    c3.metric("External links",       data["ext_count"])
    c4.metric("Activity days tracked",data["act_days"])

    st.markdown("---")
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader(f"📈 Rising (last {recent_days}d vs prior {prior_days}d)")
        rising = rising_docs(activity, titles, top_n)
        if rising:
            rows = [{"Document": titles.get(d, d), "_url": urls.get(d, ""),
                     "Recent": rec, "Prior": pri, "Change": f"+{gain}"}
                    for d, gain, rec, pri in rising]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                column_config={"_url": st.column_config.LinkColumn("Open", display_text="↗", width="small")})
        else:
            st.info("No rising documents in this window.")

    with col_r:
        st.subheader(f"📉 Stale (no activity in {recent_days}d)")
        stale = stale_docs(activity, list(in_deg.items()), titles, top_n)
        if stale:
            rows = []
            for doc_id, prior_act, indeg in stale:
                flags = []
                if indeg    > 0: flags.append(f"{indeg} inbound links")
                if prior_act > 0: flags.append(f"{prior_act} prior activity")
                rows.append({"Document": titles.get(doc_id, doc_id),
                             "_url": urls.get(doc_id, ""),
                             "Why it matters": ", ".join(flags)})
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                column_config={"_url": st.column_config.LinkColumn("Open", display_text="↗", width="small")})
        else:
            st.info("No stale documents detected.")

    st.markdown("---")
    st.subheader("🏛️ Hub Documents (most inbound links)")
    hub_rows = []
    for doc_id, deg in sorted(in_deg.items(), key=lambda x: x[1], reverse=True):
        if deg == 0 or doc_id not in titles: continue
        hub_rows.append({"Document": titles[doc_id], "_url": urls.get(doc_id, ""),
                         "Inbound links": deg})
        if len(hub_rows) >= top_n: break
    if hub_rows:
        st.dataframe(pd.DataFrame(hub_rows), width="stretch", hide_index=True,
            column_config={"_url": st.column_config.LinkColumn("Open", display_text="↗", width="small")})
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
            st.dataframe(
                pd.DataFrame(data["top_editors"][:top_n]).rename(columns={
                    "person_id": "Person ID",
                    "docs_edited": "Docs edited",
                    "total_edits": "Total edits",
                }),
                width="stretch", hide_index=True,
            )
            st.caption("⚠️ The Drive Activity API returns opaque person identifiers, not names. Resolving these to real names/emails requires adding the Google People API scope — tracked in FUTURE_IDEAS.md.")
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
        st.plotly_chart(fig, width="stretch")


# ── Needs Attention tab ───────────────────────────────────────────────────────

with tab_attention:
    st.header("🎯 Needs Attention")
    st.caption("Prioritized list of documents that warrant a look, based on combined signals.")

    items = needs_attention(data, recent_days, top_n=top_n * 2)
    if not items:
        st.success("Nothing urgent right now.")
    else:
        display_cols = ["Score", "Priority", "Document", "_url", "Signal", "Action"]
        df = pd.DataFrame([{k: i[k] for k in display_cols} for i in items])
        st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            column_config={
                "Score": st.column_config.TextColumn("Score", width="small"),
                "Priority": st.column_config.TextColumn("Priority", width="small"),
                "Document": st.column_config.TextColumn("Document", width="medium"),
                "_url": st.column_config.LinkColumn("Open", display_text="↗", width="small"),
                "Signal": st.column_config.TextColumn("Signal", width="medium"),
                "Action": st.column_config.TextColumn("Suggested action", width="large"),
            },
        )

        st.markdown("---")
        st.subheader("Signal key")
        st.markdown("""
| Priority | Meaning |
|---|---|
| 🔴 High | Stale hub — other docs link here but it hasn't been touched recently |
| 🟡 Medium | Rising — gaining activity fast, worth keeping current |
| 🔵 Low | Went quiet — was active, now isn't; decide if it's done or drifting |
""")


# ── Graph tab ─────────────────────────────────────────────────────────────────

with tab_graph:
    st.header("Document Graph")
    ca, cb, cc = st.columns(3)
    min_degree   = ca.slider("Min inbound links to show", 0, 5, 0)
    show_unknown = cb.checkbox("Show unindexed nodes", value=False)
    physics      = cc.checkbox("Enable physics simulation", value=True)

    nodes_to_show = {n for n in G.nodes()
                     if (show_unknown or n in titles) and in_deg.get(n, 0) >= min_degree}
    subG = G.subgraph(nodes_to_show)

    if len(subG) == 0:
        st.warning("No nodes to display with current filters.")
    else:
        COLORS = ["#4C72B0","#DD8452","#55A868","#C44E52","#8172B3",
                  "#937860","#DA8BC3","#8C8C8C","#CCB974","#64B5CD"]
        net = Network(height="600px", width="100%", directed=True,
                      bgcolor="#0e1117", font_color="white")
        net.barnes_hut(gravity=-8000, central_gravity=0.3, spring_length=120)
        if not physics:
            net.toggle_physics(False)

        max_deg = max((in_deg.get(n, 0) for n in subG.nodes()), default=1)
        for node in subG.nodes():
            label    = titles.get(node, "[unindexed]")
            short    = label[:30] + ("…" if len(label) > 30 else "")
            deg      = in_deg.get(node, 0)
            community= community_map.get(node, -1)
            color    = COLORS[community % len(COLORS)] if community >= 0 else "#8C8C8C"
            size     = 10 + (deg / max(max_deg, 1)) * 30
            url      = urls.get(node, "")
            tooltip  = f"{label}\nInbound links: {deg}\nCluster: {community}"
            if url:
                tooltip += f"\n{url}"
            net.add_node(node, label=short, title=tooltip, color=color, size=size,
                         shape="dot", url=url)

        for src, dst in subG.edges():
            net.add_edge(src, dst, color="#444444", arrows="to")

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
            net.save_graph(f.name)
            html = open(f.name).read()

        st.components.v1.html(html, height=620, scrolling=False)
        st.caption(f"Showing {len(subG.nodes())} nodes · {len(subG.edges())} edges · "
                   f"Node size = inbound links · Color = cluster")

    st.markdown("---")
    st.subheader("Clusters")
    cluster_rows = []
    for i, cluster in enumerate(sorted(data["comms"], key=len, reverse=True)[:10]):
        known  = [titles[n] for n in cluster if n in titles]
        sample = ", ".join(t[:25] for t in known[:3])
        cluster_rows.append({"Cluster": i+1, "Total docs": len(cluster),
                              "Indexed": len(known),
                              "Sample": sample + ("…" if len(known) > 3 else "")})
    if cluster_rows:
        st.dataframe(pd.DataFrame(cluster_rows), width="stretch", hide_index=True)


# ── External links tab ────────────────────────────────────────────────────────

with tab_external:
    st.header("External Link Map")
    st.caption("Every URL linked from your indexed documents, grouped by domain.")
    if data["ext_domains"]:
        df_ext = pd.DataFrame(data["ext_domains"])
        fig = px.bar(df_ext.head(30), x="links", y="domain", orientation="h",
                     labels={"links": "Link count", "domain": "Domain"},
                     color="links", color_continuous_scale="Blues")
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, coloraxis_showscale=False)
        st.plotly_chart(fig, width="stretch")
        st.markdown("---")
        st.subheader("Full table")
        st.dataframe(df_ext, width="stretch", hide_index=True)
    else:
        st.info("No external links found.")


# ── Doc Detail tab ────────────────────────────────────────────────────────────

if tab_detail:
    with tab_detail:
        # Parse selected doc id from sidebar selection
        selected_id = None
        if selected_label != "(none)":
            bracket = selected_label.rfind("[")
            if bracket >= 0:
                prefix = selected_label[bracket+1:bracket+9]
                for doc_id in titles:
                    if doc_id.startswith(prefix):
                        selected_id = doc_id
                        break

        if not selected_id:
            st.info("Select a document from the sidebar to view its detail.")
        else:
            title   = titles.get(selected_id, selected_id)
            url     = urls.get(selected_id, "")
            mime    = mimes.get(selected_id, "")
            mod     = data["modified"].get(selected_id, "")[:10]
            deg     = in_deg.get(selected_id, 0)
            cluster = community_map.get(selected_id, -1)
            act     = activity.get(selected_id, {"recent": 0, "prior": 0})

            icon = mime_icon(mime)
            st.header(f"{icon} {title}")
            if url:
                st.markdown(f"[Open in Google Drive →]({url})")

            st.markdown("---")
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Inbound links",    deg)
            m2.metric("Recent activity",  act["recent"])
            m3.metric("Prior activity",   act["prior"])
            m4.metric("Last modified",    mod)
            m5.metric("Cluster",          cluster if cluster >= 0 else "—")

            st.markdown("---")
            col_in, col_out = st.columns(2)

            with col_in:
                st.subheader("📥 Linked from")
                inbound = data["inbound_links"].get(selected_id, [])
                if inbound:
                    for src_id in inbound:
                        src_title = titles.get(src_id, "[unindexed]")
                        src_url   = urls.get(src_id, "")
                        st.markdown(f"- {doc_link(src_title, src_url)}")
                else:
                    st.caption("No indexed documents link to this one.")

            with col_out:
                st.subheader("📤 Links to")
                outbound = data["outbound_links"].get(selected_id, [])
                if outbound:
                    for dst_id in outbound:
                        dst_title = titles.get(dst_id, "[unindexed]")
                        dst_url   = urls.get(dst_id, "")
                        st.markdown(f"- {doc_link(dst_title, dst_url)}")
                else:
                    st.caption("No outbound links to indexed documents found.")

            st.markdown("---")
            st.subheader("📅 Activity history")
            history = data["all_activity_history"].get(selected_id)
            if history:
                df_h = pd.DataFrame(history)
                df_h["date"]  = pd.to_datetime(df_h["date"])
                df_h["total"] = df_h["views"] + df_h["edits"] + df_h["comments"]
                fig = px.bar(df_h, x="date", y=["views","edits","comments"],
                             labels={"date": "", "value": "Events", "variable": "Type"},
                             color_discrete_map={"views": "#4C72B0","edits": "#55A868","comments": "#DD8452"})
                st.plotly_chart(fig, width="stretch")
            else:
                st.caption("No activity history for this document.")

            st.markdown("---")
            st.subheader("👤 Contributors")
            editors = data["doc_editors"].get(selected_id, [])
            if editors:
                st.dataframe(
                    pd.DataFrame(editors).rename(columns={
                        "person_id": "Person ID",
                        "action": "Action",
                        "count": "Count",
                        "last_seen": "Last seen",
                    }),
                    width="stretch", hide_index=True,
                )
                st.caption("Person IDs are Google People resource names. Real names require the People API — see FUTURE_IDEAS.md.")
            else:
                st.caption("No contributor activity recorded for this document.")

            st.markdown("---")
            st.subheader("🌐 External links in this doc")
            ext = data["doc_external"].get(selected_id, [])
            if ext:
                df_ext = pd.DataFrame(ext)
                df_ext["Link"] = df_ext.apply(
                    lambda r: f"[{r['anchor'] or r['domain']}]({r['url']})" if r["url"] else r["domain"],
                    axis=1
                )
                st.dataframe(df_ext[["domain", "Link"]].rename(columns={"domain": "Domain"}),
                             width="stretch", hide_index=True)
            else:
                st.caption("No external links found in this document.")
