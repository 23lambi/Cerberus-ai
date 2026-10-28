# Searching Ollama's model library (ollama.com) for the Models panel.
#
# Ollama has no official search API, so we read its normal search page,
# like a browser would, and pick out each model's name, description, tags
# and sizes. If ollama.com ever redesigns that page, this finds nothing
# (it never crashes), and you can still type an exact model name: the
# download itself uses Ollama's official API (ollama.pull).
#
# Only your search words are sent to ollama.com.

import re
import time
from html.parser import HTMLParser

import httpx

SEARCH_URL = "https://ollama.com/search"
LIBRARY_URL = "https://ollama.com/library"  # every model, most popular first
MAX_RESULTS = 20
MAX_BROWSE = 300  # the whole library is about 260 models
BROWSE_CACHE_SECONDS = 3600  # ask ollama.com at most once an hour per list

# What a model can do, as ollama.com tags it.
CAPABILITIES = {"tools", "vision", "thinking", "embedding", "audio", "cloud"}
# Sizes like "0.5b", "70b", "8x7b", "e2b", "135m". Case matters: the
# download count looks alike but is written in capitals ("5.2M" = 5.2 million).
SIZE = re.compile(r"^(e?\d+(\.\d+)?|\d+x\d+(\.\d+)?)[bm]$")


class LibraryError(Exception):
    pass


class SearchPage(HTMLParser):
    """Collects the results of ollama.com/search: one per link to /library/<name>."""

    def __init__(self):
        super().__init__()
        self.models = []
        self.current = None  # the result we're inside
        self.in_description = False
        self.described = False  # only the first <p> is the description
        self.in_span = False
        self.last_text = ""  # the text before "Pulls" is the download count

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        href = attrs.get("href") or ""
        if tag == "a" and re.fullmatch(r"/library/[\w.\-]+", href):
            self.current = {
                "name": href.rsplit("/", 1)[1],
                "description": "",
                "capabilities": [],
                "sizes": [],
                "downloads": "",
            }
            self.models.append(self.current)
            self.described = False
        elif self.current is not None:
            if tag == "p" and not self.described:
                # The library page has a second <p> with "41.5M Pulls ·
                # 29 Tags · Updated...": that one isn't the description.
                self.in_description = True
            elif tag == "span":
                self.in_span = True
                # The download count is in a title: "43,896,967 downloads".
                title = attrs.get("title") or ""
                if title.endswith(" downloads"):
                    self.current["downloads"] = title.removesuffix(" downloads")

    def handle_endtag(self, tag):
        if tag == "a":
            self.current = None
        elif tag == "p" and self.in_description:
            self.in_description = False
            self.described = True
        elif tag == "span":
            self.in_span = False

    def handle_data(self, data):
        if self.current is None:
            return
        text = data.strip()
        if self.in_description:
            self.current["description"] += data
        elif self.in_span and text:
            # The library page writes the count as "41.5M" then "Pulls"
            # (\xa0 is the non-breaking space in "&nbsp;Pulls").
            if text.replace("\xa0", " ").strip() == "Pulls":
                self.current["downloads"] = self.current["downloads"] or self.last_text
            self.last_text = text
            if text in CAPABILITIES and text not in self.current["capabilities"]:
                self.current["capabilities"].append(text)
            elif SIZE.match(text) and text not in self.current["sizes"]:
                self.current["sizes"].append(text)


def parse(html, limit=MAX_RESULTS):
    """The models on an ollama.com search or library page."""
    page = SearchPage()
    page.feed(html)
    seen = set()
    models = []
    for model in page.models:
        if model["name"] in seen:
            continue
        seen.add(model["name"])
        model["description"] = " ".join(model["description"].split())
        models.append(model)
    return models[:limit]


async def fetch(url, params=None):
    """An ollama.com page as text. Raises LibraryError when it can't be reached."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url, params=params,
                                        headers={"User-Agent": "Mozilla/5.0 (compatible; Cerberus)"})
    except httpx.HTTPError:
        raise LibraryError("ollama.com could not be reached. Are you online?") from None
    if response.status_code != 200:
        raise LibraryError(f"ollama.com answered with error {response.status_code}.")
    return response.text


async def search(query):
    """Search ollama.com for models."""
    return parse(await fetch(SEARCH_URL, {"q": query}))


# The browse lists, kept for a while: {"popular": (time fetched, models)}.
# The library changes slowly, and opening the panel shouldn't ask
# ollama.com every time.
browse_cache = {}


async def browse(order="popular"):
    """The models to browse without searching: "popular" (the whole library,
    most downloaded first) or "newest" (the latest additions)."""
    cached = browse_cache.get(order)
    if cached and time.monotonic() - cached[0] < BROWSE_CACHE_SECONDS:
        return cached[1]
    if order == "newest":
        models = parse(await fetch(SEARCH_URL), MAX_BROWSE)
    else:
        models = parse(await fetch(LIBRARY_URL), MAX_BROWSE)
    browse_cache[order] = (time.monotonic(), models)
    return models
