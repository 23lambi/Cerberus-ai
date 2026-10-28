# Security

## Report a vulnerability

Use [GitHub's private vulnerability reporting](https://github.com/23lambi/Cerberus-ai/security/advisories/new).
Include the affected commit, reproduction steps, and impact using sample data.
Do not include API keys or personal documents.

If private reporting is unavailable, open an issue asking the maintainer for a
private contact method without sharing vulnerability details.

## Deployment scope

Cerberus is a desktop application for a single user. Its local server binds to
`127.0.0.1`; it is not designed to be exposed directly to the internet or used
as a shared, authenticated service.

Cloud engines receive the messages and context sent to them. Web search contacts
external services. API keys live separately from the chat database and are
excluded from application backups.

Security fixes target the current main branch. Older snapshots are not maintained
as separate supported releases.
