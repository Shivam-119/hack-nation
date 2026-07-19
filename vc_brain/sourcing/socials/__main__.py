"""CLI for the socials tool — for e2e checks and demos.

Examples:
    python -m vc_brain.sourcing.socials janedoe
    python -m vc_brain.sourcing.socials janedoe --linkedin janedoe --name "Jane Doe"
    python -m vc_brain.sourcing.socials janedoe --json
    python -m vc_brain.sourcing.socials janedoe --ingest

Runs on the Mock provider ($0) unless SOCIALS_*_PROVIDER + a token are configured.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.store import MemoryStore
from vc_brain.sourcing.socials.graph import to_forcegraph_json
from vc_brain.sourcing.socials.models import SocialsResult
from vc_brain.sourcing.socials.scanner import SocialsScanner

_TEMPLATE = Path(__file__).resolve().parents[3] / "frontend" / "socials_graph.html"


async def _run(args: argparse.Namespace) -> None:
    handles: dict[str, str] = {}
    if args.twitter:
        handles["twitter"] = args.twitter
    if args.linkedin:
        handles["linkedin"] = args.linkedin
    if not handles:
        print("Provide a twitter handle (positional) and/or --linkedin <slug>.")
        return

    scanner = SocialsScanner(IngestionPipeline(MemoryStore(path=args.store)))
    result = await scanner.analyze(handles, name=args.name)

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        _print_summary(result)

    if args.html:
        _write_html(result, args.html)
        print(f"\n✓ wrote interactive graph → {args.html}")

    if args.ingest:
        founder = scanner.ingest(result)
        print(f"\n✓ ingested founder id={founder.id} "
              f"(data_points={len(founder.data_points)}) → {args.store}")


def _write_html(r: SocialsResult, out: str) -> None:
    """Render the connection graph into a self-contained interactive HTML page."""
    meta = {
        "name": r.name,
        "network_score": r.network_score,
        "notable_count": len(r.graph.notable_hits),
    }
    html = (
        _TEMPLATE.read_text()
        .replace("__GRAPH_DATA__", json.dumps(to_forcegraph_json(r.graph)))
        .replace("__META__", json.dumps(meta))
    )
    Path(out).write_text(html)


def _print_summary(r: SocialsResult) -> None:
    print(f"\n=== Socials report: {r.name or '(unknown)'} ===")
    print(f"handles: {r.handles}")
    for net, p in r.profiles.items():
        print(f"  [{net}] {p.name} — {p.followers} followers — {p.url}")
    print(f"\nposts analyzed: {len(r.posts)}   comments scraped: {len(r.comments)}")
    print(f"network_score: {r.network_score}/100   (mock graph)   "
          f"identity_score: {r.identity_score}/100   (confidence {r.confidence})")
    g = r.graph
    print(f"graph [MOCK]: {g.node_count} nodes / {g.edge_count} edges (density {g.density})")
    if g.notable_hits:
        print("notable connections (mock roster):")
        for h in g.notable_hits:
            print(f"  - {h.name or h.handle} [{h.category}, w={h.weight}] — {h.reason}")

    if r.founder_identity:
        fi = r.founder_identity
        print(f"\nfounder identity [{fi.source}]: {fi.resolved_name} — "
              f"prominence {fi.prominence_score}/100 — {fi.description}")
    notable_engagers = [e for e in r.engager_identities if e.is_notable]
    if r.engager_identities:
        print(f"engagers identity-checked: {len(r.engager_identities)} "
              f"({len(notable_engagers)} notable)")
        for e in notable_engagers:
            print(f"  ★ {e.resolved_name} (@{e.handle}) — {', '.join(e.roles) or '—'} "
                  f"— prominence {e.prominence_score}/100")
    a = r.post_analysis
    print("\npost analysis:")
    print(f"  sentiment: {a.sentiment}   tone: {a.tone}")
    print(f"  topics: {', '.join(a.topics) or '—'}")
    print(f"  expertise: {', '.join(a.expertise_areas) or '—'}")
    print(f"  credibility: {', '.join(a.credibility_signals) or '—'}")
    print(f"  red flags: {', '.join(a.red_flags) or '—'}")
    print(f"  summary: {a.summary}")
    fg = to_forcegraph_json(g)
    print(f"\nforce-graph json: {len(fg['nodes'])} nodes / {len(fg['links'])} links "
          f"(use to_gexf() for Gephi).")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m vc_brain.sourcing.socials")
    parser.add_argument("twitter", nargs="?", help="twitter/X handle (positional)")
    parser.add_argument("--linkedin", default="", help="linkedin public slug (…/in/<slug>)")
    parser.add_argument("--name", default="", help="founder display name")
    parser.add_argument("--json", action="store_true", help="print full SocialsResult JSON")
    parser.add_argument("--ingest", action="store_true", help="write DataPoints into Memory")
    parser.add_argument("--html", default="", help="write an interactive graph HTML to this path")
    parser.add_argument("--store", default="vc_brain_data.json", help="Memory JSON store path")
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
