# Web search (Stage 3, step 1): ask SearXNG, a search engine that runs on
# this computer, and turn its answer into a short, clean list of results.
#
# SearXNG asks other search engines for us and hands back their results
# without ads or tracking. We use its JSON answer: the same search page
# a browser gets, but as data instead of HTML.
#
# Nothing here downloads the pages themselves; that's step 2.

import httpx

from cerberus.core.config import WEB_RESULTS, WEB_SEARCH_TIMEOUT

NOT_RUNNING = (
    "SearXNG can't be reached at {url}. Is it running? "
    "Start it with: sudo docker start searxng"
)


class WebError(Exception):
    # A problem with web search the user should see, like "SearXNG isn't
    # running". Like OllamaError: callers catch only this, not every bug.
    pass


def new_client(timeout):
    # One place that makes the HTTP client, so the tests can swap in a
    # fake one that answers without a real SearXNG.
    return httpx.AsyncClient(timeout=timeout)


async def search(base_url, query, limit=WEB_RESULTS):
    """The best results for query, as [{"title", "url", "snippet"}, ...]."""
    # rstrip("/"): "http://127.0.0.1:8888/" and ".../8888" both work.
    address = base_url.rstrip("/") + "/search"
    try:
        async with new_client(WEB_SEARCH_TIMEOUT) as client:
            # params= builds "?q=...&format=json" and encodes the spaces
            # and special characters of the query safely.
            response = await client.get(address, params={"q": query, "format": "json"})
    except httpx.HTTPError:
        # Not running, wrong address, or too slow to answer.
        raise WebError(NOT_RUNNING.format(url=base_url)) from None

    # SearXNG answers 403 "Forbidden" when JSON isn't switched on.
    if response.status_code == 403:
        raise WebError(
            "SearXNG refused to answer in JSON. Add json under "
            "search: formats: in its settings.yml, then: sudo docker restart searxng"
        )
    if response.status_code != 200:
        raise WebError(f"SearXNG answered with error {response.status_code}.")
    try:
        data = response.json()
    except ValueError:
        raise WebError("SearXNG's answer could not be read.") from None

    results = []
    seen = set()  # several engines often find the same page
    for item in data.get("results", []):
        url = item.get("url") or ""
        # Only normal web pages. Other kinds (like "magnet:" links) can't
        # be read, and step 2 must never be asked to open them.
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        results.append({
            "title": (item.get("title") or url).strip(),
            "url": url,
            # "content" is SearXNG's name for the short text under a result.
            "snippet": (item.get("content") or "").strip(),
        })
        if len(results) >= limit:
            break
    return results
