from contextlib import aclosing

# Everything that talks to Ollama goes through this file. The rest of
# Cerberus never builds an Ollama request itself, so if Ollama's API
# changes, this is the only file to fix.

import json

import httpx  # an HTTP client like "requests", but it also works with async
from cerberus.budget import ContextTooLarge, fit

from cerberus.config import (
    DEFAULT_MAX_TOKENS,
    EMBED_MODEL,
    KEEP_ALIVE,
    MAX_HISTORY_MESSAGES,
    NUM_CTX,
    OLLAMA_URL,
    THINK_MAX_TOKENS,
)

NOT_RUNNING = (
    "Ollama isn't running. Start it with: ollama serve "
    "or sudo systemctl start ollama (Linux), brew services start ollama (macOS)"
)


class OllamaError(Exception):
    # Our own error type: callers can catch Ollama problems with
    # "except OllamaError" without catching every other bug too.
    pass


def trim_history(history):
    # A negative slice takes from the end: the newest messages.
    newest = history[-MAX_HISTORY_MESSAGES:]
    if newest and (newest[0].get("role") if isinstance(newest[0], dict) else newest[0].role) == "assistant":
        newest = newest[1:]
    return newest


def error_message(body):
    # Ollama sends errors as {"error": "..."}. Pull out the text if we can.
    try:
        return json.loads(body).get("error", "Unknown error from Ollama")
    except json.JSONDecodeError:
        return "Unknown error from Ollama"


async def list_models():
    # GET /api/tags lists the models installed with "ollama pull".
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
    except httpx.ConnectError:
        # "from None" hides the long httpx traceback; our message says it all.
        raise OllamaError(NOT_RUNNING) from None
    data = response.json()
    return [m["name"] for m in data["models"]]


# Model name -> its abilities. A model's abilities never change, so we ask
# Ollama once per model and remember the answer. This is called a cache.
capabilities_cache = {}


async def capabilities(model):
    # /api/show lists what a model can do, like ["completion", "thinking"].
    if model not in capabilities_cache:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(f"{OLLAMA_URL}/api/show", json={"model": model})
            capabilities_cache[model] = response.json().get("capabilities", [])
        except (httpx.HTTPError, ValueError):
            return []  # don't cache: maybe Ollama is just starting
    return capabilities_cache[model]


async def can_think(model):
    # Models like qwen3 or deepseek-r1 can reason before they answer.
    return "thinking" in await capabilities(model)


async def can_see(model):
    # Vision models (like gemma3 or qwen2.5vl) can look at images.
    return "vision" in await capabilities(model)


async def can_use_tools(model):
    # Models like qwen3-coder or llama3.1 can ask Cerberus to run tools.
    return "tools" in await capabilities(model)


async def can_chat(model):
    # Embedding models (like nomic-embed-text) turn text into numbers and
    # can't chat. An empty list means "unknown" (an older Ollama), so we
    # keep the model rather than hide it by mistake.
    found = await capabilities(model)
    return not found or "completion" in found


# "async def" + "yield" makes an async generator: the caller loops over it
# with "async for" and gets each piece of the answer as soon as it arrives.
# Each piece is a pair (kind, value):
#   ("thinking", text)  the model's reasoning, only when think=True
#   ("content", text)   the answer itself
#   ("tool_calls", list) the model asks to run tools (only with tools=...)
#   ("stats", dict)     once at the end: token counts and speed
async def stream_events(
    model, messages, max_tokens=DEFAULT_MAX_TOKENS, temperature=None, think=False, tools=None
):
    # num_predict = the most tokens the model may write (thinking included!);
    # num_ctx = the context window.
    try:
        messages = fit(messages, max_tokens, tools)
    except ContextTooLarge as error:
        raise OllamaError(str(error)) from None
    options = {"num_predict": max_tokens, "num_ctx": NUM_CTX}
    if temperature is not None:
        # 0 = always the most likely word, higher = more random and creative.
        options["temperature"] = temperature

    body = {
        "model": model,
        "messages": messages,
        "stream": True,
        # Always say it: thinking models think by default, and then their
        # answer would be empty when we don't read the thinking. False
        # works on every model.
        "think": think,
        "keep_alive": KEEP_ALIVE,
        "options": options,
    }
    if tools:
        # The tools the model may ask for (see cerberus/tools.py). Ollama
        # puts them into the prompt in the format the model was trained on.
        body["tools"] = tools

    try:
        # timeout=None: a big model can think for minutes before the first word.
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=body) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise OllamaError(error_message(body))

                # Ollama streams one JSON object per line, like:
                # {"message": {"content": "Hel"}, "done": false}
                # {"message": {"thinking": "We are"}, "done": false}
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise OllamaError(chunk["error"])
                    message = chunk.get("message", {})
                    if message.get("thinking"):
                        yield "thinking", message["thinking"]
                    if message.get("content"):
                        yield "content", message["content"]
                    if message.get("tool_calls"):
                        # Like [{"function": {"name": "calculate",
                        #        "arguments": {"expression": "2*3"}}}]
                        yield "tool_calls", message["tool_calls"]
                    if chunk.get("done"):
                        # The last chunk carries the numbers. Durations are
                        # in nanoseconds (1 second = 1e9 ns).
                        tokens = chunk.get("eval_count", 0)
                        yield "stats", {
                            "tokens": tokens,
                            "seconds": chunk.get("eval_duration", 0) / 1e9,
                            # prompt + answer = how full the context window got
                            "context": chunk.get("prompt_eval_count", 0) + tokens,
                            "num_ctx": NUM_CTX,
                            # "length" = it stopped at max_tokens, not by choice
                            "cut_off": chunk.get("done_reason") == "length",
                        }
                        break
    except httpx.ConnectError:
        raise OllamaError(NOT_RUNNING) from None
    except (httpx.HTTPError, ValueError) as error:
        raise OllamaError(f"Ollama's response could not be read: {error}") from None


async def stream_chat(model, messages, max_tokens=DEFAULT_MAX_TOKENS, temperature=None):
    # Only the answer text, as plain strings. The Guard, titles, summaries,
    # recaps and Deep think use this: they need the answer, not reasoning.
    #
    # Some models (like qwen3:4b "Thinking") always think, even with
    # think=False, and then write their reasoning into the answer. So a
    # thinking model is allowed to think, gets room for it, and we throw
    # the thinking away.
    think = await can_think(model)
    if think:
        max_tokens += THINK_MAX_TOKENS
    async with aclosing(stream_events(model, messages, max_tokens, temperature, think)) as events:
        async for kind, value in events:
            if kind == "content":
                yield value


async def embed(texts):
    # Turns texts into vectors (lists of numbers). Texts with similar meaning
    # get vectors that point in a similar direction. keeper.py uses this.
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": EMBED_MODEL, "input": texts, "keep_alive": KEEP_ALIVE},
            )
    except httpx.ConnectError:
        raise OllamaError(NOT_RUNNING) from None
    if response.status_code != 200:
        raise OllamaError(error_message(response.content))
    return response.json()["embeddings"]


# ---------- Freeing memory ----------


def full_name(model):
    # Ollama adds ":latest" when a name has no tag, so "nomic-embed-text"
    # and "nomic-embed-text:latest" are the same model.
    return model if ":" in model else model + ":latest"


async def loaded_models():
    # GET /api/ps lists the models that are in memory (RAM) right now.
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{OLLAMA_URL}/api/ps")
        return [m["name"] for m in response.json()["models"]]
    except (httpx.HTTPError, ValueError, KeyError):
        return []


async def unload(model):
    # keep_alive 0 means "don't keep this model at all": Ollama frees its
    # RAM right away. A chat request with no messages writes nothing; it
    # only changes how long the model stays loaded.
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={"model": model, "messages": [], "keep_alive": 0},
            )
    except httpx.HTTPError:
        pass  # if Ollama can't be reached, there's nothing to free anyway


# ---------- Managing models (the Models panel) ----------


async def installed():
    """The installed models with their details: size, parameters, quantization."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
    except httpx.ConnectError:
        raise OllamaError(NOT_RUNNING) from None
    models = []
    for m in response.json().get("models", []):
        details = m.get("details") or {}
        models.append({
            "name": m["name"],
            "size": m.get("size", 0),  # bytes on disk
            "parameters": details.get("parameter_size", ""),  # like "3.2B"
            "quantization": details.get("quantization_level", ""),  # like "Q4_K_M"
            "family": details.get("family", ""),
        })
    return models


async def running():
    """The models in memory right now, with how much memory each one uses."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{OLLAMA_URL}/api/ps")
        return {m["name"]: m.get("size", 0) for m in response.json()["models"]}
    except (httpx.HTTPError, ValueError, KeyError):
        return {}


async def pull(model):
    """Download a model, as a stream of steps like Ollama sends them:
    {"status": "pulling 6a0746a1ec1a", "completed": 123, "total": 456}.

    If the caller stops reading (Cancel), the connection closes and Ollama
    stops downloading; what it already has is reused next time.
    """
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{OLLAMA_URL}/api/pull", json={"model": model, "stream": True}
            ) as response:
                if response.status_code != 200:
                    raise OllamaError(error_message(await response.aread()))
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    step = json.loads(line)
                    if "error" in step:
                        raise OllamaError(step["error"])
                    yield step
    except httpx.ConnectError:
        raise OllamaError(NOT_RUNNING) from None
    except (httpx.HTTPError, ValueError) as error:
        raise OllamaError(f"The download stopped: {error}") from None
    capabilities_cache.pop(model, None)  # a new version may do new things


async def delete(model):
    """Remove an installed model from the disk."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # DELETE with a body: httpx's request() allows it, .delete() doesn't.
            response = await client.request("DELETE", f"{OLLAMA_URL}/api/delete", json={"model": model})
    except httpx.ConnectError:
        raise OllamaError(NOT_RUNNING) from None
    if response.status_code != 200:
        raise OllamaError(error_message(response.content))
    capabilities_cache.pop(model, None)
