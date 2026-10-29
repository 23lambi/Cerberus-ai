# Other AI engines: anything that speaks the "OpenAI-compatible" language.
#
# OpenAI's chat format became a common standard, so one connector reaches
# many engines: Hugging Face's cloud, LM Studio, Jan, llama.cpp's server,
# OpenAI, Groq, OpenRouter... They differ only in the address and whether
# they need a key. ollama.py sends each request here when one of them is
# chosen as the engine, so the rest of Cerberus doesn't notice which runs.
#
# This file translates both ways: Cerberus's messages into OpenAI's format
# (pictures, tool calls), and the streamed answer back into the same
# events ollama.stream_events gives: ("content", text), ("thinking", text),
# ("tool_calls", list), ("stats", dict).

import ipaddress
import json
import time
from urllib.parse import urlsplit

import httpx

from cerberus.storage import database, keys
from cerberus.chat.budget import ContextTooLarge, fit

# The engines to choose from. "cloud": messages leave this computer.
PRESETS = {
    "huggingface": {"name": "Hugging Face (cloud)", "url": "https://router.huggingface.co/v1", "key": True,
                    "key_help": "A token from huggingface.co/settings/tokens (Read access)."},
    "lmstudio": {"name": "LM Studio", "url": "http://127.0.0.1:1234/v1", "key": False,
                 "key_help": "Start LM Studio's server (Developer tab) and load a model."},
    "jan": {"name": "Jan", "url": "http://127.0.0.1:1337/v1", "key": False,
            "key_help": "Turn on Jan's Local API Server in its settings."},
    "llamacpp": {"name": "llama.cpp server", "url": "http://127.0.0.1:8080/v1", "key": False,
                 "key_help": "Run: llama-server -m your-model.gguf --jinja (Hugging Face GGUF files)."},
    "openai": {"name": "OpenAI", "url": "https://api.openai.com/v1", "key": True,
               "key_help": "A key from platform.openai.com (paid)."},
    "groq": {"name": "Groq", "url": "https://api.groq.com/openai/v1", "key": True,
             "key_help": "A key from console.groq.com (has a free tier)."},
    "openrouter": {"name": "OpenRouter", "url": "https://openrouter.ai/api/v1", "key": True,
                   "key_help": "A key from openrouter.ai (many models, some free)."},
    "custom": {"name": "Other (OpenAI-compatible)", "url": "", "key": False,
               "key_help": "Any server that speaks the OpenAI API. Add a key if it needs one."},
}


class EngineError(Exception):
    pass


def is_cloud(url):
    """True when the address is on the internet, not this computer or home network."""
    host = urlsplit(url).hostname or ""
    if host in ("localhost", ""):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True  # a name like api.openai.com: on the internet
    return not (address.is_loopback or address.is_private)


def current():
    """The chosen OpenAI-compatible engine: its preset, address and key."""
    preset = database.get_setting("openai_preset") or "custom"
    info = PRESETS.get(preset, PRESETS["custom"])
    url = (database.get_setting("openai_url") or info["url"]).rstrip("/")
    return {
        "preset": preset,
        "name": info["name"],
        "url": url,
        "key": keys.get("openai_key"),
        "cloud": is_cloud(url),
    }


def headers(engine):
    return {"Authorization": f"Bearer {engine['key']}"} if engine["key"] else {}


def error_text(engine, response_body, status):
    """The engine's own error message, as plain words."""
    if status == 401:
        return f"{engine['name']} refused the API key. Check it in Setup."
    try:
        error = json.loads(response_body).get("error")
        message = error.get("message") if isinstance(error, dict) else error
    except (ValueError, AttributeError):
        message = None
    return message or f"{engine['name']} answered with error {status}."


# ---------- Models ----------


async def list_models(engine=None, timeout=15):
    """The model names this engine offers (GET /models)."""
    engine = engine or current()
    if not engine["url"]:
        raise EngineError("Choose the engine's address in Setup.")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(engine["url"] + "/models", headers=headers(engine))
    except httpx.HTTPError:
        raise EngineError(f"{engine['name']} can't be reached at {engine['url']}. Is it running?") from None
    if response.status_code != 200:
        raise EngineError(error_text(engine, response.content, response.status_code))
    try:
        return sorted(model["id"] for model in response.json()["data"])
    except (ValueError, KeyError, TypeError):
        raise EngineError(f"{engine['name']} sent a model list Cerberus can't read.") from None


# ---------- Messages: Cerberus's format -> OpenAI's ----------


def to_openai(messages):
    """Translate messages. Pictures become image parts; tool calls get ids.

    OpenAI wants every tool call to have an id, and every tool result to
    name the id it answers. Ollama doesn't use ids, so we make them: the
    results follow their calls in the same order.
    """
    result = []
    waiting_ids = []  # ids of tool calls whose results come next
    for message in messages:
        role = message["role"]
        if role == "user" and message.get("images"):
            parts = [{"type": "text", "text": message.get("content", "")}]
            for image in message["images"]:
                parts.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image}})
            result.append({"role": "user", "content": parts})
        elif role == "assistant" and message.get("tool_calls"):
            calls = []
            for number, call in enumerate(message["tool_calls"]):
                call_id = call.get("id") or f"call_{len(result)}_{number}"
                arguments = call["function"].get("arguments") or {}
                calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": call["function"]["name"],
                        # OpenAI wants the arguments as JSON text, not an object.
                        "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
                    },
                })
                waiting_ids.append(call_id)
            result.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
        elif role == "tool":
            call_id = waiting_ids.pop(0) if waiting_ids else "call_unknown"
            result.append({"role": "tool", "tool_call_id": call_id, "content": message["content"]})
        else:
            result.append({"role": role, "content": message.get("content", "")})
    return result


# ---------- Streaming an answer ----------


def finished_calls(pieces):
    """Tool calls collected from their pieces, in Cerberus's format."""
    calls = []
    for index in sorted(pieces):
        piece = pieces[index]
        text = piece["arguments"]
        try:
            arguments = json.loads(text) if text else {}
        except ValueError:
            arguments = text  # tools.run_tool explains broken JSON to the model
        calls.append({"id": piece["id"], "function": {"name": piece["name"], "arguments": arguments}})
    return calls


async def stream_events(model, messages, max_tokens, temperature=None, think=False, tools=None, num_ctx=8192):
    """Like ollama.stream_events, for an OpenAI-compatible engine."""
    engine = current()
    try:
        messages = fit(messages, max_tokens, tools, num_ctx)
    except ContextTooLarge as error:
        raise EngineError(str(error)) from None
    body = {
        "model": model,
        "messages": to_openai(messages),
        "stream": True,
        "max_tokens": max_tokens,
        # Ask for the token counts at the end (for the line under an answer).
        "stream_options": {"include_usage": True},
    }
    if temperature is not None:
        body["temperature"] = temperature
    if tools:
        body["tools"] = tools  # Cerberus's tool definitions are already OpenAI's format

    started = time.monotonic()
    pieces = {}  # tool calls arrive in pieces: {index: {"id", "name", "arguments"}}
    finish = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=None)) as client:
            async with client.stream("POST", engine["url"] + "/chat/completions",
                                     json=body, headers=headers(engine)) as response:
                if response.status_code != 200:
                    raise EngineError(error_text(engine, await response.aread(), response.status_code))
                # Server-sent events: lines like "data: {...}", then "data: [DONE]".
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if chunk.get("error"):
                        raise EngineError(error_text(engine, data, 500))
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        # Thinking models send their reasoning separately;
                        # engines name it differently.
                        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                        if reasoning:
                            yield "thinking", reasoning
                        if delta.get("content"):
                            yield "content", delta["content"]
                        for call in delta.get("tool_calls") or []:
                            piece = pieces.setdefault(call.get("index", 0), {"id": "", "name": "", "arguments": ""})
                            piece["id"] = call.get("id") or piece["id"]
                            function = call.get("function") or {}
                            piece["name"] = function.get("name") or piece["name"]
                            piece["arguments"] += function.get("arguments") or ""
                        finish = choice.get("finish_reason") or finish
                    usage = chunk.get("usage")
                    if usage:
                        tokens = usage.get("completion_tokens", 0)
                        if pieces:
                            yield "tool_calls", finished_calls(pieces)
                            pieces = {}
                        yield "stats", {
                            "tokens": tokens,
                            "seconds": time.monotonic() - started,
                            "context": usage.get("prompt_tokens", 0) + tokens,
                            "num_ctx": num_ctx,
                            "cut_off": finish == "length",
                        }
    except httpx.HTTPError:
        raise EngineError(f"{engine['name']} can't be reached at {engine['url']}. Is it running?") from None
    except ValueError as error:
        raise EngineError(f"{engine['name']}'s answer could not be read: {error}") from None
    # Engines that send no token counts: still hand over the tool calls.
    if pieces:
        yield "tool_calls", finished_calls(pieces)
