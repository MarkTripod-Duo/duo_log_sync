# Contributing

Thanks for your interest in improving Duo Log Sync! This is an independent fork;
contributions are welcome here (not against `duosecurity/duo_log_sync`).

## Development setup

This project uses [uv](https://docs.astral.sh/uv/) for packaging and dependency
management.

```bash
# Install uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync --dev        # create the venv and install runtime + dev dependencies
```

## Running tests, lint, and formatting

```bash
uv run pytest                                   # run the test suite
uv run pytest --cov=duologsync --cov-report=term-missing   # with coverage
uv run ruff check .                             # lint
uv run ruff format .                            # auto-format
uv run ruff format --check .                    # verify formatting (CI does this)
```

### Coverage gate

CI enforces **`--cov-fail-under=90`** — the test job fails if total coverage
drops below 90%. New code should ship with tests that keep coverage at or above
that line. Run the coverage command above before opening a PR.

## Branch and commit conventions

- Branch off `main` using a descriptive prefix: `feat/…`, `fix/…`, `test/…`,
  `chore/…`, `docs/…`, or `ci/…`.
- Write clear, imperative commit messages (a short subject plus a body when the
  change needs explanation).
- Keep unrelated changes in separate PRs.

## Pull requests

- Open PRs against `main`. The [PR template](.github/PULL_REQUEST_TEMPLATE.md)
  is applied automatically — please complete it.
- CI (`.github/workflows/ci.yml`) runs ruff, the test matrix across Python
  3.8–3.13, a build check, and the coverage gate. All checks must pass.
- Update the `README.md` when you change behavior, configuration, or usage.

## Reporting bugs and requesting features

Use the issue templates (Bug report / Feature request). For **security
vulnerabilities**, follow the [security policy](SECURITY.md) instead of opening
a public issue.

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE) and that you follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
