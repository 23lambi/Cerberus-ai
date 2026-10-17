# The Eyes feature: a vision model looks at the user's images and writes
# down what it sees. A chat model that can't see then answers from that
# text, like a friend describing a photo to you over the phone.
#
# So you can chat with your favourite model (even one without vision) and
# still ask about pictures.

from cerberus.ollama import OllamaError, stream_chat
from cerberus.prompts import EYES_PROMPT

EYES_MAX_TOKENS = 500  # a description, not an essay


async def describe(model, images, question):
    """What the images show, as text. "" when the vision model fails."""
    # The question goes along, so the description focuses on what matters
    # (a screenshot of an error vs. a photo of a cat need different details).
    messages = [
        {"role": "user", "content": EYES_PROMPT.format(question=question), "images": images}
    ]
    text = ""
    try:
        async for piece in stream_chat(model, messages, EYES_MAX_TOKENS, temperature=0.2):
            text += piece
    except OllamaError:
        return ""  # the chat model will then be told it can't see the images
    return text.strip()
