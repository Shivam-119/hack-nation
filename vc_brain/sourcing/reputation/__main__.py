"""CLI for the reputation scanner.

    python -m vc_brain.sourcing.reputation "Ada Whitfield"
    python -m vc_brain.sourcing.reputation "Marcus Vale" --hint "Northwind Logistics"
    python -m vc_brain.sourcing.reputation "Ada Whitfield" --provider mock --json
    python -m vc_brain.sourcing.reputation "Ada Whitfield" --min-relevance 6
"""

from __future__ import annotations

import argparse
import asyncio
import json

from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.store import MemoryStore
from vc_brain.sourcing.reputation.models import EntityType, ReputationReport
from vc_brain.sourcing.reputation.providers import get_provider
from vc_brain.sourcing.reputation.scanner import ReputationScanner

_RULE = "=" * 78
_THIN = "-" * 78


def render(report: ReputationReport) -> str:
    lines = [_RULE, f"REPUTATION FINDINGS  --  {report.name}  [{report.entity.value}]"]
    if report.hint:
        lines.append(f"disambiguation hint: {report.hint}")
    lines += [
        _RULE,
        f"provider: {report.provider}    "
        f"articles: {report.articles_reviewed} ({report.articles_extracted} read in full)    "
        f"findings: {len(report.findings)}",
    ]
    if report.by_polarity:
        summary = "  ".join(f"{k}={v}" for k, v in report.by_polarity.items())
        lines.append(f"polarity: {summary}")

    # Findings arrive grouped by category already (aggregate.sort_findings).
    current_category = None
    for finding in report.findings:
        if finding.category.value != current_category:
            current_category = finding.category.value
            count = report.by_category.get(current_category, 0)
            lines += ["", f"{current_category.upper()}  ({count})", _THIN]

        lines.append(
            f"  [{finding.polarity.value}] relevance {finding.relevance}/10  "
            f"confidence {finding.confidence:.2f}  "
            f"{finding.source_count} source(s)"
            + (f"  |  {finding.entity}" if finding.entity else "")
        )
        lines.append(f"    {finding.summary}")
        for source in finding.sources:
            lines.append(
                f"      - {source.source or 'unknown'} (rel {source.relevance}/10)"
                + (f"  {source.published}" if source.published else "")
            )
            lines.append(f"        {source.url}")

    if report.gaps:
        lines += ["", "GAPS  (what this sweep could NOT establish)", _THIN]
        lines += [f"  - {gap}" for gap in report.gaps]

    lines.append("")
    return "\n".join(lines)


def _filter(report: ReputationReport, min_relevance: int) -> ReputationReport:
    if min_relevance <= 1:
        return report
    kept = [f for f in report.findings if f.relevance >= min_relevance]
    return report.model_copy(update={"findings": kept})


async def _run(args: argparse.Namespace) -> int:
    provider = get_provider(args.provider) if args.provider else None

    pipeline = None
    if args.ingest:
        pipeline = IngestionPipeline(MemoryStore(path=args.store))

    entity = EntityType.COMPANY if args.company else EntityType.PERSON
    scanner = ReputationScanner(pipeline=pipeline, provider=provider)
    report = _filter(
        await scanner.analyze(args.name, hint=args.hint, entity=entity),
        args.min_relevance,
    )

    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(render(report))

    if pipeline is not None:
        founder = scanner.ingest(report)
        if founder is not None:
            print(
                f"ingested -> founder {founder.id} "
                f"({len(founder.data_points)} data points in memory)"
            )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m vc_brain.sourcing.reputation",
        description="Collect categorised, sourced web findings about a person.",
    )
    parser.add_argument("name", help="Person's full name, or a company name with --company")
    parser.add_argument(
        "--company",
        action="store_true",
        help="Research a company/project instead of a person",
    )
    parser.add_argument(
        "--hint",
        default="",
        help="Company, sector, role or location to disambiguate a common name",
    )
    parser.add_argument(
        "--provider",
        choices=["tavily", "mock"],
        help="Override the configured search provider",
    )
    parser.add_argument(
        "--min-relevance",
        type=int,
        default=1,
        help="Drop findings whose best source scores below this relevance (1-10)",
    )
    parser.add_argument("--json", action="store_true", help="Emit raw JSON")
    parser.add_argument(
        "--ingest", action="store_true", help="Write findings into Memory"
    )
    parser.add_argument(
        "--store",
        default="vc_brain_data.json",
        help="Memory store path (used with --ingest)",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
