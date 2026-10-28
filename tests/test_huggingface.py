# Tests for getting models from Hugging Face (cerberus/huggingface.py).
# huggingface.co is faked: these tests never go online.

import asyncio

import pytest

from cerberus import huggingface as hf


def test_versions_are_read_from_the_file_names():
    files = [
        ("Model-7B-Q4_K_M.gguf", 4_700),
        ("Model-7B-Q2_K.gguf", 3_000),
        ("Q8_0/Model-7B-Q8_0-00001-of-00002.gguf", 5_000),  # a big model split in two
        ("Q8_0/Model-7B-Q8_0-00002-of-00002.gguf", 3_100),
        ("mmproj-Model-F16.gguf", 600),  # the vision part, not a version
        ("README.md", 10),
        ("model-bf16.gguf", 15_000),
    ]
    assert hf.versions_of(files) == [
        {"version": "Q2_K", "size": 3_000},
        {"version": "Q4_K_M", "size": 4_700},
        {"version": "Q8_0", "size": 8_100},
        {"version": "BF16", "size": 15_000},
    ]


def fake_api(monkeypatch, answers):
    asked = []

    async def get(url, params=None):
        asked.append((url, params))
        return answers[url]

    monkeypatch.setattr(hf, "get", get)
    return asked


def test_search_keeps_what_the_panel_needs(monkeypatch):
    asked = fake_api(monkeypatch, {hf.API: [
        {"id": "Qwen/Qwen2.5-7B-Instruct-GGUF", "downloads": 647061, "likes": 204, "pipeline_tag": "text-generation"},
        {"id": "unsloth/Qwen2.5-VL-7B-Instruct-GGUF", "downloads": 9, "pipeline_tag": "image-text-to-text"},
    ]})
    found = asyncio.run(hf.search("qwen"))
    assert found[0] == {"repo": "Qwen/Qwen2.5-7B-Instruct-GGUF", "downloads": 647061, "likes": 204,
                        "vision": False, "embedding": False}
    assert found[1]["vision"] is True
    assert asked[0][1]["filter"] == "gguf"  # only models Ollama can run


def test_versions_suggest_q4_k_m_and_give_the_ollama_name(monkeypatch):
    repo = "bartowski/Qwen2.5-7B-Instruct-GGUF"
    fake_api(monkeypatch, {f"{hf.API}/{repo}": {
        "gated": False, "cardData": {"license": "apache-2.0"},
        "siblings": [{"rfilename": "Qwen2.5-7B-Instruct-Q4_K_M.gguf", "size": 4_700}],
    }})
    data = asyncio.run(hf.versions(repo))
    assert data["suggested"] == "Q4_K_M" and data["license"] == "apache-2.0" and not data["gated"]
    assert data["versions"][0]["ollama_name"] == "hf.co/bartowski/Qwen2.5-7B-Instruct-GGUF:Q4_K_M"


def test_gated_models_are_marked(monkeypatch):
    repo = "meta-llama/Llama-3.2-3B-Instruct-GGUF"
    fake_api(monkeypatch, {f"{hf.API}/{repo}": {"gated": "manual", "siblings": []}})
    assert asyncio.run(hf.versions(repo))["gated"] is True


@pytest.mark.parametrize("repo", ["", "no-slash", "../../etc/passwd", "a/b/c", "user/model?x=1"])
def test_strange_repo_names_are_refused_before_asking(client, monkeypatch, repo):
    asked = fake_api(monkeypatch, {})
    response = client.get("/models/huggingface/versions", params={"repo": repo})
    assert response.status_code == 422
    assert asked == []


def test_huggingface_offline(client, monkeypatch):
    async def offline(url, params=None):
        raise hf.HuggingFaceError("huggingface.co could not be reached. Are you online?")

    monkeypatch.setattr(hf, "get", offline)
    response = client.get("/models/huggingface", params={"q": "qwen"})
    assert response.status_code == 502 and "online" in response.json()["detail"]


# ---------- Browsing without searching ----------


def test_browse_asks_for_one_category_in_the_chosen_order(client, monkeypatch):
    asked = fake_api(monkeypatch, {hf.API: [{"id": "a/b-GGUF", "pipeline_tag": "feature-extraction"}]})
    monkeypatch.setattr(hf, "browse_cache", {})
    found = client.get("/models/huggingface", params={"order": "trending", "category": "embedding"}).json()["models"]
    assert found[0]["embedding"] is True
    params = asked[0][1]
    assert params["sort"] == "trendingScore" and params["pipeline_tag"] == "feature-extraction"
    assert params["filter"] == "gguf"


def test_unknown_lists_fall_back_to_popular_chat(monkeypatch):
    asked = fake_api(monkeypatch, {hf.API: []})
    monkeypatch.setattr(hf, "browse_cache", {})
    asyncio.run(hf.browse("newest", "all"))  # no such list: no spam, no image models
    assert asked[0][1]["sort"] == "downloads" and asked[0][1]["pipeline_tag"] == "text-generation"


def test_browse_lists_are_kept_for_an_hour(monkeypatch):
    asked = fake_api(monkeypatch, {hf.API: []})
    clock = [500.0]
    monkeypatch.setattr(hf, "browse_cache", {})
    monkeypatch.setattr(hf.time, "monotonic", lambda: clock[0])
    asyncio.run(hf.browse("popular", "chat"))
    asyncio.run(hf.browse("popular", "chat"))
    asyncio.run(hf.browse("popular", "vision"))  # another list: asked separately
    assert len(asked) == 2
    clock[0] += 3601
    asyncio.run(hf.browse("popular", "chat"))
    assert len(asked) == 3
