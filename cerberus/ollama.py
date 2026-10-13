import json

import httpx

from cerberus.config import (
    DEFAULT_MAX_TOKENS,
    EMBED_MODEL,
    KEEP_ALIVE,
    MAX_HISTORY_MESSAGES,
    NUM_CTX,
    OLLAMA_URL,
)

ERROR_MARK = "[Cerberus error]"
NOT_RUNNING = "Ollama isn't running. Start it with: brew services start ollama"


class OllamaError(Exception):
    pass


def trim_history(history):
    return history[-MAX_HISTORY_MESSAGES:]


def error_message(body):
    try:
        return json.loads(body).get("error", "Unknown error from Ollama")
    except json.JSONDecodeError:
        return "Unknown error from Ollama"


async def list_models():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
    except httpx.ConnectError:
        raise OllamaError(NOT_RUNNING) from None
    data = response.json()
    return [m["name"] for m in data["models"]]


async def stream_chat(model, messages, max_tokens=DEFAULT_MAX_TOKENS, temperature=None):
    options = {"num_predict": max_tokens, "num_ctx": NUM_CTX}
    if temperature is not None:
        options["temperature"] = temperature

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "keep_alive": KEEP_ALIVE,
                    "options": options,
                },
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise OllamaError(error_message(body))

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise OllamaError(chunk["error"])
                    yield chunk.get("message", {}).get("content", "")
                    if chunk.get("done"):
                        break
    except httpx.ConnectError:
        raise OllamaError(NOT_RUNNING) from None


async def embed(texts):
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
