"""Central configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    # Load a local .env so keys work without exporting them by hand.
    # Real environment variables always win over the file.
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:  # pragma: no cover - dotenv is optional
    pass


@dataclass
class Config:
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_api_key: str = ""
    github_token: str = ""
    crunchbase_api_key: str = ""
    producthunt_token: str = ""
    database_url: str = "sqlite+aiosqlite:///./vc_brain.db"

    # -- Socials tool (Twitter/LinkedIn processing) -------------------------
    # Data-access is opt-in and cost-capped. Providers default to "mock" so the
    # tool always runs at $0; live providers activate only when selected AND
    # their token is present. Apify covers both networks under its free monthly
    # credit; TwitterAPI.io is an optional pay-as-you-go swap for real-time X.
    apify_token: str = ""
    # Verified free-tier friendly (2026). apidojo/* block free accounts (return
    # {"noResults":true}); kaitoeasyapi cheapest tweet actor works on the $5
    # credit and returns likes/retweets/replies/views. Replies come from the SAME
    # actor via a `conversation_id:` search, so no separate (paid) reply actor.
    apify_twitter_actor: str = "kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest"
    apify_twitter_followers_actor: str = "kaitoeasyapi/premium-x-follower-scraper-following-data"
    apify_linkedin_actor: str = "apimaestro/linkedin-profile-posts"
    twitterapi_io_key: str = ""
    socials_twitter_provider: str = "mock"  # mock | apify | twitterapi_io
    socials_linkedin_provider: str = "mock"  # mock | apify
    socials_post_limit: int = 30  # cost cap: max posts fetched per handle
    socials_follower_sample: int = 200  # cost cap: max follower/following edges sampled
    # Comment/reply scraping (real). Twitter replies reuse apify_twitter_actor
    # via a conversation_id search (free tier); LinkedIn comments use apimaestro's
    # no-cookies comment scraper (verified free-tier).
    apify_linkedin_comments_actor: str = (
        "apimaestro/linkedin-post-comments-replies-engagements-scraper-no-cookies"
    )
    socials_comment_limit: int = 20  # cost cap: comments fetched per post
    # Identity check: resolve WHO a name is + a deterministic prominence score.
    # "mock" (default, $0) or "tavily" (reuses tavily_api_key from reputation).
    socials_identity_provider: str = "mock"  # mock | tavily
    socials_max_identity_checks: int = 8  # cost cap: people identity-checked per run

    # -- Reputation scanner (web-article background check) -------------------
    # Tavily is the default search backend; it falls back to the bundled
    # fixtures automatically when no key is set, so tests and demos still run
    # offline. Limits below bound a single sweep, not the budget.
    tavily_api_key: str = ""
    reputation_provider: str = "tavily"  # tavily | mock
    reputation_results_per_query: int = 10  # results per angle (Tavily caps at 20)
    reputation_max_queries: int = 15  # query angles per subject (full sweep)
    # Full-page extraction (Tavily /extract): recovers claims that a thin
    # search snippet cannot ground. Selection is capped because each page
    # costs credits and latency.
    reputation_extract: bool = True
    reputation_extract_limit: int = 16  # max pages fetched in full per subject
    reputation_extract_depth: str = "basic"  # basic | advanced
    reputation_extract_chars: int = 4000  # per-article cap fed to the LLM

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            crunchbase_api_key=os.getenv("CRUNCHBASE_API_KEY", ""),
            producthunt_token=os.getenv("PRODUCTHUNT_TOKEN", ""),
            database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./vc_brain.db"),
            apify_token=os.getenv("APIFY_TOKEN", ""),
            apify_twitter_actor=os.getenv(
                "APIFY_TWITTER_ACTOR",
                "kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest",
            ),
            apify_twitter_followers_actor=os.getenv(
                "APIFY_TWITTER_FOLLOWERS_ACTOR",
                "kaitoeasyapi/premium-x-follower-scraper-following-data",
            ),
            apify_linkedin_actor=os.getenv("APIFY_LINKEDIN_ACTOR", "apimaestro/linkedin-profile-posts"),
            twitterapi_io_key=os.getenv("TWITTERAPI_IO_KEY", ""),
            socials_twitter_provider=os.getenv("SOCIALS_TWITTER_PROVIDER", "mock"),
            socials_linkedin_provider=os.getenv("SOCIALS_LINKEDIN_PROVIDER", "mock"),
            socials_post_limit=int(os.getenv("SOCIALS_POST_LIMIT", "30")),
            socials_follower_sample=int(os.getenv("SOCIALS_FOLLOWER_SAMPLE", "200")),
            apify_linkedin_comments_actor=os.getenv(
                "APIFY_LINKEDIN_COMMENTS_ACTOR",
                "apimaestro/linkedin-post-comments-replies-engagements-scraper-no-cookies",
            ),
            socials_comment_limit=int(os.getenv("SOCIALS_COMMENT_LIMIT", "20")),
            socials_identity_provider=os.getenv("SOCIALS_IDENTITY_PROVIDER", "mock"),
            socials_max_identity_checks=int(os.getenv("SOCIALS_MAX_IDENTITY_CHECKS", "8")),
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
            reputation_provider=os.getenv("REPUTATION_PROVIDER", "tavily"),
            reputation_results_per_query=int(os.getenv("REPUTATION_RESULTS_PER_QUERY", "6")),
            reputation_max_queries=int(os.getenv("REPUTATION_MAX_QUERIES", "14")),
            reputation_extract=os.getenv("REPUTATION_EXTRACT", "true").lower()
            not in ("0", "false", "no"),
            reputation_extract_limit=int(os.getenv("REPUTATION_EXTRACT_LIMIT", "12")),
            reputation_extract_depth=os.getenv("REPUTATION_EXTRACT_DEPTH", "basic"),
            reputation_extract_chars=int(os.getenv("REPUTATION_EXTRACT_CHARS", "4000")),
        )


config = Config.from_env()
