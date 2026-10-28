# Tests for the Guard's rules. No model is needed: the rules are just
# regular expressions, so these tests run in milliseconds.

import asyncio

import pytest

from cerberus.chat import guard


# parametrize runs the same test once per value in the list, so one
# function checks many messages. Each run shows up separately in pytest.
@pytest.mark.parametrize(
    "message",
    [
        "Remember that I like tea",
        "What did we decide about the database?",
        "What do you know about me?",
        "Look in my notes",
        "Is it in the pdf?",
    ],
)
def test_rules_find_memory_questions(message):
    assert guard.by_rules(message) == "memory"


@pytest.mark.parametrize("message", ["How do loops work?", "Write a poem", "hello"])
def test_rules_leave_normal_chat_alone(message):
    assert guard.by_rules(message) is None


def test_short_replies_stay_in_chat():
    # route() is async, so we run it with asyncio.run().
    assert asyncio.run(guard.route("ok go on", "any-model")) == ("chat", "rules")


def test_without_a_model_the_default_is_chat():
    result = asyncio.run(guard.route("Explain how a compiler works", "any-model", use_model=False))
    assert result == ("chat", "default")
