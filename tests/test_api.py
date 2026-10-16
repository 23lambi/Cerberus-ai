# Tests for the URLs, the way the browser uses them. "client" sends fake
# requests straight into the app (no real server), and "fake" is the fake
# Ollama, so we can check what the model was sent.

import json

from cerberus import database


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


def test_chat_streams_the_answer_and_saves_it(client):
    chat_id = client.post("/chats", json={}).json()["id"]

    response = client.post("/chat", json=chat_body("Hi there", chat_id=chat_id))

    kinds = [event["type"] for event in events(response)]
    assert kinds == ["content", "stats"]
    saved = database.get_chat(chat_id)["messages"]
    assert [m["content"] for m in saved] == ["Hi there", "Hello from the fake model"]


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


def test_rename_chat(client):
    chat_id = client.post("/chats", json={}).json()["id"]

    assert client.put(f"/chats/{chat_id}", json={"title": "  Renamed  "}).json()["title"] == "Renamed"
    assert client.put(f"/chats/{chat_id}", json={"title": "   "}).status_code == 400
    assert client.put("/chats/999", json={"title": "x"}).status_code == 404
