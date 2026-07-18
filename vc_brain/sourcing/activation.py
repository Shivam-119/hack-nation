"""Activation engine: generate outreach for high-scoring sourced founders.

Cold outreach, not cold investment -- the goal is to trigger a real application.
Activated applications flow into the same Screening step as inbound.
"""

from __future__ import annotations

from dataclasses import dataclass

from vc_brain.llm import complete
from vc_brain.memory.models import Founder


@dataclass
class OutreachDraft:
    founder_id: str
    founder_name: str
    channel: str  # email | twitter_dm | linkedin
    subject: str
    body: str
    reasoning: str  # why this founder was selected


class ActivationEngine:
    """Generate personalized outreach messages for top-scoring outbound candidates."""

    SYSTEM_PROMPT = (
        "You are an outreach specialist for a venture fund. Write a concise, "
        "personalized cold email to a founder we discovered through their public work. "
        "The tone should be respectful, specific about WHY we noticed them, and invite "
        "them to apply for funding. Keep it under 150 words. No hard sell."
    )

    async def draft_outreach(self, founder: Founder, fund_thesis: str = "") -> OutreachDraft:
        """Generate a personalized outreach draft for a founder."""
        context = self._build_context(founder, fund_thesis)

        prompt = (
            f"Write a short outreach email for this founder.\n\n"
            f"Context:\n{context}\n\n"
            f"Return the email with a subject line on the first line prefixed 'Subject: ', "
            f"then a blank line, then the body."
        )

        response = await complete(prompt, system=self.SYSTEM_PROMPT)
        subject, body = self._parse_email(response)

        return OutreachDraft(
            founder_id=founder.id,
            founder_name=founder.name,
            channel="email" if founder.email else "linkedin",
            subject=subject,
            body=body,
            reasoning=f"Founder Score: {founder.score.overall}, "
                       f"Skills: {', '.join(founder.skills[:5])}",
        )

    def _build_context(self, founder: Founder, fund_thesis: str) -> str:
        lines = [
            f"Name: {founder.name}",
            f"Location: {founder.location}",
            f"Bio: {founder.bio}",
            f"Skills: {', '.join(founder.skills[:10])}",
            f"Founder Score: {founder.score.overall}/100",
        ]
        if founder.github_url:
            lines.append(f"GitHub: {founder.github_url}")
        if fund_thesis:
            lines.append(f"Fund thesis: {fund_thesis}")
        return "\n".join(lines)

    def _parse_email(self, text: str) -> tuple[str, str]:
        lines = text.strip().split("\n")
        subject = ""
        body_start = 0
        for i, line in enumerate(lines):
            if line.lower().startswith("subject:"):
                subject = line.split(":", 1)[1].strip()
                body_start = i + 1
                break

        body_lines = lines[body_start:]
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        return subject, "\n".join(body_lines)
