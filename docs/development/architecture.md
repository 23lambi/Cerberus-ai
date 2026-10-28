# Project layout

[← README](../../README.md) · [Contributing](../../CONTRIBUTING.md)

```text
cerberus/                  Python application and engine connectors
  routes/                  FastAPI endpoints
static/                    HTML, CSS, JavaScript, and app icons
  vendor/                  Bundled frontend libraries and their licenses
tests/                     Python tests and frontend checks
  fixtures/                Small binary samples and their C source
docs/                      User guide, roadmap, and development notes
  assets/                  Images used in documentation
.github/                   CI workflows and contribution templates
desktop.py                 Desktop launcher
main.py                    FastAPI application
install-desktop.sh         Linux and macOS app installation
install-desktop.ps1        Windows app installation
requirements.txt           Pinned Python dependencies
```

The desktop launcher runs the FastAPI application in a background thread and
opens its interface with pywebview. The UI uses plain JavaScript with no build
step. SQLite stores chats, settings, memories, and document metadata.

Chat flows through `cerberus/ollama.py`, which delegates to Ollama or the
OpenAI-compatible connector in `cerberus/openai_api.py`. Managed server lifecycles
live in `engine.py` and `llamacpp.py`. API keys are handled separately by `keys.py`.

Keep user data, environments, credentials, model weights, and generated files
out of Git. Entry points stay at the repository root so installed desktop
shortcuts and existing commands continue to work.

The [historical development notes](history.md) describe earlier decisions and
may contain superseded status information. The [user guide](../guide.md) covers
current application behavior.
