"""Provider factory — selects a swappable backend per network.

Default is Mock ($0, keyless). A live provider is used only when it is BOTH
selected in config AND its credential is present; otherwise we fall back to Mock
so the tool always runs and never spends unexpectedly. Live providers are
imported lazily so their optional deps/keys are only touched when chosen.
"""

from __future__ import annotations

from vc_brain.config import config
from vc_brain.sourcing.socials.models import Network
from vc_brain.sourcing.socials.providers.base import SocialProvider
from vc_brain.sourcing.socials.providers.mock import MockProvider


def get_provider(network: Network) -> SocialProvider:
    if network == "twitter":
        choice = config.socials_twitter_provider
        if choice == "apify" and config.apify_token:
            from vc_brain.sourcing.socials.providers.twitter_apify import ApifyTwitterProvider

            return ApifyTwitterProvider()
        if choice == "twitterapi_io" and config.twitterapi_io_key:
            from vc_brain.sourcing.socials.providers.twitter_apiio import TwitterApiIoProvider

            return TwitterApiIoProvider()
        return MockProvider("twitter")

    if network == "linkedin":
        choice = config.socials_linkedin_provider
        if choice == "apify" and config.apify_token:
            from vc_brain.sourcing.socials.providers.linkedin_apify import LinkedInApifyProvider

            return LinkedInApifyProvider()
        return MockProvider("linkedin")

    return MockProvider(network)


def get_graph_provider(network: Network) -> SocialProvider:
    """Provider for CONNECTION EDGES — always Mock for now.

    The connection graph is intentionally mocked until we have a real
    "approved people" list to source edges from. Posts and comments still use
    the live provider from `get_provider`; only who-connects-to-whom is mocked.
    """
    return MockProvider(network)


__all__ = ["get_provider", "get_graph_provider", "SocialProvider", "MockProvider"]
