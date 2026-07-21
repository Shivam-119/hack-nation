"""Turn articles into structured, summarised findings using the LLM.

This is the only LLM step in the tool, and it is deliberately narrow: the model
*summarises and labels* what an article says, it never judges the person. There
is no scoring anywhere in this pipeline -- downstream stages decide what the
evidence is worth.

The model cites articles by index rather than by URL, and we resolve that index
against our own list, so a hallucinated link cannot enter the evidence chain.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, TypeVar

from vc_brain.config import config
from vc_brain.llm import complete_json
from vc_brain.sourcing.reputation.models import (
    RELEVANCE_DEFAULT,
    Article,
    EntityType,
    FindingCategory,
    Polarity,
    ReputationFinding,
    SourceRef,
)

_PROMPT_DIR = Path(__file__).resolve().parents[3] / "prompts" / "system"

# The prompt is the only part of extraction that differs by entity type.
PROMPT_PATHS: dict[EntityType, Path] = {
    EntityType.PERSON: _PROMPT_DIR / "reputation_extraction.txt",
    EntityType.COMPANY: _PROMPT_DIR / "company_extraction.txt",
}

DEDUP_PROMPT_PATH = _PROMPT_DIR / "reputation_dedup.txt"

# Small batches keep each prompt focused and bound the blast radius of one
# failed call -- a bad batch loses its own articles, not the whole sweep.
BATCH_SIZE = 8
MAX_CONFIDENCE = 0.95

_FALLBACK_SYSTEM = (
    "Summarise what each article says about the given person. Ground every "
    "summary in the text, cite article_index, never invent URLs, and return "
    'JSON {"findings": [...]}.'
)

E = TypeVar("E")


def _load_system_prompt(entity: EntityType = EntityType.PERSON) -> str:
    path = PROMPT_PATHS.get(entity, PROMPT_PATHS[EntityType.PERSON])
    try:
        return path.read_text().strip()
    except OSError:
        return _FALLBACK_SYSTEM


def _as_enum(value: Any, enum_cls: type[E], default: E) -> E:
    try:
        return enum_cls(str(value).strip().lower())
    except (ValueError, AttributeError):
        return default


def _as_relevance(value: Any) -> int:
    """Clamp the model's relevance tag into 1-10."""
    try:
        return max(1, min(10, int(round(float(value)))))
    except (TypeError, ValueError):
        return RELEVANCE_DEFAULT


def _render_articles(articles: list[Article]) -> str:
    limit = config.reputation_extract_chars
    blocks = []
    for index, article in enumerate(articles):
        # Tell the model whether it is reading a blurb or the real page, so it
        # can calibrate how much a missing detail actually means.
        label = "FULL PAGE TEXT" if article.extracted else "search snippet only"
        blocks.append(
            f"[{index}] {article.title}\n"
            f"    source: {article.source or 'unknown'}\n"
            f"    date: {article.published or 'unknown'}\n"
            f"    {label}: {article.best_text(limit)}"
        )
    return "\n\n".join(blocks)


async def _extract_batch(
    name: str,
    articles: list[Article],
    hint: str,
    system: str,
    entity: EntityType = EntityType.PERSON,
) -> list[ReputationFinding]:
    label = "COMPANY" if entity is EntityType.COMPANY else "PERSON"
    prompt = (
        f"{label}: {name}\n"
        f"HINT: {hint or '(none provided)'}\n\n"
        f"ARTICLES:\n{_render_articles(articles)}\n\n"
        "Summarise the findings as specified."
    )

    try:
        data = await complete_json(prompt, system=system)
    except Exception:
        # Fail soft: this batch yields nothing, the rest of the sweep survives.
        return []

    raw_findings = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(raw_findings, list):
        return []

    findings: list[ReputationFinding] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            continue
        # The person prompt calls this `about_person`, the company one
        # `about_entity`; either being false means a name collision.
        if item.get("about_person") is False or item.get("about_entity") is False:
            continue  # same name, different subject

        try:
            index = int(item.get("article_index", -1))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(articles):
            continue  # cited an article that does not exist -- drop it

        summary = str(item.get("summary", "")).strip()
        if not summary:
            continue

        source = articles[index]
        relevance = _as_relevance(item.get("relevance"))

        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5

        findings.append(
            ReputationFinding(
                summary=summary,
                category=_as_enum(item.get("category"), FindingCategory, FindingCategory.OTHER),
                polarity=_as_enum(item.get("polarity"), Polarity, Polarity.NEUTRAL),
                entity=str(item.get("entity", "") or "").strip(),
                relevance=relevance,
                confidence=min(MAX_CONFIDENCE, max(0.0, confidence)),
                sources=[
                    # Identity fields come from OUR article, never from the model.
                    SourceRef(
                        source=source.source,
                        url=source.url,
                        title=source.title,
                        published=source.published,
                        relevance=relevance,
                    )
                ],
            )
        )

    return findings


async def extract_findings(
    name: str,
    articles: list[Article],
    hint: str = "",
    entity: EntityType = EntityType.PERSON,
) -> list[ReputationFinding]:
    """Summarise what the articles say about the subject. Never raises."""
    if not name or not articles:
        return []

    system = _load_system_prompt(entity)
    batches = [articles[i : i + BATCH_SIZE] for i in range(0, len(articles), BATCH_SIZE)]

    results = await asyncio.gather(
        *(_extract_batch(name, batch, hint, system, entity) for batch in batches),
        return_exceptions=True,
    )

    findings: list[ReputationFinding] = []
    for result in results:
        if isinstance(result, list):
            findings.extend(result)
    return findings


_DEDUP_FALLBACK_SYSTEM = (
    "You group web findings that describe the SAME underlying event or fact "
    "about the subject, even when worded differently or reported by different "
    "outlets. Findings about different events stay in different groups. Return "
    'JSON {"groups": [[index, ...], ...]} listing only groups of two or more; '
    "omit singletons."
)


def _load_dedup_prompt() -> str:
    try:
        return DEDUP_PROMPT_PATH.read_text().strip()
    except OSError:
        return _DEDUP_FALLBACK_SYSTEM


async def cluster_findings(
    name: str, findings: list[ReputationFinding], entity: EntityType = EntityType.PERSON
) -> list[list[int]]:
    """Ask the model which findings describe the same underlying story.

    Returns groups of indices into `findings` that should be merged into one.
    Findings the model does not group stay on their own. Fail-soft: returns []
    on any error (no merging) rather than raising -- deduplication is a
    nice-to-have, never a reason to lose a sweep.

    The decision is the model's; string similarity is deliberately not used,
    because outlets phrase the same event too differently for it to tell "same
    story" from merely "same topic".
    """
    if len(findings) < 2:
        return []

    label = "COMPANY" if entity is EntityType.COMPANY else "PERSON"
    listing = "\n".join(
        f"[{i}] ({f.category.value}) {f.summary}" for i, f in enumerate(findings)
    )
    prompt = (
        f"{label}: {name}\n\n"
        f"FINDINGS:\n{listing}\n\n"
        "Group the indices whose findings describe the same underlying event or "
        "fact. Return JSON as specified."
    )

    try:
        data = await complete_json(prompt, system=_load_dedup_prompt())
    except Exception:  # noqa: BLE001 -- a failed dedup must not abort the sweep
        return []

    raw = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []

    groups: list[list[int]] = []
    for group in raw:
        if not isinstance(group, list):
            continue
        idxs = [int(x) for x in group if isinstance(x, (int, float)) and not isinstance(x, bool)]
        if len(idxs) >= 2:
            groups.append(idxs)
    return groups
