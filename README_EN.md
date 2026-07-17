# Curx

Curx is a LangChain-based internal knowledge-answering platform rebuilt from the
useful parts of AidBot. It is intentionally not a NotebookLM clone: the first
release optimizes for reliable ingestion, hybrid retrieval, grounded answers,
and operational traceability.

## Development environment

Python 3.12 and dependencies are managed by `uv`.

```powershell
uv sync
uv run python --version
uv run pytest
```

The local virtual environment lives in `.venv`; do not activate it for normal
work. Use `uv run` so commands always use the locked project environment.

## Design

The implementation decisions, Open Notebook comparison, data model, indexing
pipeline, and phased backlog live in [docs/system-design.md](docs/system-design.md).
