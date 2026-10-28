# Reverse-analysis fixtures

`crackme` and `crackme2` are small, intentionally simple Linux x86-64 ELF
programs used to test static analysis. Their C sources are included beside them.
They contain sample challenge passwords, not real credentials.

The tests read these files; they do not execute them. Keep the compiled fixtures
in version control because disassembly assertions depend on their exact code.
