"""Models → a model's Settings: context length and temperature."""
import asyncio
import json

import httpx
import pytest

from cerberus.core import model_settings
from cerberus.core.config import NUM_CTX
from cerberus.engines import ollama

LLAMA_3B = {"llama.block_count": 28, "llama.attention.head_count": 24, "llama.attention.head_count_kv": 8,
            "llama.attention.key_length": 128, "llama.attention.value_length": 128, "llama.context_length": 131072}


def test_memory_per_token_comes_from_the_models_build():
    # 28 layers x 8 KV heads x (128 + 128) x 2 bytes, as Ollama really used for llama3.2:3b.
    assert ollama.kv_bytes_per_token(LLAMA_3B) == 114688
    # Some models list KV heads per layer; the largest counts.
    gemma = {"gemma3.block_count": 34, "gemma3.attention.head_count_kv": [4, 4, 8],
             "gemma3.embedding_length": 2560, "gemma3.attention.head_count": 8}
    assert ollama.kv_bytes_per_token(gemma) == 34 * 8 * (320 + 320) * 2
    assert ollama.kv_bytes_per_token({}) is None


@pytest.mark.parametrize("ram,model_gb,longest,expected", [
    (29, 1.9, 131072, 32768),  # plenty of memory: suggestions stop at 32K
    (8, 1.9, 131072, 16384),  # a small laptop
    (8, 4.6, 131072, 4096),  # a bigger model on a small laptop
    (29, 11.7, 16384, 16384),  # never more than the model reads
    (None, 1.9, 131072, NUM_CTX),  # memory unknown: today's default
])
def test_suggestion_fits_this_computer(ram, model_gb, longest, expected):
    assert model_settings.suggest(ram, model_gb, 114688, longest) == expected


def test_settings_are_saved_per_model_and_defaults_stay_unsaved(db):
    assert model_settings.get("llama3.2:3b") == {"num_ctx": NUM_CTX, "temperature": None}
    model_settings.save("llama3.2:3b", 32768, 0.25)
    assert model_settings.get("llama3.2:3b") == {"num_ctx": 32768, "temperature": 0.25}
    assert model_settings.get("qwen3:4b")["num_ctx"] == NUM_CTX  # other models untouched
    model_settings.save("llama3.2:3b", NUM_CTX, None)
    assert model_settings.saved() == {}  # back to defaults: nothing stored


def test_damaged_saved_settings_fall_back_to_defaults(db):
    from cerberus.storage import database
    database.set_setting(model_settings.KEY, json.dumps({"m": {"num_ctx": 12345, "temperature": 9}}))
    assert model_settings.get("m") == {"num_ctx": NUM_CTX, "temperature": None}
    database.set_setting(model_settings.KEY, "not json")
    assert model_settings.get("m")["num_ctx"] == NUM_CTX


def test_routes_offer_only_what_the_model_reads(client, monkeypatch):
    async def facts(model):
        return {"capabilities": ["completion"], "context_length": 16384, "kv_bytes": 114688}
    async def installed():
        return [{"name": "small:3b", "size": 2 * 1024**3}]
    monkeypatch.setattr(ollama, "model_facts", facts)
    monkeypatch.setattr(ollama, "installed", installed)
    info = client.get("/models/settings", params={"name": "small:3b"}).json()
    assert [c["tokens"] for c in info["choices"]] == [4096, 8192, 16384]
    assert info["choices"][-1]["memory_gb"] == 1.8 and info["model_gb"] == 2.0
    assert client.put("/models/settings", json={"name": "small:3b", "num_ctx": 32768}).status_code == 422
    assert client.put("/models/settings", json={"name": "small:3b", "num_ctx": 12000}).status_code == 422
    assert client.put("/models/settings", json={"name": "small:3b", "num_ctx": 16384, "temperature": 3}).status_code == 422
    saved = client.put("/models/settings", json={"name": "small:3b", "num_ctx": 16384, "temperature": 0.4}).json()
    assert saved == {"num_ctx": 16384, "temperature": 0.4}


def test_ollama_gets_the_models_context_and_temperature(db, monkeypatch):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        done = {"message": {"content": "hi"}, "done": True, "eval_count": 1, "eval_duration": 1, "prompt_eval_count": 5}
        return httpx.Response(200, content=(json.dumps(done) + "\n").encode())

    real_client = httpx.AsyncClient
    monkeypatch.setattr(ollama.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    model_settings.save("small:3b", 32768, 0.3)

    async def run(**kwargs):
        return [event async for event in ollama.stream_events("small:3b", [{"role": "user", "content": "Hi"}], **kwargs)]

    events = asyncio.run(run())
    assert sent[-1]["options"]["num_ctx"] == 32768 and sent[-1]["options"]["temperature"] == 0.3
    assert events[-1][1]["num_ctx"] == 32768  # the stats under the answer say so too
    asyncio.run(run(temperature=0))  # background jobs ask for an exact temperature
    assert sent[-1]["options"]["temperature"] == 0
