<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo/deepsift-mark-dark.svg">
    <img src="assets/logo/deepsift-mark-light.svg" alt="DeepSift logo" width="120">
  </picture>
</p>

# DeepSift

> **🚧 Work in progress.** DeepSift is in early development. Every v1 service works from the CLI (usernames, email addresses, phone numbers, domains and images, with automatic pivots and avatar matching); the gateway API and the web GUI work. Expect breaking changes.

DeepSift is an OSINT investigation console. Give it a selector — a username, an email address, a phone number, a domain or an image — and it runs the matching collection services, merges what they find, and lets you pivot from one result to the next.

It ships as a **CLI** and a **web GUI**, built on a **micro-service architecture**: every capability (Sherlock, Maigret, holehe, avatar hashing…) runs as its own service behind a common contract, so new capabilities can be added without touching the core.

## Status

| Area | State |
|---|---|
| Service contract | Draft v1 — [`docs/specs/service-contract.md`](docs/specs/service-contract.md) |
| SDK | ✅ Models, `Service` base class, Redis Streams and in-memory buses, worker, local mode |
| CLI | ✅ Local mode or through the gateway (`--gateway`), automatic pivots and avatar groups: `user`, `email`, `phone`, `domain`, `image`, `search`, `services` |
| Services | ✅ All 10 v1 services, plus `telegram` and `whatsapp` (opt-in) · see [`services/`](services/) |
| Gateway | ✅ REST + WebSocket API, pivots, correlation, exports, token/session auth, hardened headers · see [`gateway/`](gateway/) |
| Web GUI | ✅ Login, new investigation, live results (lanes, table, graph), entity page with pivots, services; graphite and light themes · see [`gui/`](gui/) |

## Features

| Selector | Services |
|---|---|
| Username | Sherlock (fast pass), Maigret (deep pass with profile extraction), SearXNG |
| Email | holehe, Gravatar, MX records and mail provider, SearXNG |
| Phone number | Offline metadata (country, area, carrier, line type), ignorant, SearXNG |
| Domain | MX records and mail provider, SearXNG |
| Image / avatar | Perceptual hashing to spot profiles that share an avatar; TinEye reverse image search (API key) |
| Opt-in | Telegram (phone or @username) and WhatsApp (phone), through a dedicated account of yours |

Results from several services are de-duplicated and scored: a profile found by two tools, or sharing an avatar with another profile, gets a higher confidence. What a service finds is handed to the services that accept it (an avatar to avatar-hash and TinEye, a Telegram @username to Sherlock and Maigret…).

Results from several services are de-duplicated and scored: a profile found by two tools, or sharing an avatar with another profile, gets a higher confidence.

## Architecture

```
     Web GUI (React)          CLI (deepsift)
           └──────────┬──────────────┘
              API gateway (FastAPI)        auth, WebSocket, service registry
                      │
          Message bus (Redis Streams)
     ┌──────┬─────────┼─────────┬────────────┐
 sherlock maigret   holehe   avatar-hash   searxng …     one container per service
                      │
      PostgreSQL (entities, links) · object storage (avatars, exports)
```

Each service publishes a manifest (what it accepts, what it returns) and registers itself at startup. The GUI and CLI discover it automatically.

## Try it (development)

DeepSift is not on PyPI yet. From a clone, with [uv](https://docs.astral.sh/uv/):

```
uv sync
uv run deepsift services
uv run deepsift user nightowl_77 -o findings.json
```

Some services need settings or keys: copy `.env.example` to `.env` and fill in what you use. For web mentions, run your own SearXNG (see the header of `compose.yaml`), then `export SEARXNG_URL=http://127.0.0.1:8080`. `deepsift services` shows what each service still needs.

To run the API and the GUI: build the GUI once (`cd gui && npm install && npm run build`), then `DEEPSIFT_GUI_DIR=gui/dist uv run deepsift-gateway` and open http://127.0.0.1:8000 (tasks run in-process; the token is written to `~/.local/share/deepsift/api-token`), or `docker compose up --build` for the full stack with Redis, PostgreSQL and one worker per service. See [`gateway/README.md`](gateway/README.md).

In Docker, the gateway image already contains the GUI. Later: `pipx install deepsift` for the CLI.

## Development

Conventions: [`CONTRIBUTING.md`](CONTRIBUTING.md).

```
uv sync                 # install the workspace (sdk, cli, gateway, services)
uv run ruff check .     # lint
uv run ruff format .    # format
uv run pytest           # tests, no network needed
```

## Roadmap

| Version | Scope |
|---|---|
| v1 | Gateway, SDK, CLI, web GUI, the services listed above |
| v1.5 | Login screen and user accounts, people search engines (Webmii and similar), GHunt |
| v2 | X, Instagram, TikTok |

## Ethics and legal

Some services act through an account of yours or go against a platform's terms (e.g. `whatsapp`). They are **off by default**, documented with their risks, and run only when you turn them on (`--enable`).


DeepSift only collects **publicly available** information. It will not integrate breached or stolen data, and it does not do facial recognition. Respect the terms of service of the sites you query and the laws that apply to you (GDPR in the EU). You are responsible for how you use it.

## License

[GPL-3.0](LICENSE). Some planned dependencies (holehe, ignorant) are GPL-3.0, so DeepSift is too.
