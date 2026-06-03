"""Build a NetworkX graph from the SQLite store."""

import networkx as nx
from db import connect


def build_doc_graph(conn):
    """Directed graph of document → document links."""
    G = nx.DiGraph()

    for row in conn.execute("SELECT id, title, mime_type, modified_at FROM documents"):
        G.add_node(row["id"], title=row["title"], mime_type=row["mime_type"], modified_at=row["modified_at"])

    for row in conn.execute("SELECT src_id, dst_id FROM doc_links"):
        src, dst = row["src_id"], row["dst_id"]
        if G.has_node(src):  # only add edges where we've indexed both ends
            if not G.has_node(dst):
                G.add_node(dst, title="[not indexed]")
            G.add_edge(src, dst)

    return G


def in_degree_rank(G):
    """Documents sorted by number of other docs linking to them."""
    return sorted(G.in_degree(), key=lambda x: x[1], reverse=True)


def hub_scores(G):
    """HITS algorithm: returns (hub_scores, authority_scores) dicts."""
    if len(G) == 0:
        return {}, {}
    try:
        return nx.hits(G, max_iter=1000)
    except nx.PowerIterationFailedConvergence:
        return {}, {}


def betweenness(G):
    if len(G) < 3:
        return {}
    return nx.betweenness_centrality(G)


def communities(G):
    """Louvain community detection on undirected version of doc graph."""
    U = G.to_undirected()
    if len(U) == 0:
        return []
    return list(nx.community.louvain_communities(U, seed=42))
