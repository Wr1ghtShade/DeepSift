# Contributing to DeepSift

OSINT investigation console: CLI + web GUI on a micro-service architecture. The project is in early development.

## Source of truth

- The service contract is `docs/specs/service-contract.md`. Read it before touching the gateway, the SDK or a service. A change to the contract means updating that document in the same commit.
- GUI themes: graphite + violet (default) and a light "papier technique" alternative.

## Layout

| Folder | Content |
|---|---|
| `gateway/` | FastAPI gateway: REST + WebSocket API, service registry, pivot engine |
| `sdk/` | `deepsift-sdk`: contract models, `Service` base class, buses, worker, local mode |
| `services/<name>/` | One service per folder: `manifest.yaml`, `Dockerfile`, code, tests |
| `cli/` | `deepsift` command (Typer + Rich) |
| `gui/` | React + Vite + TypeScript, TanStack Query and Table, Cytoscape.js; native HTML components (dialog, popover), no inline styles (strict CSP) |
| `docs/` | Specs and design notes |

The repo is a uv workspace: `sdk/` (deepsift-sdk), `cli/` (deepsift), `gateway/` (deepsift-gateway) and each `services/<name>/` (deepsift-svc-<name>) are packages with a `src/` layout. A new service must be added to `members` and `[tool.uv.sources]` in the root `pyproject.toml`, and to `testpaths`.

Commands: `uv sync`, `uv run ruff check .`, `uv run ruff format .`, `uv run pytest`; GUI: `cd gui && npm test && npm run build`, browser check `npm run e2e` (see `gui/README.md`). Tests must not need the network: replace external calls with fakes (see `services/sherlock/tests`). Shared test fakes live in `sdk/tests/fakes.py`.

## Code

- Python 3.11+, type hints everywhere, `ruff` for lint and format, `pytest` for tests.
- Code, comments, docs and commit messages in English.
- Async I/O (`httpx`, `redis.asyncio`). No blocking calls in a service's task loop.
- Secrets come from environment variables. Never log them.

## Rules for services

- Call wrapped tools as libraries when they offer an API; fall back to a subprocess only if not.
- Every dependency must be compatible with GPL-3.0.
- Public data only: no breached or stolen data, no facial recognition.
- Respect target sites' rate limits and declare them in the manifest.

## Git

- Small commits with clear messages.
