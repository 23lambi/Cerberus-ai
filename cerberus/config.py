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
WEB_PAGE_TIMEOUT = 10  # seconds for one page, redirects included
MAX_PAGE_BYTES = 2 * 1024 * 1024  # stop downloading a page after 2 MB
MAX_REDIRECTS = 5
PAGE_TEXT_CHARS = 40000  # the most text kept from one page
WEB_PAGES = 3  # how many of the search results are read
# Web pages are cut finer than documents. On a CPU the model reads only
# about 75 tokens a second, so every character it gets costs time: small
# pieces mean the 4 chosen ones are mostly what matters (measured: about
# 2000 instead of 3200 characters, several seconds less per answer).
WEB_PIECE_CHARS = 500
WEB_PIECE_OVERLAP = 60
WEB_PIECES_PER_PAGE = 4  # round 1, by words: the best pieces of each page
WEB_PIECES = 4  # round 2, by meaning: the pieces the model gets
