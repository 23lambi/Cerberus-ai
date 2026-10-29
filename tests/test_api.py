# Tests for the URLs, the way the browser uses them. "client" sends fake
# requests straight into the app (no real server), and "fake" is the fake
# Ollama, so we can check what the model was sent.

import json

from cerberus.storage import database


def chat_body(text, model="small:3b", chat_id=None, think=False):
    # The JSON the page sends to /chat.
    return {
        "model": model,
        "chat_id": chat_id,
        "think": think,
        "messages": [{"role": "user", "content": text}],
    }


def events(response):
    # /chat answers with NDJSON: one JSON object per line.
    return [json.loads(line) for line in response.text.splitlines()]


def test_models_hides_embedding_models(client):
    data = client.get("/models").json()
    assert "embed-text" not in data["models"]
    assert data["thinking"] == ["thinker:4b"]
    assert data["vision"] == ["eyes:4b"]


def test_chat_streams_the_answer_and_saves_it(client):
    chat_id = client.post("/chats", json={}).json()["id"]

    response = client.post("/chat", json=chat_body("Hi there", chat_id=chat_id))

    kinds = [event["type"] for event in events(response)]
    assert kinds == ["content", "stats", "done"]
    saved = database.get_chat(chat_id)["messages"]
    assert [m["content"] for m in saved] == ["Hi there", "Hello from the fake model"]


def test_one_message_loads_the_full_chat_only_once(client, monkeypatch):
    # get_chat reads every message, images included. Only the check for a
    # stale history needs that; the rest only needs the chat's project.
    project = database.create_project("Project")["id"]
    chat_id = database.create_chat("Chat", project)["id"]
    loads = []
    real_get_chat = database.get_chat

    def counting_get_chat(chat_id):
        loads.append(chat_id)
        return real_get_chat(chat_id)

    monkeypatch.setattr(database, "get_chat", counting_get_chat)
    client.post("/chat", json=chat_body("Hi there", chat_id=chat_id))
    assert loads == [chat_id]


def test_memory_goes_in_the_last_message_not_the_system_prompt(client, fake):
    # This is the speed fix: if the memory were in the system prompt, the
    # start of the prompt would change every time and Ollama's cache
    # could not be reused.
    database.add_memory("The user's favourite language is Rust", None)

    client.post("/chat", json=chat_body("Which programming language is my favourite?"))

    sent = fake.calls[-1]["messages"]
    assert "Rust" not in sent[0]["content"]  # the system prompt
    assert "Rust" in sent[-1]["content"]  # the user's newest message


def test_think_only_for_models_that_can(client, fake):
    client.post("/chat", json=chat_body("Hi", model="small:3b", think=True))
    assert fake.calls[-1]["think"] is False

    response = client.post("/chat", json=chat_body("Hi", model="thinker:4b", think=True))
    assert fake.calls[-1]["think"] is True
    assert events(response)[0] == {"type": "thinking", "text": "Let me think..."}


def test_title_uses_the_helper_only_when_it_is_on(client, fake):
    chat_id = client.post("/chats", json={}).json()["id"]
    client.post("/chat", json=chat_body("Hi", model="big:8b", chat_id=chat_id))

    # Helper off: the chat model writes the title.
    client.post(f"/chats/{chat_id}/title", json={"model": "big:8b"})
    assert fake.calls[-1]["model"] == "big:8b"

    # Helper on: the helper model writes it.
    client.put("/settings", json={"helper_on": "yes", "helper_model": "small:3b"})
    client.post(f"/chats/{chat_id}/title", json={"model": "big:8b"})
    assert fake.calls[-1]["model"] == "small:3b"


def test_switching_models_frees_the_others(client, fake):
    fake.loaded = ["big:8b", "small:3b", "thinker:4b", "nomic-embed-text:latest"]
    client.put("/settings", json={"helper_on": "yes", "helper_model": "thinker:4b"})

    response = client.post("/models/keep", json={"model": "small:3b"})

    # Kept: the chosen model, the Helper and the embedding model.
    assert response.json()["unloaded"] == ["big:8b"]
    assert fake.unloaded == ["big:8b"]


def test_choosing_none_frees_every_model(client, fake):
    fake.loaded = ["big:8b", "nomic-embed-text:latest"]
    response = client.post("/models/keep", json={"model": ""})
    assert response.json()["unloaded"] == ["big:8b", "nomic-embed-text:latest"]


def test_rename_chat(client):
    chat_id = client.post("/chats", json={}).json()["id"]

    assert client.put(f"/chats/{chat_id}", json={"title": "  Renamed  "}).json()["title"] == "Renamed"
    assert client.put(f"/chats/{chat_id}", json={"title": "   "}).status_code == 400
    assert client.put("/chats/999", json={"title": "x"}).status_code == 404


def test_images_go_only_to_models_that_can_see(client, fake):
    chat_id = client.post("/chats", json={}).json()["id"]
    body = chat_body("What is in this picture?", model="eyes:4b", chat_id=chat_id)
    body["messages"][0]["images"] = ["aGVsbG8="]  # a tiny bit of base64

    client.post("/chat", json=body)
    assert fake.calls[-1]["messages"][-1]["images"] == ["aGVsbG8="]
    # Saved with the question, so it's still there when the chat is reopened.
    assert database.get_chat(chat_id)["messages"][0]["images"] == ["aGVsbG8="]

    # A model that can't see gets only the text.
    body["model"] = "small:3b"
    body["chat_id"] = None
    client.post("/chat", json=body)
    assert "images" not in fake.calls[-1]["messages"][-1]


# ---------- Eyes: a vision model describes images for the chat model ----------


def image_body(text, model, chat_id=None):
    body = chat_body(text, model=model, chat_id=chat_id)
    body["messages"][0]["images"] = ["aGVsbG8="]
    return body


def test_eyes_describe_images_for_a_model_that_cannot_see(client, fake):
    client.put("/settings", json={"eyes_on": "yes", "eyes_model": "eyes:4b"})
    chat_id = client.post("/chats", json={}).json()["id"]

    response = client.post("/chat", json=image_body("What is this?", "small:3b", chat_id))

    # First the vision model looks, then the chat model answers from its words.
    look, answer = fake.calls[-2], fake.calls[-1]
    assert look["model"] == "eyes:4b"
    assert look["messages"][-1]["images"] == ["aGVsbG8="]
    assert answer["model"] == "small:3b"
    assert "images" not in answer["messages"][-1]
    assert "I see a red square" in answer["messages"][-1]["content"]

    # The page gets what was seen first, and it's saved apart from the question.
    assert events(response)[0] == {"type": "seen", "text": "I see a red square", "model": "eyes:4b"}
    saved = database.get_chat(chat_id)["messages"][0]
    assert saved["content"] == "What is this?"
    assert saved["seen"] == "I see a red square"


def test_eyes_never_look_at_the_same_picture_twice(client, fake):
    client.put("/settings", json={"eyes_on": "yes", "eyes_model": "eyes:4b"})
    body = image_body("What is this?", "small:3b")
    body["messages"][0]["seen"] = "I see a red square"  # described last time

    client.post("/chat", json=body)

    assert [call["model"] for call in fake.calls] == ["small:3b"]


def test_without_eyes_the_model_is_told_it_cannot_see(client, fake):
    client.post("/chat", json=image_body("What is this?", "small:3b"))

    assert "can't see them" in fake.calls[-1]["messages"][-1]["content"]


def test_settings_show_every_built_in_prompt(client):
    prompts = client.get("/settings/prompts").json()["prompts"]
    names = [prompt["name"] for prompt in prompts]
    assert "Guard" in names and "Reverse: skill" in names
    # Every prompt has text and an explanation; none is empty by mistake.
    assert all(prompt["text"] and prompt["about"] for prompt in prompts)


def test_unchanged_personality_follows_improved_defaults(client):
    from cerberus.chat.prompts import OLD_SYSTEM_PROMPTS, SYSTEM_PROMPT
    from cerberus.storage import database
    # Settings → Save used to store the old default word for word.
    database.set_setting("system_prompt", OLD_SYSTEM_PROMPTS[0])
    assert client.get("/settings").json()["system_prompt"] == SYSTEM_PROMPT.strip()
    # Saving it unchanged now stores nothing, so it keeps following the default.
    client.put("/settings", json={"system_prompt": SYSTEM_PROMPT.strip()})
    assert database.get_setting("system_prompt") is None
    # A real change is kept exactly.
    client.put("/settings", json={"system_prompt": "You are a pirate."})
    assert client.get("/settings").json()["system_prompt"] == "You are a pirate."
