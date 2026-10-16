# Tests for the small helper functions in keeper.py.
# A test is a function whose name starts with "test_". pytest finds and
# runs them all. Inside, "assert" checks that something is true; if it
# isn't, the test fails and pytest shows you both values.

from cerberus import keeper


def test_wants_to_save_finds_the_fact():
    assert keeper.wants_to_save("Remember that I like tea.") == "I like tea"
    assert keeper.wants_to_save("please remember: my cat is Luna") == "my cat is Luna"


def test_wants_to_save_ignores_normal_messages():
    assert keeper.wants_to_save("Do you remember my cat?") is None
    assert keeper.wants_to_save("hello") is None


def test_cosine():
    assert keeper.cosine([1, 0], [1, 0]) == 1.0  # same direction
    assert keeper.cosine([1, 0], [0, 1]) == 0.0  # unrelated
    assert keeper.cosine([0, 0], [1, 1]) == 0.0  # no crash on an empty vector


def test_words_skips_short_and_stop_words():
    assert keeper.words("What is the Python language about?") == {"python", "language"}


def test_split_text_short_text_is_one_piece():
    assert keeper.split_text("Just a short note.") == ["Just a short note."]


def test_split_text_long_text():
    text = "This is one sentence. " * 200  # about 4400 characters
    pieces = keeper.split_text(text, size=800, overlap=100)

    assert len(pieces) > 1
    assert all(len(piece) <= 800 for piece in pieces)
    # It prefers to cut after a sentence, so every piece ends with a dot.
    assert all(piece.endswith(".") for piece in pieces)
