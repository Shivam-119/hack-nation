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

# Community sites carry complaints and first-hand experience long before any
# outlet covers them. Restricting by domain is far more reliable than a
# "site:" operator, which Tavily's semantic search does not honour.
REDDIT_DOMAINS = ("reddit.com",)


@dataclass(frozen=True)
class Query:
    text: str
    intent: str
    include_domains: tuple[str, ...] = field(default=())


# (intent, template, include_domains)
_Angle = tuple[str, str, tuple[str, ...]]

# Ordered by value: the cap in config trims from the end, so keep the
# highest-signal angles first. Both polarities appear early, so a tight cap
# still produces a balanced sweep.
PERSON_ANGLES: list[_Angle] = [
    (NEGATIVE, '"{name}" fraud OR scam OR misconduct', ()),
    (POSITIVE, '"{name}" founder OR co-founder OR CEO', ()),
    (NEGATIVE, '"{name}" lawsuit OR sued OR court OR settlement', ()),
    (POSITIVE, '"{name}" award OR prize OR olympiad OR medalist OR winner', ()),
    (NEGATIVE, '"{name}" investigation OR allegations OR probe OR SEC', ()),
    (FORUM, '"{name}" reputation OR experience OR opinion', REDDIT_DOMAINS),
    (POSITIVE, '"{name}" research OR paper OR publication OR patent', ()),
    (NEGATIVE, '"{name}" controversy OR resigned OR fired OR ousted', ()),
    (POSITIVE, '"{name}" raised OR funding OR investment round', ()),
    (NEGATIVE, '"{name}" bankruptcy OR insolvency OR shut down OR failed', ()),
    (POSITIVE, '"{name}" interview OR profile OR featured', ()),
    (BACKGROUND, '"{name}" biography OR background OR career history', ()),
    (POSITIVE, '"{name}" "30 under 30" OR award list OR recognition', ()),
    (BACKGROUND, '"{name}" former OR previously OR prior company', ()),
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
