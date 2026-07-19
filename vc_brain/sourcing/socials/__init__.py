"""Socials tool: multi-provider Twitter/LinkedIn processing.

Discovers a founder's posts + comments + network across swappable providers,
builds a connection graph (structure + notable tags), and resolves who engages
with them. It ACCUMULATES data only — scoring/consolidation happens in the
downstream stage. Runs keyless at $0 on the Mock provider by default.
"""

from __future__ import annotations

from vc_brain.sourcing.socials.graph import build_network_graph
from vc_brain.sourcing.socials.identity import get_identity_checker
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

# NOTE: scoring (score_network / score_prominence / aggregate_identity_score) is
# disabled — this tool only accumulates data. Those functions live, commented, in
# graph.py / identity.py for the downstream consolidation stage to reuse.
__all__ = [
    "SocialsScanner",
    "get_provider",
    "get_graph_provider",
    "get_identity_checker",
    "build_network_graph",
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
