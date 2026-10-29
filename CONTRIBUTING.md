# Contributing

Cerberus is in active development. Bug reports, usability feedback, and focused
pull requests are welcome.

## Try it and report a problem

Follow the [README](README.md#build-from-source), then open a
[bug report](https://github.com/23lambi/Cerberus-ai/issues/new/choose).
Include your operating system, engine, model, and steps to reproduce the issue.
Use sample data in screenshots and remove keys or private content from logs.
For vulnerabilities, follow the [security policy](SECURITY.md).

## Make a change

1. Fork and clone the repository, then create a branch for your change.
2. Install Python 3.14 and the dependencies in `requirements.txt`.
3. Keep the change focused and follow the existing Python and JavaScript style.
4. Run the checks and open a pull request explaining the behavior and validation.

```bash
venv/bin/python -m pytest -q
node tests/frontend.test.cjs
```

Tests use temporary databases and fake AI responses. You do not need API keys
or a running model. Desktop behavior still needs manual testing; include your
platform and screenshots when changing the interface.

## Changing a prompt

Prompts live in `cerberus/chat/prompts.py`. Small models easily make things up,
so after changing one, run the honesty check against a local Ollama model:

```bash
venv/bin/python scripts/check_prompts.py --compare --runs 5
```

It asks questions that tempt the model to invent (that it watches the computer,
remembers yesterday, knows your name) and counts invented answers. Mention the
before and after numbers in your pull request. When you change the default
personality, move the previous text into `OLD_SYSTEM_PROMPTS`, so people who
never customized it get the new one.

See [architecture](docs/development/architecture.md) for the file layout and
[roadmap](docs/roadmap.md) for areas to improve. Contributions to project-owned
code are provided under the [Apache License 2.0](LICENSE). Bundled libraries retain
their own licenses.
