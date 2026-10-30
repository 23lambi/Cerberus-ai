# Web search (Stage 3, step 1): ask a search engine and turn its answer
# into a short, clean list of results.
#
# You choose the engine in Settings (web_engine):
#   - SearXNG: runs on this computer, asks other engines for us and hands
#     back their results without ads or tracking. No key.
#   - DuckDuckGo: its simple HTML page, read directly. Nothing to install,
#     no key, but it may ask for a CAPTCHA after many searches in a row.
#   - Brave Search and Tavily: official search APIs. Reliable, but they
#     need a (free) API key, kept private in keys.py.
#
# Every engine answers in its own way. Each one gets a small function that
# turns its answer into the same shape: [{"title", "url", "snippet"}, ...].
# search() picks the function, so the chat and the research agent never
# need to know which engine is used.
#
# Nothing here downloads the pages themselves; that's step 2.

import html
import re
import sys
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import httpx

from cerberus.core import settings
from cerberus.core.config import WEB_ENGINES, WEB_RESULTS, WEB_SEARCH_TIMEOUT
from cerberus.storage import keys



def docker(command, platform_name=None):
    """A docker command as you type it on this system. On Linux Docker
    needs sudo; Docker Desktop (Windows, macOS) doesn't, and has no sudo."""
    # Read sys.platform now, not as the default above: a default is worked
    # out once, when Python first reads this file.
    platform_name = platform_name or sys.platform
    return ("sudo docker " if platform_name.startswith("linux") else "docker ") + command


NOT_RUNNING = ("SearXNG can't be reached at {url}. Is it running? Setup → Web search can "
               "install or start it. With Docker, start it with: {command}")
# Some sites refuse the default "python-httpx" name (as in webpage.py).
USER_AGENT = "Mozilla/5.0 (compatible; Cerberus; private local assistant)"


class WebError(Exception):
    # A problem with web search the user should see, like "SearXNG isn't
    # running". Like OllamaError: callers catch only this, not every bug.
    pass


def new_client(timeout):
    # One place that makes the HTTP client, so the tests can swap in a
    # fake one that answers without a real search engine.
    return httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT})


async def search(query, limit=WEB_RESULTS):
    """The best results for query from the chosen engine, as [{"title", "url", "snippet"}, ...]."""
    engine = settings.get("web_engine")
    if engine == "duckduckgo":
        found = await duckduckgo(query)
    elif engine in ("brave", "tavily"):
        key = keys.get(f"{engine}_key")
        if not key:
            raise WebError(f"{WEB_ENGINES[engine]} needs an API key. Add it in Settings → Web search.")
        found = await (brave(key, query, limit) if engine == "brave" else tavily(key, query, limit))
    elif settings.get("searxng_on") == "no":
        raise WebError("SearXNG is switched off. Switch it on in Settings → Web, or choose another engine.")
    else:
        found = await searxng(settings.get("web_url"), query)
    return clean(found, limit)


def clean(found, limit):
    """Only normal web pages, each once, with tidy text, at most limit."""
    results = []
    seen = set()  # several engines often find the same page
    for item in found:
        url = item.get("url") or ""
        # Only normal web pages. Other kinds (like "magnet:" links) can't
        # be read, and step 2 must never be asked to open them.
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        results.append({
            "title": (item.get("title") or url).strip(),
            "url": url,
            "snippet": (item.get("snippet") or "").strip(),
        })
        if len(results) >= limit:
            break
    return results


def without_tags(text):
    # Brave marks the searched words as <strong>python</strong>; we only
    # want the words. unescape turns "&amp;" back into "&".
    return html.unescape(re.sub(r"<[^>]+>", "", text or ""))


async def ask(name, method, url, **request):
    """One request to an engine. A network problem becomes a clear WebError."""
    try:
        async with new_client(WEB_SEARCH_TIMEOUT) as client:
            return await client.request(method, url, **request)
    except httpx.HTTPError:
        raise WebError(f"{name} can't be reached. Are you online?") from None


def read_json(name, response):
    """The engine's JSON answer, or a WebError that says what went wrong."""
    if response.status_code in (401, 403):
        raise WebError(f"{name} refused the API key. Check it in Settings → Web search.")
    if response.status_code == 429:
        raise WebError(f"{name} says: too many searches. Wait a little, or check your plan's limit.")
    if response.status_code != 200:
        raise WebError(f"{name} answered with error {response.status_code}.")
    try:
        return response.json()
    except ValueError:
        raise WebError(f"{name}'s answer could not be read.") from None


# ---------- SearXNG ----------


async def searxng(base_url, query):
    # We use its JSON answer: the same search page a browser gets, but as
    # data instead of HTML. rstrip("/"): ".../8888/" and ".../8888" both work.
    address = base_url.rstrip("/") + "/search"
    try:
        async with new_client(WEB_SEARCH_TIMEOUT) as client:
            # params= builds "?q=...&format=json" and encodes the spaces
            # and special characters of the query safely.
            response = await client.get(address, params={"q": query, "format": "json"})
    except httpx.HTTPError:
        # Not running, wrong address, or too slow to answer.
        raise WebError(NOT_RUNNING.format(url=base_url, command=docker("start searxng"))) from None

    # SearXNG answers 403 "Forbidden" when JSON isn't switched on.
    if response.status_code == 403:
        raise WebError(
            "SearXNG refused to answer in JSON. Add json under "
            "search: formats: in its settings.yml, then: " + docker("restart searxng")
        )
    data = read_json("SearXNG", response)
    # "content" is SearXNG's name for the short text under a result.
    return [{"title": item.get("title"), "url": item.get("url"), "snippet": item.get("content")}
            for item in data.get("results", [])]


async def searxng_check(url):
    """"ok", "json_off" (it runs, but JSON is off), or "offline"."""
    try:
        async with new_client(5) as client:
            response = await client.get(url.rstrip("/") + "/search", params={"q": "cerberus", "format": "json"})
    except httpx.HTTPError:
        return "offline"
    if response.status_code == 403:
        return "json_off"
    return "ok" if response.status_code == 200 else "offline"


# ---------- DuckDuckGo ----------


class DuckDuckGoPage(HTMLParser):
    # Reads DuckDuckGo's HTML results page. Each result is a link with the
    # class "result__a" (title and address), then "result__snippet" (the
    # text under it). Ads sit in a box with the class "result--ad".
    def __init__(self):
        super().__init__()
        self.results = []
        self.reading = None  # "title" or "snippet" while inside that link
        self.in_ad = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "div" and "result" in classes:
            self.in_ad = "result--ad" in classes
        if tag == "a" and not self.in_ad:
            if "result__a" in classes:
                self.results.append({"title": "", "url": real_address(attrs.get("href")), "snippet": ""})
                self.reading = "title"
            elif "result__snippet" in classes and self.results:
                self.reading = "snippet"

    def handle_endtag(self, tag):
        if tag == "a":
            self.reading = None

    def handle_data(self, data):
        # The text can come in parts (<b>python</b> asyncio), so we add them up.
        if self.reading:
            self.results[-1][self.reading] += data


def real_address(href):
    # DuckDuckGo sometimes wraps an address in its own redirect:
    # //duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F. The real
    # address is the "uddg" value; parse_qs also decodes the %2F parts.
    href = href or ""
    if "duckduckgo.com/l/" in href:
        return parse_qs(urlsplit(href).query).get("uddg", [""])[0]
    return href


async def duckduckgo(query):
    response = await ask("DuckDuckGo", "POST", "https://html.duckduckgo.com/html/", data={"q": query})
    if response.status_code != 200:
        raise WebError(f"DuckDuckGo answered with error {response.status_code}.")
    page = DuckDuckGoPage()
    page.feed(response.text)
    # No results and a challenge form: DuckDuckGo thinks we're a robot.
    if not page.results and ("anomaly" in response.text or "challenge" in response.text):
        raise WebError("DuckDuckGo asked for a CAPTCHA (too many searches). "
                       "Wait a few minutes, or choose another engine in Settings.")
    return page.results


# ---------- Brave Search and Tavily (API keys) ----------


async def brave(key, query, limit):
    response = await ask(
        "Brave Search", "GET", "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": limit},
        headers={"Accept": "application/json", "X-Subscription-Token": key},
    )
    data = read_json("Brave Search", response)
    return [{"title": without_tags(item.get("title")), "url": item.get("url"),
             "snippet": without_tags(item.get("description"))}
            for item in data.get("web", {}).get("results", [])]


async def tavily(key, query, limit):
    response = await ask(
        "Tavily", "POST", "https://api.tavily.com/search",
        json={"query": query, "max_results": limit},
        headers={"Authorization": f"Bearer {key}"},
    )
    data = read_json("Tavily", response)
    return [{"title": item.get("title"), "url": item.get("url"), "snippet": item.get("content")}
            for item in data.get("results", [])]
