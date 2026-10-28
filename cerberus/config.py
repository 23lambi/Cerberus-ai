# All the settings that change how Cerberus behaves, in one place.
# Names in CAPITALS are constants: Python lets you change them, but the
# convention says "don't, they are settings".

# ---------- Ollama ----------

OLLAMA_URL = "http://localhost:11434"  # where the Ollama server listens
KEEP_ALIVE = "30m"  # how long Ollama keeps a model in memory after the last use

# ---------- Chat history ----------

NUM_CTX = 8192  # the context window: how many tokens the model can see at once
SUMMARY_EVERY = 6  # redo the summary of old messages after this many new ones
MAX_HISTORY_MESSAGES = 20  # only the newest 20 messages are sent to the model

# ---------- Answer lengths (in tokens, about 3/4 of a word each) ----------

DEFAULT_MAX_TOKENS = 600  # a normal answer
THINK_MAX_TOKENS = 4000  # extra room for reasoning when Think is on
HEAD_MAX_TOKENS = 400  # Deep think: the draft and the review
JUDGE_MAX_TOKENS = 600  # Deep think: the final answer

DB_PATH = "cerberus.db"  # the SQLite file with all chats, memories and settings

# ---------- Guard ----------

GUARD_USE_MODEL = True  # False = the Guard only uses its rules, never asks the model

# ---------- Memory (the Keeper) ----------

EMBED_MODEL = "nomic-embed-text"  # the model that turns text into vectors
# A score is how close two texts are in meaning, from 0 (unrelated) to 1 (same).
# Normal chat: only a few, very close matches.
MEMORY_RESULTS = 3
MEMORY_MIN_SCORE = 0.55
# Memory mode (the user asks about the past): more results, looser matches.
KEEPER_RESULTS = 5
KEEPER_MIN_SCORE = 0.4

# ---------- Documents ----------

DOCUMENTS_DIR = "documents"  # uploaded files are kept in this folder
MAX_UPLOAD_MB = 20
CHUNK_SIZE = 800  # documents are cut into pieces of about 800 characters
CHUNK_OVERLAP = 100  # neighbouring pieces share 100 characters, so no sentence is lost at a cut
DOC_RESULTS = 3
DOC_MIN_SCORE = 0.6
KEEPER_DOC_RESULTS = 4
KEEPER_DOC_MIN_SCORE = 0.45
CHAT_SEARCH_RESULTS = 4  # memory mode: how many old chat messages to show the model

# ---------- Projects ----------

PROJECT_NOTES_MAX_CHARS = 6000  # the most project notes that go into one prompt

# ---------- Web search (SearXNG) ----------

WEB_RESULTS = 5  # how many search results to keep
WEB_SEARCH_TIMEOUT = 15  # seconds; SearXNG waits for several engines
