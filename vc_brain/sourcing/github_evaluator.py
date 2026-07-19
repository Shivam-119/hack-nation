"""GitHub evaluator — 6-dimension founder assessment.

Dimensions:
1. Technical ability — GitHub activity, production code, open source, engineering depth
2. Execution ability — products launched, shipping speed, projects completed
3. Founder/product ability — real users, traction (limited from GitHub alone)
4. Technical background — languages, infrastructure, AI/ML, domain signals
5. Reputation and credibility — stars, forks, community contributions
6. Growth signals — increasing complexity, expanding scope, career progression

What GitHub CAN tell us vs what it CAN'T is flagged explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from vc_brain.config import config

TUTORIAL_KEYWORDS = {
    "todo", "tutorial", "course", "homework", "assignment", "exercise",
    "bootcamp", "learning", "practice", "hello-world", "test", "demo",
    "example", "sample", "starter", "template", "boilerplate",
}

INFRA_KEYWORDS = {"docker", "kubernetes", "k8s", "terraform", "aws", "gcp", "azure", "ci", "cd", "deploy", "infra", "cloud", "devops"}
AI_KEYWORDS = {"ai", "ml", "machine-learning", "deep-learning", "neural", "llm", "gpt", "transformer", "pytorch", "tensorflow", "model"}


@dataclass
class BuilderEvaluation:
    username: str
    is_builder: bool
    grade: str
    score: float  # 0-100
    technical_ability: float
    execution_ability: float
    founder_product_ability: float
    technical_background: float
    reputation: float
    growth_signals: float
    signals: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    not_measurable: list[str] = field(default_factory=list)


async def evaluate(username: str) -> BuilderEvaluation:
    headers = {"Accept": "application/vnd.github+json"}
    if config.github_token:
        headers["Authorization"] = f"Bearer {config.github_token}"

    async with httpx.AsyncClient(headers=headers, timeout=20) as client:
        user = (await client.get(f"https://api.github.com/users/{username}")).json()
        repos_resp = await client.get(
            f"https://api.github.com/users/{username}/repos",
            params={"per_page": 100, "sort": "pushed", "type": "owner"},
        )
        repos = repos_resp.json() if repos_resp.status_code == 200 else []
        events_resp = await client.get(
            f"https://api.github.com/users/{username}/events/public",
            params={"per_page": 100},
        )
        events = events_resp.json() if events_resp.status_code == 200 else []

    signals = []
    red_flags = []
    not_measurable = []

    original = [r for r in repos if not r.get("fork")]
    forks = [r for r in repos if r.get("fork")]
    real_repos = [r for r in original if not _is_tutorial(r)]
    now = datetime.utcnow()

    # ── 1. TECHNICAL ABILITY (25%) ────────────────────────────────────
    tech = 0.0

    # GitHub activity — public repos with real code
    substantial = [r for r in real_repos if r.get("size", 0) > 100]
    if len(substantial) >= 5:
        tech += 25
        signals.append(f"{len(substantial)} substantial codebases")
    elif len(substantial) >= 2:
        tech += 15
        signals.append(f"{len(substantial)} substantial codebases")
    elif len(substantial) >= 1:
        tech += 8

    # Open source contributions — pushes to repos they don't own
    push_events = [e for e in events if e.get("type") == "PushEvent"]
    contrib_to_others = [e for e in push_events if e.get("repo", {}).get("name", "").split("/")[0] != username]
    if len(contrib_to_others) >= 5:
        tech += 20
        signals.append(f"Active open source contributor ({len(contrib_to_others)} pushes to other repos)")
    elif len(contrib_to_others) >= 1:
        tech += 10
        signals.append("Contributes to other projects")

    # Engineering depth — large repos suggest system design
    large_repos = [r for r in real_repos if r.get("size", 0) > 1000]
    if len(large_repos) >= 2:
        tech += 20
        signals.append(f"{len(large_repos)} large-scale projects (>1MB)")
    elif len(large_repos) >= 1:
        tech += 10

    # Language count — technical range
    languages = set(r.get("language") or "" for r in real_repos) - {""}
    if len(languages) >= 5:
        tech += 20
        signals.append(f"{len(languages)} languages — deep technical range")
    elif len(languages) >= 3:
        tech += 12
        signals.append(f"{len(languages)} languages")
    elif len(languages) >= 1:
        tech += 5

    # PR/code review activity — engineering discipline
    pr_events = [e for e in events if e.get("type") == "PullRequestReviewEvent"]
    if len(pr_events) >= 3:
        tech += 15
        signals.append("Reviews others' code")

    not_measurable.append("System design experience — needs interview or technical writeup")

    tech = max(0, min(100, tech))

    # ── 2. EXECUTION ABILITY (25%) ────────────────────────────────────
    exe = 0.0

    # Products launched — repos with live URLs
    shipped = [r for r in real_repos if r.get("homepage")]
    if len(shipped) >= 3:
        exe += 25
        signals.append(f"{len(shipped)} projects with live URLs — ships to users")
    elif len(shipped) >= 1:
        exe += 15
        signals.append(f"{len(shipped)} project with live URL")

    # Speed of shipping — how many repos pushed in last 90 days
    cutoff_90d = (now - timedelta(days=90)).isoformat() + "Z"
    active_90 = [r for r in real_repos if (r.get("pushed_at") or "") > cutoff_90d]
    if len(active_90) >= 5:
        exe += 25
        signals.append(f"{len(active_90)} repos pushed in last 90 days — ships fast")
    elif len(active_90) >= 3:
        exe += 18
        signals.append(f"{len(active_90)} repos pushed in last 90 days")
    elif len(active_90) >= 1:
        exe += 8

    # Number of projects completed — repos with descriptions + substantial code
    completed = [r for r in real_repos if r.get("description") and r.get("size", 0) > 100]
    if len(completed) >= 5:
        exe += 20
        signals.append(f"{len(completed)} completed projects")
    elif len(completed) >= 2:
        exe += 12

    # Operates independently — original repos vs forks ratio
    if len(repos) > 3:
        orig_ratio = len(original) / len(repos)
        if orig_ratio >= 0.7:
            exe += 15
            signals.append(f"{int(orig_ratio * 100)}% original work")
        elif orig_ratio < 0.3:
            red_flags.append(f"Only {int(orig_ratio * 100)}% original work — mostly forks")

    # Evidence of solving difficult problems — large + well-starred repos
    hard_projects = [r for r in real_repos if r.get("size", 0) > 500 and r.get("stargazers_count", 0) >= 5]
    if hard_projects:
        exe += 15
        signals.append(f"{len(hard_projects)} non-trivial projects with external validation")

    exe = max(0, min(100, exe))

    # ── 3. FOUNDER/PRODUCT ABILITY (15%) ──────────────────────────────
    founder = 0.0

    # Real users — forks = someone using/building on the code
    total_forks = sum(r.get("forks_count", 0) for r in original)
    if total_forks >= 50:
        founder += 35
        signals.append(f"{total_forks} forks — real users building on their work")
    elif total_forks >= 10:
        founder += 20
        signals.append(f"{total_forks} forks")
    elif total_forks >= 3:
        founder += 10

    # Issues filed by others = people using the product
    issue_events = [e for e in events if e.get("type") == "IssuesEvent"]
    if len(issue_events) >= 5:
        founder += 25
        signals.append("Active issue tracker — users report bugs/requests")
    elif len(issue_events) >= 1:
        founder += 10

    # Product iterations — repos updated many times over months
    cutoff_180d = (now - timedelta(days=180)).isoformat() + "Z"
    iterated = [r for r in real_repos if r.get("pushed_at", "") > cutoff_180d and r.get("size", 0) > 200]
    if len(iterated) >= 3:
        founder += 20
        signals.append(f"{len(iterated)} projects actively iterated on")
    elif len(iterated) >= 1:
        founder += 10

    # Breakout repo — single repo with outsized traction
    max_stars = max((r.get("stargazers_count", 0) for r in original), default=0)
    if max_stars >= 100:
        founder += 20
        signals.append(f"Breakout project with {max_stars} stars")
    elif max_stars >= 20:
        founder += 10
        signals.append(f"Top project has {max_stars} stars")

    not_measurable.append("Revenue/business traction — needs application data")
    not_measurable.append("Customer interviews — not visible on GitHub")

    founder = max(0, min(100, founder))

    # ── 4. TECHNICAL BACKGROUND (15%) ─────────────────────────────────
    bg = 0.0

    # Detect infrastructure/cloud experience from repo topics and names
    all_topics = set()
    all_text = ""
    for r in real_repos:
        all_topics.update(r.get("topics") or [])
        all_text += f" {r.get('name', '')} {r.get('description', '')}"
    all_text = all_text.lower()

    infra_hits = [kw for kw in INFRA_KEYWORDS if kw in all_text or kw in all_topics]
    if len(infra_hits) >= 3:
        bg += 30
        signals.append(f"Infrastructure experience: {', '.join(infra_hits[:5])}")
    elif len(infra_hits) >= 1:
        bg += 15

    # AI/ML experience
    ai_hits = [kw for kw in AI_KEYWORDS if kw in all_text or kw in all_topics]
    if len(ai_hits) >= 3:
        bg += 30
        signals.append(f"AI/ML experience: {', '.join(ai_hits[:5])}")
    elif len(ai_hits) >= 1:
        bg += 15
        signals.append(f"AI/ML signal: {', '.join(ai_hits)}")

    # Domain depth — repos in same topic area
    if all_topics:
        bg += 15
        signals.append(f"Tagged domains: {', '.join(list(all_topics)[:8])}")

    # Years on platform as proxy for experience
    created_at = user.get("created_at", "")
    if created_at:
        try:
            age_years = (now - datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)).days / 365
            if age_years >= 5 and len(real_repos) >= 5:
                bg += 25
                signals.append(f"{int(age_years)} years on GitHub with sustained output")
            elif age_years >= 2 and len(real_repos) >= 3:
                bg += 15
        except (ValueError, TypeError):
            pass

    not_measurable.append("Previous companies — needs LinkedIn data")
    not_measurable.append("Startup experience — needs application data")

    bg = max(0, min(100, bg))

    # ── 5. REPUTATION & CREDIBILITY (10%) ─────────────────────────────
    rep = 0.0

    # Stars — social proof (matters more per-repo than total)
    total_stars = sum(r.get("stargazers_count", 0) for r in original)
    if total_stars >= 500:
        rep += 30
        signals.append(f"{total_stars} total stars")
    elif total_stars >= 100:
        rep += 20
        signals.append(f"{total_stars} stars")
    elif total_stars >= 20:
        rep += 10
    elif total_stars < 5 and len(real_repos) > 3:
        red_flags.append(f"Only {total_stars} stars across {len(real_repos)} repos")

    # Breakout single repo (stronger signal than spread-out stars)
    if max_stars >= 200:
        rep += 20
        signals.append(f"Single repo with {max_stars} stars — recognized project")

    # Followers
    followers = user.get("followers", 0)
    if followers >= 100:
        rep += 20
        signals.append(f"{followers} followers")
    elif followers >= 20:
        rep += 10

    # Community contributions — contributes to others' repos
    if len(contrib_to_others) >= 3:
        rep += 15

    # Personal site / blog
    if user.get("blog"):
        rep += 15
        signals.append("Has personal site")

    not_measurable.append("References — needs direct outreach")
    not_measurable.append("Publications/research — needs arXiv/Scholar data")

    rep = max(0, min(100, rep))

    # ── 6. GROWTH SIGNALS (10%) ───────────────────────────────────────
    growth = 0.0

    # Increasing project complexity — compare older vs newer repos
    if len(real_repos) >= 4:
        sorted_repos = sorted(real_repos, key=lambda r: r.get("created_at", ""))
        older_half = sorted_repos[:len(sorted_repos) // 2]
        newer_half = sorted_repos[len(sorted_repos) // 2:]

        avg_size_old = sum(r.get("size", 0) for r in older_half) / max(len(older_half), 1)
        avg_size_new = sum(r.get("size", 0) for r in newer_half) / max(len(newer_half), 1)

        if avg_size_new > avg_size_old * 1.5:
            growth += 35
            signals.append("Projects growing in complexity over time")
        elif avg_size_new > avg_size_old:
            growth += 20

        # Expanding technical scope — more languages in newer repos
        old_langs = set(r.get("language") or "" for r in older_half) - {""}
        new_langs = set(r.get("language") or "" for r in newer_half) - {""}
        new_additions = new_langs - old_langs
        if len(new_additions) >= 2:
            growth += 25
            signals.append(f"Expanding scope — picked up {', '.join(new_additions)}")
        elif len(new_additions) >= 1:
            growth += 15

    # Commit cadence trending up — more push days recently vs overall pattern
    unique_days = sorted({e.get("created_at", "")[:10] for e in push_events if e.get("created_at")})
    if len(unique_days) >= 10:
        midpoint = len(unique_days) // 2
        first_half = unique_days[:midpoint]
        second_half = unique_days[midpoint:]
        if len(second_half) > len(first_half):
            growth += 20
            signals.append("Commit frequency increasing")

    # Sustained across months — not just a phase
    push_months = {r.get("pushed_at", "")[:7] for r in real_repos if r.get("pushed_at")}
    cutoff_365d = (now - timedelta(days=365)).isoformat()[:7]
    recent_months = {m for m in push_months if m >= cutoff_365d}
    if len(recent_months) >= 8:
        growth += 20
        signals.append(f"Active {len(recent_months)} of last 12 months")

    not_measurable.append("Learning speed — needs interview")
    not_measurable.append("Career progression — needs LinkedIn data")

    growth = max(0, min(100, growth))

    # ── FINAL SCORE ───────────────────────────────────────────────────
    score = (
        tech * 0.25
        + exe * 0.25
        + founder * 0.15
        + bg * 0.15
        + rep * 0.10
        + growth * 0.10
    )
    score = round(max(0, min(100, score)), 1)

    is_builder = score >= 35 and len(real_repos) >= 2 and len(red_flags) <= len(signals)

    if score >= 75:
        grade = "A"
    elif score >= 55:
        grade = "B"
    elif score >= 35:
        grade = "C"
    elif score >= 20:
        grade = "D"
    else:
        grade = "F"

    return BuilderEvaluation(
        username=username,
        is_builder=is_builder,
        grade=grade,
        score=score,
        technical_ability=round(tech, 1),
        execution_ability=round(exe, 1),
        founder_product_ability=round(founder, 1),
        technical_background=round(bg, 1),
        reputation=round(rep, 1),
        growth_signals=round(growth, 1),
        signals=signals,
        red_flags=red_flags,
        not_measurable=not_measurable,
    )


def _is_tutorial(repo: dict) -> bool:
    name = (repo.get("name") or "").lower().replace("-", " ").replace("_", " ")
    desc = (repo.get("description") or "").lower()
    text = f"{name} {desc}"
    return any(kw in text for kw in TUTORIAL_KEYWORDS)
