from __future__ import annotations

from tavily import TavilyClient

MAX_RESULTS = 5


def search(query: str, api_key: str) -> str:
    """Run a Tavily web search and return the results formatted as a string for the LLM."""
    client = TavilyClient(api_key=api_key)
    response = client.search(query, max_results=MAX_RESULTS, include_answer=False)

    results = response.get("results", [])
    if not results:
        return f"No results found for query: {query!r}"

    lines: list[str] = []
    for r in results:
        title = r.get("title", "")
        url = r.get("url", "")
        content = (r.get("content") or "").strip()
        published = r.get("published_date")
        header = f"- {title} ({url})"
        if published:
            header += f" [published: {published}]"
        lines.append(header)
        if content:
            lines.append(f"  {content}")
    return "\n".join(lines)
