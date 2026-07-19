"""SocialsScanner — orchestrates providers → graph + post analysis → Memory.

Same shape as the other sourcing scanners (`GitHubScanner`, `HackerNewsScanner`):
constructed with an `IngestionPipeline`, exposes an async `analyze(...)` that
returns a `SocialsResult`, and `ingest(...)` that writes source-tagged, cited
`DataPoint`s into Memory.

Data sourcing (per current design):
- posts + comments → the selected live provider (or Mock),
- connection graph edges → ALWAYS Mock for now (real "approved people" later),
- identity of the founder + real commenters → the identity checker (Mock/Tavily).
"""

from __future__ import annotations

from datetime import datetime

from vc_brain.config import config
from vc_brain.memory.ingestion import IngestionPipeline
from vc_brain.memory.models import DataPoint, Founder, SourceType
from vc_brain.sourcing.socials.graph import build_network_graph
from vc_brain.sourcing.socials.identity import get_identity_checker
from vc_brain.sourcing.socials.models import (
    Connection,
    IdentityResult,
    SocialComment,
    SocialPost,
    SocialProfile,
    SocialsResult,
)
from vc_brain.sourcing.socials.post_analyzer import analyze_posts
from vc_brain.sourcing.socials.providers import get_graph_provider, get_provider

_SOURCE_BY_NETWORK = {"twitter": SourceType.TWITTER, "linkedin": SourceType.LINKEDIN}


class SocialsScanner:
    def __init__(self, pipeline: IngestionPipeline):
        self.pipeline = pipeline

    async def analyze(self, handles: dict[str, str], name: str = "") -> SocialsResult:
        """Pull posts + comments + (mock) network, build a graph, analyze posts, ID engagers."""
        profiles: dict[str, SocialProfile] = {}
        all_posts: list[SocialPost] = []
        all_comments: list[SocialComment] = []
        all_connections: list[Connection] = []
        sources: list[str] = []

        for network, handle in handles.items():
            if not handle:
                continue
            provider = get_provider(network)  # type: ignore[arg-type]
            graph_provider = get_graph_provider(network)  # type: ignore[arg-type]  (mock)
            profile = await provider.get_profile(handle)
            posts = await provider.get_posts(handle, config.socials_post_limit)
            comments = await provider.get_comments(posts, config.socials_comment_limit)
            conns = await graph_provider.get_connections(handle, config.socials_follower_sample)
            if profile:
                profiles[network] = profile
                if profile.url:
                    sources.append(profile.url)
            all_posts.extend(posts)
            all_comments.extend(comments)
            all_connections.extend(conns)
            sources.append(f"{network}:{type(provider).__name__}")

        # Graph is seeded on the network that provides edges (Twitter if present).
        seed_network = "twitter" if "twitter" in handles else next(iter(handles), "twitter")
        seed_handle = handles.get(seed_network, "")
        graph = build_network_graph(
            seed_handle,
            seed_network,  # type: ignore[arg-type]
            all_connections,
            [p for p in all_posts if p.network == seed_network],
        )

        seed_profile = profiles.get(seed_network) or (
            next(iter(profiles.values())) if profiles else None
        )
        analysis = await analyze_posts(all_posts, seed_profile)

        founder_name = name or (seed_profile.name if seed_profile else seed_handle)
        founder_identity, engagers = await self._run_identity(
            founder_name, seed_handle, all_comments
        )

        # No scoring here — this tool only accumulates data for the downstream stage.
        return SocialsResult(
            name=founder_name,
            handles=handles,
            profiles=profiles,
            posts=all_posts,
            comments=all_comments,
            post_analysis=analysis,
            graph=graph,
            founder_identity=founder_identity,
            engager_identities=engagers,
            sources=sources,
        )

    async def _run_identity(
        self, founder_name: str, seed_handle: str, comments: list[SocialComment]
    ) -> tuple[IdentityResult | None, list[IdentityResult]]:
        """Identify the founder + the unique real commenters (capped)."""
        checker = get_identity_checker()
        founder_identity = await checker.identify(
            founder_name, seed_handle, context="startup founder"
        )
        seen: set[str] = set()
        uniques: list[SocialComment] = []
        for c in comments:
            key = c.author_handle or c.author_name.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            uniques.append(c)
        engagers: list[IdentityResult] = []
        for c in uniques[: config.socials_max_identity_checks]:
            engagers.append(
                await checker.identify(c.author_name or c.author_handle, c.author_handle)
            )
        return founder_identity, engagers

    def ingest(self, result: SocialsResult) -> Founder:
        """Write source-tagged DataPoints into Memory; enrich an existing founder if found."""
        data_points = self._build_data_points(result)

        existing = self._find_existing(result)
        if existing:
            existing.data_points.extend(data_points)
            if result.name:
                existing.name = result.name
            for net, prof in result.profiles.items():
                if net == "twitter" and prof.url:
                    existing.twitter_url = prof.url
                if net == "linkedin" and prof.url:
                    existing.linkedin_url = prof.url
            if not existing.bio and result.profiles:
                existing.bio = next(iter(result.profiles.values())).bio
            existing.updated_at = datetime.utcnow()
            return self.pipeline.store.upsert_founder(existing)

        tw = result.profiles.get("twitter")
        li = result.profiles.get("linkedin")
        founder = Founder(
            name=result.name or "Unknown",
            twitter_url=tw.url if tw else "",
            linkedin_url=li.url if li else "",
            bio=(tw.bio if tw else "") or (li.bio if li else ""),
            data_points=data_points,
        )
        return self.pipeline.store.upsert_founder(founder)

    # -- internals ----------------------------------------------------------
    def _build_data_points(self, result: SocialsResult) -> list[DataPoint]:
        points: list[DataPoint] = []
        for network, profile in result.profiles.items():
            content = {
                "type": "social_profile",
                "network": network,
                "handle": profile.handle,
                "name": profile.name,
                "bio": profile.bio,
                "followers": profile.followers,
                "posts_fetched": sum(1 for p in result.posts if p.network == network),
            }
            content["comments_fetched"] = sum(1 for c in result.comments if c.network == network)
            if network == "twitter":  # the network that carries the (mock) graph structure
                content["notable_connections"] = [h.model_dump() for h in result.graph.notable_hits]
                content["graph_metrics"] = {
                    "nodes": result.graph.node_count,
                    "edges": result.graph.edge_count,
                    "density": result.graph.density,
                }
            points.append(
                DataPoint(
                    source=_SOURCE_BY_NETWORK.get(network, SourceType.MANUAL),
                    source_url=profile.url,
                    content=content,
                )
            )

        # Post analysis as its own citable data point.
        seed_url = ""
        if result.profiles:
            seed_url = next(iter(result.profiles.values())).url
        points.append(
            DataPoint(
                source=SourceType.TWITTER if "twitter" in result.profiles else SourceType.LINKEDIN,
                source_url=seed_url,
                content={"type": "post_analysis", **result.post_analysis.model_dump()},
            )
        )

        # Identity data — founder + notable engagers (who they are), no scores.
        notable_engagers = [e.model_dump() for e in result.engager_identities if e.is_notable]
        points.append(
            DataPoint(
                source=SourceType.TWITTER if "twitter" in result.profiles else SourceType.LINKEDIN,
                source_url=seed_url,
                content={
                    "type": "identity_network",
                    "founder_identity": result.founder_identity.model_dump()
                    if result.founder_identity
                    else None,
                    "notable_engagers": notable_engagers,
                    "engagers_checked": len(result.engager_identities),
                },
            )
        )
        return points

    def _find_existing(self, result: SocialsResult) -> Founder | None:
        """Look up an existing founder by social URL (store dedups only on email/github_url)."""
        for network in ("twitter", "linkedin"):
            profile = result.profiles.get(network)
            if not profile or not profile.url:
                continue
            field = "twitter_url" if network == "twitter" else "linkedin_url"
            matches = self.pipeline.store.search_founders(**{field: profile.url})
            if matches:
                return matches[0]
        return None
