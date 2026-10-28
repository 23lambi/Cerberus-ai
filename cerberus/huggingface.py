# Hugging Face as a second place to get models, for the Models panel.
#
# Hugging Face (huggingface.co) is where most AI models are published.
# Models made for computers like this one come as GGUF files: one file per
# version, from big and precise (Q8_0) to small and rough (Q2_K). Q4_K_M
# is the usual choice. Unlike ollama.com, Hugging Face has an official
# API, so this asks it directly (only your search words are sent).
#
# The download itself goes through Ollama, which can run Hugging Face
# models by their address: "hf.co/<repo>:<version>", for example
# hf.co/bartowski/Qwen2.5-7B-Instruct-GGUF:Q4_K_M.

import re
import time

import httpx

API = "https://huggingface.co/api/models"
MAX_RESULTS = 20
MAX_BROWSE = 100  # one list: the page shows 30 at a time
BROWSE_CACHE_SECONDS = 3600

# The lists to browse. Hugging Face sorts by its own names. There is no
# "newest": brand-new uploads haven't been tried by anyone yet, and many
# are spam.
ORDERS = {"popular": "downloads", "trending": "trendingScore", "liked": "likes"}
# The categories Ollama can run, by Hugging Face's "pipeline tag". There
# is no "all": that would mix in image, music and speech models.
CATEGORIES = {"chat": "text-generation", "vision": "image-text-to-text", "embedding": "feature-extraction"}
SUGGESTED = "Q4_K_M"  # good quality for its size: what most people pick

# A repo name: "bartowski/Qwen2.5-7B-Instruct-GGUF".
REPO = re.compile(r"[\w.\-]{1,96}/[\w.\-]{1,96}")
# The version in a file name, like "Qwen2.5-7B-Instruct-Q4_K_M.gguf", also
# for big models split in parts: "...-Q8_0-00001-of-00002.gguf".
VERSION = re.compile(
    r"[-_.]((?:I?Q\d(?:_[A-Z0-9]+)*)|B?F(?:P)?(?:16|32))(?:-\d{5}-of-\d{5})?\.gguf$",
    re.IGNORECASE,
)


class HuggingFaceError(Exception):
    pass


async def get(url, params=None):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError:
        raise HuggingFaceError("huggingface.co could not be reached. Are you online?") from None
    if response.status_code == 404:
        raise HuggingFaceError("That model doesn't exist on Hugging Face.")
    if response.status_code != 200:
        raise HuggingFaceError(f"huggingface.co answered with error {response.status_code}.")
    return response.json()


def as_models(found):
    """What the panel needs from Hugging Face's answer."""
    return [{
        "repo": model["id"],
        "downloads": model.get("downloads", 0),
        "likes": model.get("likes", 0),
        # "image-text-to-text" = it can look at pictures.
        "vision": model.get("pipeline_tag") == "image-text-to-text",
        "embedding": model.get("pipeline_tag") == "feature-extraction",
    } for model in found]


async def search(query):
    """GGUF models for the search words, the most downloaded first."""
    return as_models(await get(API, {
        "search": query, "filter": "gguf", "sort": "downloads", "direction": "-1", "limit": MAX_RESULTS,
    }))


# The browse lists, kept for an hour: {("popular", "chat"): (time, models)}.
browse_cache = {}


async def browse(order="popular", category="chat"):
    """A list to browse without searching: GGUF models of one category."""
    order = order if order in ORDERS else "popular"
    category = category if category in CATEGORIES else "chat"
    cached = browse_cache.get((order, category))
    if cached and time.monotonic() - cached[0] < BROWSE_CACHE_SECONDS:
        return cached[1]
    models = as_models(await get(API, {
        "filter": "gguf", "pipeline_tag": CATEGORIES[category],
        "sort": ORDERS[order], "direction": "-1", "limit": MAX_BROWSE,
    }))
    browse_cache[(order, category)] = (time.monotonic(), models)
    return models


def versions_of(files):
    """The versions in a list of (file name, size): [{"version", "size"}], small first.

    A version split into several files is one version with their sizes
    added up. mmproj files are the vision part of a model, not a version.
    """
    sizes = {}
    for name, size in files:
        if "mmproj" in name.lower():
            continue
        match = VERSION.search(name)
        if match:
            version = match.group(1).upper()
            sizes[version] = sizes.get(version, 0) + (size or 0)
    return sorted(({"version": v, "size": s} for v, s in sizes.items()), key=lambda item: item["size"])


async def versions(repo):
    """The downloadable versions of one model, and what to know first."""
    if not REPO.fullmatch(repo):
        raise HuggingFaceError("That isn't a Hugging Face model name, like user/model-GGUF.")
    info = await get(f"{API}/{repo}", {"blobs": "true"})
    files = [(f["rfilename"], f.get("size")) for f in info.get("siblings", [])]
    found = versions_of(files)
    names = {item["version"] for item in found}
    return {
        "repo": repo,
        # Gated models need a Hugging Face account and accepted terms
        # first, so Ollama can't download them without signing in.
        "gated": bool(info.get("gated")),
        "license": (info.get("cardData") or {}).get("license") or "",
        "suggested": SUGGESTED if SUGGESTED in names else "",
        "versions": [{**item, "ollama_name": f"hf.co/{repo}:{item['version']}"} for item in found],
    }
