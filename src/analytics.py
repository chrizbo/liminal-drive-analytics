"""Compute and print rising/stale/hub analytics."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from db import connect
from graph import build_doc_graph, in_degree_rank, communities
from storage import (
    activity_totals_by_doc,
    count_rows,
    document_title_rows,
    external_link_summary_rows,
)


STALE_WINDOW_DAYS    = 30   # inactivity window — no/little activity in this period
STALE_HISTORY_DAYS   = 90   # look-back for historical average
STALE_RECENT_MAX     = 2    # max activity in stale window to still count as stale
STALE_HISTORY_MIN    = 3    # minimum historical daily avg to care about at all


def _today(now=None):
    if now is None:
        return datetime.now(timezone.utc).date()
    if isinstance(now, str):
        return datetime.fromisoformat(now.replace("Z", "+00:00")).date()
    if isinstance(now, datetime):
        return now.date()
    return now


def activity_by_doc(conn, days_recent=7, days_prior=7, now=None, scope=None):
    """Returns {doc_id: {recent: N, prior: N}} activity totals."""
    today = _today(now)
    recent_start = (today - timedelta(days=days_recent)).isoformat()
    prior_start = (today - timedelta(days=days_recent + days_prior)).isoformat()
    prior_end = recent_start
    recent = activity_totals_by_doc(conn, recent_start, scope=scope)
    prior = activity_totals_by_doc(conn, prior_start, end_date=prior_end, scope=scope)

    all_ids = set(recent) | set(prior)
    return {doc_id: {"recent": recent.get(doc_id, 0), "prior": prior.get(doc_id, 0)} for doc_id in all_ids}


def stale_activity(conn, now=None, scope=None):
    """
    Returns {doc_id: {recent_30d: N, history_total: N, history_daily_avg: F}}
    Recent = last 30 days. History = prior 90 days before that.
    """
    today = _today(now)
    recent_start  = (today - timedelta(days=STALE_WINDOW_DAYS)).isoformat()
    history_start = (today - timedelta(days=STALE_WINDOW_DAYS + STALE_HISTORY_DAYS)).isoformat()
    recent = activity_totals_by_doc(conn, recent_start, scope=scope)
    history = activity_totals_by_doc(conn, history_start, end_date=recent_start, scope=scope)

    all_ids = set(recent) | set(history)
    result = {}
    for doc_id in all_ids:
        hist_total = history.get(doc_id, 0)
        result[doc_id] = {
            "recent_30d":      recent.get(doc_id, 0),
            "history_total":   hist_total,
            "history_daily_avg": round(hist_total / STALE_HISTORY_DAYS, 2),
        }
    return result


def title_map(conn, scope=None):
    return {row["id"]: row["title"] for row in document_title_rows(conn, scope)}


def rising_docs(activity, titles, top_n=10):
    """Docs where recent activity > prior activity, ranked by absolute gain."""
    candidates = []
    for doc_id, counts in activity.items():
        gain = counts["recent"] - counts["prior"]
        if gain > 0 and counts["recent"] > 0:
            candidates.append((doc_id, gain, counts["recent"], counts["prior"]))
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[:top_n]


def stale_docs(stale_act, in_degree, titles, top_n=10):
    """
    Docs with little/no activity in the last 30 days that used to be active.
    Ranked by how dramatic the drop-off is relative to historical average.
    """
    in_deg = dict(in_degree)
    candidates = []
    for doc_id, counts in stale_act.items():
        recent   = counts["recent_30d"]
        hist_avg = counts["history_daily_avg"]
        indeg    = in_deg.get(doc_id, 0)

        # Must be indexed and have a title
        if doc_id not in titles:
            continue
        # Must be below the recent activity threshold
        if recent > STALE_RECENT_MAX:
            continue
        # Must have meaningful historical activity OR be a hub
        if hist_avg < STALE_HISTORY_MIN and indeg == 0:
            continue

        # Drop-off score: how far below historical average the recent period is
        expected_30d = hist_avg * STALE_WINDOW_DAYS
        dropoff = max(0, expected_30d - recent)

        candidates.append((doc_id, recent, counts["history_total"], indeg, dropoff))

    # Sort: hubs first within each tier, then by dropoff magnitude
    candidates.sort(key=lambda x: (x[3] > 0, x[4]), reverse=True)
    return candidates[:top_n]


# Keep old signature available for needs_attention compatibility
def _stale_docs_compat(activity, in_degree, titles, top_n=10):
    """Compatibility shim used by needs_attention which passes activity dict."""
    in_deg = dict(in_degree)
    candidates = []
    for doc_id, counts in activity.items():
        if counts["recent"] == 0 and (counts["prior"] > 0 or in_deg.get(doc_id, 0) > 0):
            candidates.append((doc_id, counts["prior"], in_deg.get(doc_id, 0)))
    # rank by in-degree first (stale hubs are most important), then prior activity
    candidates.sort(key=lambda x: (x[2], x[1]), reverse=True)
    return candidates[:top_n]


def external_link_summary(conn, by="category", top_n=20):
    """Count external links. by='category' groups known domains into buckets;
    by='domain' shows every domain individually."""
    summary = defaultdict(int)
    if by == "category":
        group_by = "category"
    else:
        group_by = "domain"
    for row in external_link_summary_rows(conn, by=group_by, top_n=top_n):
        summary[row["label"]] = row["cnt"]
    return summary


def print_section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def run(top_n, recent_days, prior_days):
    conn = connect()
    titles = title_map(conn)
    activity = activity_by_doc(conn, days_recent=recent_days, days_prior=prior_days)
    G = build_doc_graph(conn)
    in_deg = in_degree_rank(G)

    doc_count = count_rows(conn, "documents")
    link_count = count_rows(conn, "doc_links")
    ext_count = count_rows(conn, "external_links")
    activity_days = count_rows(conn, "activity_snapshots", distinct="date")

    print_section("Overview")
    print(f"  Documents indexed : {doc_count}")
    print(f"  Doc → doc links   : {link_count}")
    print(f"  External links    : {ext_count}")
    print(f"  Activity days     : {activity_days}")
    print(f"  Graph nodes       : {G.number_of_nodes()}")
    print(f"  Graph edges       : {G.number_of_edges()}")

    print_section(f"Hub Documents (most inbound links)")
    shown = 0
    for doc_id, deg in in_deg:
        if deg == 0 or shown >= top_n:
            break
        title = titles.get(doc_id)
        if not title:
            continue  # skip unindexed nodes
        print(f"  {deg:>4} links  {title}")
        shown += 1
    if shown == 0:
        print("  No hub documents found (try re-indexing with --days 365 or --expand).")

    print_section(f"Rising Documents (last {recent_days}d vs prior {prior_days}d)")
    rising = rising_docs(activity, titles, top_n)
    if not rising:
        print("  No rising documents detected (may need more activity history).")
    for doc_id, gain, rec, pri in rising:
        title = titles.get(doc_id, "[unknown]")
        print(f"  +{gain:>3} activity  [{pri}→{rec}]  {title}")

    print_section(f"Stale Documents (≤{STALE_RECENT_MAX} activity in last {STALE_WINDOW_DAYS}d, was active before)")
    stale_act = stale_activity(conn)
    stale = stale_docs(stale_act, in_deg, titles, top_n)
    if not stale:
        print("  No stale documents detected.")
    for doc_id, recent, hist_total, indeg, dropoff in stale:
        title = titles.get(doc_id, "[unknown]")
        flags = []
        if indeg > 0:
            flags.append(f"{indeg} inbound links")
        flags.append(f"avg {stale_act[doc_id]['history_daily_avg']:.1f}/day historically")
        print(f"  {title}  ({', '.join(flags)})")

    print_section("External Link Map (top domains)")
    ext_summary = external_link_summary(conn, by="domain")
    if not ext_summary:
        print("  No external links found.")
    for domain, count in ext_summary.items():
        print(f"  {count:>4}  {domain}")

    print_section("Document Clusters")
    comms = communities(G)
    if not comms:
        print("  Not enough connected documents to detect clusters.")
    else:
        for i, cluster in enumerate(sorted(comms, key=len, reverse=True)[:5], 1):
            known = [titles[n] for n in cluster if n in titles]
            unknown_count = len(cluster) - len(known)
            sample = ", ".join(t[:35] for t in known[:4])
            suffix = f"... +{unknown_count} unindexed" if unknown_count else ("..." if len(known) > 4 else "")
            print(f"  Cluster {i} ({len(cluster)} docs): {sample}{suffix}")

    print()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Liminal Drive Analytics report")
    parser.add_argument("--top", type=int, default=10, help="How many results per section (default: 10)")
    parser.add_argument("--recent-days", type=int, default=7, help="Recent window in days (default: 7)")
    parser.add_argument("--prior-days", type=int, default=7, help="Prior comparison window in days (default: 7)")
    args = parser.parse_args()
    run(args.top, args.recent_days, args.prior_days)
