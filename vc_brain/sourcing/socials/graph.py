"""Deterministic connection-graph builder (no LLM).

Takes the connections and posts a provider returned and produces a `NetworkGraph`
(nodes/edges/metrics/notable-hits) — pure structural DATA. Scoring has moved to
the downstream consolidation stage (see the disabled `score_network` below).
Exports for viz are provided too (`to_forcegraph_json`, `to_gexf`).
"""

from __future__ import annotations

import networkx as nx

from vc_brain.sourcing.socials.models import (
    Connection,
    GraphEdge,
    GraphNode,
    Network,
    NetworkGraph,
    NotableHit,
    SocialPost,
)
from vc_brain.sourcing.socials.notable import lookup_notable, normalize_handle

_MENTION_WEIGHT = 0.5  # weight of a post-mention edge vs. an explicit follow (1.0)
# Scoring knobs (used only by the disabled score_network below; kept for reuse).
_PER_CATEGORY_CAP = 25.0
_NOTABLE_CAP = 70.0
_REACH_CAP = 30.0


def build_network_graph(
    seed_handle: str,
    network: Network,
    connections: list[Connection],
    posts: list[SocialPost] | None = None,
) -> NetworkGraph:
    """Build the connection graph (structure + notable tags) for one seed handle."""
    posts = posts or []
    seed = normalize_handle(seed_handle)
    g: nx.DiGraph = nx.DiGraph()
    if seed:
        g.add_node(seed)

    for c in connections:
        s = normalize_handle(c.source_handle)
        t = normalize_handle(c.target_handle)
        if not s or not t or s == t:
            continue
        _add_or_bump(g, s, t, c.weight, c.edge_type, c.source_url)

    # Engagement edges: seed -> people it mentions in its own posts.
    for p in posts:
        src = normalize_handle(p.author_handle) or seed
        for m in p.mentions:
            t = normalize_handle(m)
            if not t or t == src:
                continue
            _add_or_bump(g, src, t, _MENTION_WEIGHT, "mentions", p.url)

    return _finalize(g, seed, network)


def _add_or_bump(
    g: nx.DiGraph, s: str, t: str, weight: float, edge_type: str, source_url: str
) -> None:
    if g.has_edge(s, t):
        g[s][t]["weight"] += weight
    else:
        g.add_edge(s, t, weight=weight, edge_type=edge_type, source_url=source_url)


def _finalize(g: nx.DiGraph, seed: str, network: Network) -> NetworkGraph:
    centrality = nx.degree_centrality(g) if g.number_of_nodes() > 1 else {}

    notable_hits = _notable_hits(g, seed)
    notable_handles = {h.handle for h in notable_hits}

    nodes = [
        GraphNode(
            handle=n,
            network=network,
            label=n,
            is_seed=(n == seed),
            is_notable=(n in notable_handles),
            notable_category=_category_for(n, notable_hits),
            centrality=round(centrality.get(n, 0.0), 4),
        )
        for n in g.nodes()
    ]
    edges = [
        GraphEdge(
            source=u,
            target=v,
            edge_type=data.get("edge_type", "follows"),
            weight=round(data.get("weight", 1.0), 3),
        )
        for u, v, data in g.edges(data=True)
    ]
    top_central = [
        {"handle": h, "centrality": round(c, 4)}
        for h, c in sorted(centrality.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]

    return NetworkGraph(
        nodes=nodes,
        edges=edges,
        node_count=g.number_of_nodes(),
        edge_count=g.number_of_edges(),
        density=round(nx.density(g), 4) if g.number_of_nodes() > 1 else 0.0,
        top_central=top_central,
        notable_hits=notable_hits,
    )


def _notable_hits(g: nx.DiGraph, seed: str) -> list[NotableHit]:
    hits: list[NotableHit] = []
    for node in g.nodes():
        if node == seed:
            continue
        entry = lookup_notable(node)
        if not entry:
            continue
        hits.append(
            NotableHit(
                handle=node,
                name=entry.name,
                category=entry.category,
                weight=entry.weight,
                reason=_reason_for(g, seed, node, entry.category),
                source_url=_source_url_for(g, node),
            )
        )
    hits.sort(key=lambda h: h.weight, reverse=True)
    return hits


def _reason_for(g: nx.DiGraph, seed: str, node: str, category: str) -> str:
    if g.has_edge(seed, node):
        et = g[seed][node].get("edge_type", "follows")
        verb = {"follows": "follows", "mentions": "engages with", "replies": "replies to"}.get(
            et, "connected to"
        )
        return f"{seed} {verb} {node} ({category})"
    if g.has_edge(node, seed):
        return f"{node} follows {seed} ({category})"
    return f"in {seed}'s network ({category})"


def _source_url_for(g: nx.DiGraph, node: str) -> str:
    for _, _, data in g.in_edges(node, data=True):
        if data.get("source_url"):
            return data["source_url"]
    for _, _, data in g.out_edges(node, data=True):
        if data.get("source_url"):
            return data["source_url"]
    return f"https://twitter.com/{node}"


def _category_for(node: str, hits: list[NotableHit]) -> str:
    for h in hits:
        if h.handle == node:
            return h.category
    return ""


# ---------------------------------------------------------------------------
# DISABLED: scoring moved to the downstream consolidation stage. This tool emits
# the graph structure + notable_hits as DATA and no longer scores the network.
# Preserved (commented) so the downstream agent can lift it later.
# ---------------------------------------------------------------------------
# def score_network(graph: NetworkGraph) -> float:
#     """0-100 score from notable-connection weights (capped per category) + reach."""
#     by_cat: dict[str, float] = defaultdict(float)
#     for hit in graph.notable_hits:
#         by_cat[hit.category] += hit.weight
#     notable_score = sum(min(v, _PER_CATEGORY_CAP) for v in by_cat.values())
#     notable_score = min(notable_score, _NOTABLE_CAP)
#     # Breadth of network (diminishing returns on edge count).
#     reach = min((graph.edge_count ** 0.5) * 4.0, _REACH_CAP)
#     return round(min(notable_score + reach, 100.0), 1)


# ---------------------------------------------------------------------------
# Exports for visualization / interchange
# ---------------------------------------------------------------------------
def to_forcegraph_json(graph: NetworkGraph) -> dict:
    """Shape expected by react-force-graph / sigma.js frontends."""
    return {
        "nodes": [
            {
                "id": n.handle,
                "label": n.label or n.handle,
                "seed": n.is_seed,
                "notable": n.is_notable,
                "category": n.notable_category,
                "val": 1 + n.centrality * 10,
            }
            for n in graph.nodes
        ],
        "links": [
            {"source": e.source, "target": e.target, "type": e.edge_type, "weight": e.weight}
            for e in graph.edges
        ],
    }


def to_gexf(graph: NetworkGraph) -> str:
    """Serialize to GEXF (for Gephi) by rebuilding a networkx graph from the model."""
    g: nx.DiGraph = nx.DiGraph()
    for n in graph.nodes:
        g.add_node(n.handle, label=n.label, notable=n.is_notable, seed=n.is_seed)
    for e in graph.edges:
        g.add_edge(e.source, e.target, weight=e.weight, edge_type=e.edge_type)
    body = "\n".join(nx.generate_gexf(g))
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body
