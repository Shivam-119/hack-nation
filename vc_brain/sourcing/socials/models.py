"""Pydantic models for the socials tool.

Everything a provider returns, the graph builder produces, and the post
analyzer emits is typed here so downstream logic never touches raw dicts
(per project standards). Kept provider-neutral: Twitter and LinkedIn map onto
the same shapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Network = Literal["twitter", "linkedin"]
EdgeType = Literal["follows", "followed_by", "mentions", "replies", "co_affiliation"]


class SocialProfile(BaseModel):
    network: Network
    handle: str
    name: str = ""
    bio: str = ""
    url: str = ""
    followers: int = 0
    following: int = 0
    verified: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class SocialPost(BaseModel):
    network: Network
    author_handle: str
    text: str = ""
    created_at: str = ""  # ISO string kept as-is; providers vary in format
    url: str = ""
    likes: int = 0
    reposts: int = 0
    replies: int = 0
    is_repost: bool = False
    mentions: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class SocialComment(BaseModel):
    """A reply/comment left on one of the founder's posts (real, scraped)."""

    network: Network
    post_url: str = ""
    author_handle: str = ""
    author_name: str = ""
    text: str = ""
    likes: int = 0
    created_at: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class Connection(BaseModel):
    """A directed edge discovered from a network (source_handle -> target_handle)."""

    network: Network
    source_handle: str
    target_handle: str
    edge_type: EdgeType = "follows"
    weight: float = 1.0
    source_url: str = ""  # where this edge was observed (traceability)


# ---------------------------------------------------------------------------
# Post analysis (LLM output — validated)
# ---------------------------------------------------------------------------
class Evidence(BaseModel):
    claim: str
    url: str = ""


class PostAnalysis(BaseModel):
    topics: list[str] = Field(default_factory=list)
    expertise_areas: list[str] = Field(default_factory=list)
    sentiment: str = "neutral"  # positive | neutral | negative | mixed
    tone: str = ""
    credibility_signals: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    summary: str = ""
    confidence: float = 0.5  # 0-1; never 1.0 — no claim is fully verified
    evidence: list[Evidence] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Identity check ("who is this person?" + deterministic prominence)
# ---------------------------------------------------------------------------
class IdentityResult(BaseModel):
    query_name: str
    handle: str = ""
    resolved_name: str = ""
    description: str = ""  # one-line "who they are"
    roles: list[str] = Field(default_factory=list)  # Founder, Investor, Engineer, ...
    affiliations: list[str] = Field(default_factory=list)  # orgs/companies
    is_notable: bool = False
    prominence_score: float = 0.0  # 0-100, deterministic
    confidence: float = 0.5
    evidence: list[Evidence] = Field(default_factory=list)
    source: str = "mock"  # which checker produced it


# ---------------------------------------------------------------------------
# Connection graph
# ---------------------------------------------------------------------------
class GraphNode(BaseModel):
    handle: str
    network: Network
    label: str = ""
    is_seed: bool = False
    is_notable: bool = False
    notable_category: str = ""
    centrality: float = 0.0


class GraphEdge(BaseModel):
    source: str
    target: str
    edge_type: EdgeType = "follows"
    weight: float = 1.0


class NotableHit(BaseModel):
    """A node in the founder's network that matched the hardcoded notable roster."""

    handle: str
    name: str = ""
    category: str = ""
    weight: float = 0.0
    reason: str = ""
    source_url: str = ""


class NetworkGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    density: float = 0.0
    top_central: list[dict[str, Any]] = Field(default_factory=list)  # [{handle, centrality}]
    notable_hits: list[NotableHit] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level result
# ---------------------------------------------------------------------------
class SocialsResult(BaseModel):
    name: str = ""
    handles: dict[str, str] = Field(default_factory=dict)  # network -> handle
    profiles: dict[str, SocialProfile] = Field(default_factory=dict)  # network -> profile
    posts: list[SocialPost] = Field(default_factory=list)
    comments: list[SocialComment] = Field(default_factory=list)  # real, scraped
    post_analysis: PostAnalysis = Field(default_factory=PostAnalysis)
    graph: NetworkGraph = Field(default_factory=NetworkGraph)  # MOCK edges for now
    network_score: float = 0.0  # 0-100, deterministic (from the mock graph)
    founder_identity: IdentityResult | None = None
    engager_identities: list[IdentityResult] = Field(default_factory=list)
    identity_score: float = 0.0  # 0-100, deterministic (who actually engages)
    confidence: float = 0.5
    sources: list[str] = Field(default_factory=list)
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
