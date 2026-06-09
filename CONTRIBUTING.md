# Contributing

Welcome to Strata Memory. We're glad you're here.

## Development Setup

```bash
git clone https://github.com/vincy/strata-memory.git
cd strata-memory
uv sync --group dev
```

## Development Workflow

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/awesome-feature`)
3. Make your changes
4. Run tests: `uv run pytest -v`
5. Commit (`git commit -m 'Add awesome feature'`)
6. Push (`git push origin feature/awesome-feature`)
7. Open a Pull Request

## Code Style

- **Dependency management**: `uv`
- **Formatting**: PEP 8 via ruff
- **Type hints**: All public functions must have type annotations
- **Tests**: New features should include tests

## Pre-PR Checklist

- [ ] Tests pass: `uv run pytest -v`
- [ ] No lint errors: `uv run ruff check .`
- [ ] README updated if adding user-facing features

## Project Structure

See [DEVELOPMENT.md](DEVELOPMENT.md) for architecture details.

Thank you for contributing.
