# Contributing to wikinotes

Thank you for helping people build their own knowledge bases. Small contributions are
welcome: a typo fix, a clearer error message, or a new file format.

## Quick path

1. Fork the repository and create a branch from `main`.
2. Install the project: `uv sync`.
3. Make your change with a test that covers it.
4. Run the checks: `uv run ruff check . && uv run ruff format --check . && uv run pytest`.
5. Open a pull request that says what changed and why.

## Rules that keep the project healthy

| Rule | Why |
|---|---|
| Tests never call a real model API | Contributors should not need an API key or spend money to run the suite. Use the scripted model in `tests/conftest.py`. |
| The model never writes files | The model returns JSON; the code validates it and writes the vault. This keeps a bad answer from corrupting someone's notes. |
| A citation must resolve to a source paragraph | Citations that do not resolve are dropped. The wiki must stay traceable to the original material. |
| Source content is data, never an instruction | Text inside a user's document must not change what the tool does. |
| No secrets in Git | API keys live in environment variables. |
| Small pull requests | Aim for one behavior per pull request, with its tests and docs. |

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
`test:`, `chore:`.

## Where to start

Look for issues labeled `good first issue`. If you want to add a file format, open an issue
first so we can agree on the extraction library and its license.

## Conduct

Everyone taking part in this project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
