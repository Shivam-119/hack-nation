"""Shared test setup.

`vc_brain.config` loads a local `.env`, which is what we want in normal use but
is actively harmful in tests: any test that reads config would silently pick up
real credentials and start calling Tavily, Apify and OpenAI for money. That is
how a 0.2s offline suite turned into a 145s one that also failed.

So every test runs with credentials blanked and providers pinned to their mock
implementations -- unless it is explicitly marked `live`, which is the opt-in
for tests that are *supposed* to hit real APIs (see tests/test_tavily_live.py).
"""

import pytest

from vc_brain.config import config

# Anything that could authenticate against a paid API.
_CREDENTIAL_FIELDS = (
    "tavily_api_key",
    "apify_token",
    "twitterapi_io_key",
    "openai_api_key",
    "anthropic_api_key",
    "github_token",
    "crunchbase_api_key",
    "producthunt_token",
)

# Provider selectors, forced to their offline implementations.
_MOCK_PROVIDERS = {
    "reputation_provider": "mock",
    "socials_twitter_provider": "mock",
    "socials_linkedin_provider": "mock",
    "socials_identity_provider": "mock",
}


@pytest.fixture(autouse=True)
def isolate_from_real_credentials(request, monkeypatch):
    """Keep offline tests offline, whatever happens to be in .env."""
    if request.node.get_closest_marker("live"):
        return  # live tests need the real keys, by design

    for field in _CREDENTIAL_FIELDS:
        monkeypatch.setattr(config, field, "", raising=False)
    for field, value in _MOCK_PROVIDERS.items():
        monkeypatch.setattr(config, field, value, raising=False)
