"""Query angles for the reputation sweep.

Searching a name on its own returns whatever the subject optimised for. To get
a balanced picture we ask for the good and the bad explicitly, from several
angles, and record which angle produced each article -- so a silent angle
("no litigation found") becomes a reportable gap rather than an invisible one.

Two angle sets live here, one per entity type. They are the only thing that
differs between researching a person and researching a company; everything
downstream is shared.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vc_brain.sourcing.reputation.models import EntityType

POSITIVE = "positive"
NEGATIVE = "negative"
BACKGROUND = "background"
FORUM = "forum"
# Verifiable credentials -- degrees, olympiads, patents, fellowships. Kept
# distinct from BACKGROUND so "we looked for education and found nothing"
# becomes a reportable gap rather than an invisible one.
CREDENTIAL = "credential"

# Community sites carry complaints and first-hand experience long before any
# outlet covers them. Restricting by domain is far more reliable than a
# "site:" operator, which Tavily's semantic search does not honour.
REDDIT_DOMAINS = ("reddit.com",)
# The single best source of a founder's career history and education. Scoped
# by domain for the same reason as Reddit.
LINKEDIN_DOMAINS = ("linkedin.com",)


@dataclass(frozen=True)
class Query:
    text: str
    intent: str
    include_domains: tuple[str, ...] = field(default=())


# (intent, template, include_domains)
_Angle = tuple[str, str, tuple[str, ...]]

# Ordered by value: the cap in config trims from the end, so keep the
# highest-signal angles first.
#
# At pre-seed the founder IS the investment, so this sweep leads with who they
# are -- role, career history, education, prior companies, prizes -- before it
# asks what went wrong. The adverse angles are NOT demoted to the tail though:
# fraud, lawsuits and forced exits are founder diligence, not company gossip,
# and they stay in the top half so even a trimmed sweep stays balanced.
PERSON_ANGLES: list[_Angle] = [
    (POSITIVE, '"{name}" founder OR co-founder OR CEO', ()),
    (CREDENTIAL, '"{name}" experience OR education OR career', LINKEDIN_DOMAINS),
    (CREDENTIAL, '"{name}" university OR PhD OR MSc OR graduated OR "alma mater" OR degree', ()),
    (NEGATIVE, '"{name}" fraud OR scam OR misconduct', ()),
    (BACKGROUND, '"{name}" former OR previously OR prior company', ()),
    (POSITIVE, '"{name}" award OR prize OR medalist OR winner', ()),
    (CREDENTIAL, '"{name}" olympiad OR IMO OR IOI OR ICPC OR Putnam OR "gold medal"', ()),
    (NEGATIVE, '"{name}" lawsuit OR sued OR court OR settlement', ()),
    (BACKGROUND, '"{name}" "worked at" OR "ex-" OR engineer OR "head of"', ()),
    (FORUM, '"{name}" reputation OR experience OR opinion', REDDIT_DOMAINS),
    (POSITIVE, '"{name}" research OR paper OR publication', ()),
    (NEGATIVE, '"{name}" controversy OR resigned OR fired OR ousted', ()),
    (CREDENTIAL, '"{name}" patent OR inventor OR USPTO', ()),
    (POSITIVE, '"{name}" "30 under 30" OR award list OR recognition', ()),
    (CREDENTIAL, '"{name}" thesis OR dissertation OR professor OR lab', ()),
    (NEGATIVE, '"{name}" investigation OR allegations OR probe OR SEC', ()),
    (POSITIVE, '"{name}" interview OR profile OR featured', ()),
    (CREDENTIAL, '"{name}" scholarship OR fellowship OR hackathon OR "science fair"', ()),
    (BACKGROUND, '"{name}" biography OR background OR career history', ()),
    (POSITIVE, '"{name}" acquired OR exit OR "sold company" OR IPO', ()),
    (NEGATIVE, '"{name}" bankruptcy OR insolvency OR shut down OR failed', ()),
    (POSITIVE, '"{name}" keynote OR speaker OR conference OR podcast', ()),
    (BACKGROUND, '"{name}" blog OR "personal website" OR portfolio OR "about me"', ()),
    (POSITIVE, '"{name}" raised OR funding OR investment round', ()),
    (NEGATIVE, '"{name}" complaint OR accused OR criticism', ()),
]

# Scoped to pre-seed / seed. Deliberately no layoffs, M&A, market-share or
# partnership angles: a company at this stage has none of those, and asking
# would burn queries to return noise about a larger namesake.
COMPANY_ANGLES: list[_Angle] = [
    (NEGATIVE, '"{name}" scam OR fraud OR complaint OR lawsuit', ()),
    (POSITIVE, '"{name}" raised OR pre-seed OR seed round OR investors OR backed', ()),
    (FORUM, '"{name}" review OR experience OR legit OR scam', REDDIT_DOMAINS),
    (BACKGROUND, '"{name}" founders OR founded by OR team behind', ()),
    (POSITIVE, '"{name}" launch OR "Show HN" OR "Product Hunt" OR beta', ()),
    (POSITIVE, '"{name}" "Y Combinator" OR Techstars OR accelerator OR incubator', ()),
    (BACKGROUND, '"{name}" startup OR what it does OR company profile', ()),
    (NEGATIVE, '"{name}" shut down OR failed OR dead OR discontinued', ()),
    (NEGATIVE, '"{name}" controversy OR criticism OR concerns OR accused', ()),
    (POSITIVE, '"{name}" interview OR featured OR profile OR press', ()),
    (POSITIVE, '"{name}" open source OR github OR technical OR demo', ()),
    (POSITIVE, '"{name}" award OR hackathon OR "demo day" OR winner', ()),
    (POSITIVE, '"{name}" paper OR patent OR research', ()),
    (BACKGROUND, '"{name}" waitlist OR early access OR launched', ()),
    (NEGATIVE, '"{name}" refund OR support OR broken OR "does not work"', ()),
]

ANGLES_BY_ENTITY: dict[EntityType, list[_Angle]] = {
    EntityType.PERSON: PERSON_ANGLES,
    EntityType.COMPANY: COMPANY_ANGLES,
}


def build_queries(
    name: str,
    hint: str = "",
    max_queries: int = 12,
    entity: EntityType = EntityType.PERSON,
) -> list[Query]:
    """Build the query sweep for a person or a company.

    `hint` (a company, role, sector or location) is appended to every query.
    For a background check, disambiguation beats recall: a finding about the
    wrong subject is far more damaging than a finding we merely missed.
    """
    name = (name or "").strip()
    if not name:
        return []

    hint = (hint or "").strip()
    angles = ANGLES_BY_ENTITY.get(entity, PERSON_ANGLES)

    queries: list[Query] = []
    for intent, template, domains in angles[: max(0, max_queries)]:
        text = template.format(name=name)
        if hint:
            text = f"{text} {hint}"
        queries.append(Query(text=text, intent=intent, include_domains=domains))
    return queries


def intents_covered(queries: list[Query]) -> set[str]:
    """Which intents the sweep actually asked about (used to report gaps)."""
    return {q.intent for q in queries}
