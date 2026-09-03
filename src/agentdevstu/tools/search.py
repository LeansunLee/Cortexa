from __future__ import annotations

from typing import Any

import httpx
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def search_web(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    url = "https://html.duckduckgo.com/html/"
    with httpx.Client(timeout=20, follow_redirects=True, headers=_HEADERS) as client:
        response = client.post(url, data={"q": query})
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    results: list[dict[str, Any]] = []

    for item in soup.select(".result"):
        title_el = item.select_one(".result__title a")
        snippet_el = item.select_one(".result__snippet")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        href = title_el.get("href")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        results.append({"title": title, "url": str(href), "snippet": snippet})
        if len(results) >= max_results:
            break
    return results
