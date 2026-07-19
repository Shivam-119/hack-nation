"""Socials tool: multi-provider Twitter/LinkedIn processing.

Discovers a founder's posts + network across swappable providers, builds a
connection graph (deterministic notable-node scoring), and analyzes their posts
for investment signal. Runs keyless at $0 on the Mock provider by default.
"""

from __future__ import annotations

from vc_brain.sourcing.socials.graph import build_network_graph, score_network
from vc_brain.sourcing.socials.identity import (
    aggregate_identity_score,
    get_identity_checker,
    score_prominence,
)
from vc_brain.sourcing.socials.models import (
    Connection,
    IdentityResult,
    NetworkGraph,
    NotableHit,
    PostAnalysis,
    SocialComment,
    SocialPost,
    SocialProfile,
    SocialsResult,
)
from vc_brain.sourcing.socials.providers import get_graph_provider, get_provider
from vc_brain.sourcing.socials.scanner import SocialsScanner

__all__ = [
    "SocialsScanner",
    "get_provider",
    "get_graph_provider",
    "get_identity_checker",
    "aggregate_identity_score",
    "score_prominence",
    "build_network_graph",
    "score_network",
    "Connection",
    "IdentityResult",
    "NetworkGraph",
    "NotableHit",
    "PostAnalysis",
    "SocialComment",
    "SocialPost",
    "SocialProfile",
    "SocialsResult",
]
