<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo/deepsift-mark-dark.svg">
    <img src="assets/logo/deepsift-mark-light.svg" alt="DeepSift logo" width="120">
  </picture>
</p>

# DeepSift

> **🚧 Work in progress.** DeepSift is in early development. Nothing is usable yet: the repository currently holds the design and the service contract. Expect breaking changes.

DeepSift is an OSINT investigation console. Give it a selector — a username, an email address, a phone number, a domain or an image — and it runs the matching collection services, merges what they find, and lets you pivot from one result to the next.

It ships as a **CLI** and a **web GUI**, built on a **micro-service architecture**: every capability (Sherlock, Maigret, holehe, avatar hashing…) runs as its own service behind a common contract, so new capabilities can be added without touching the core.

## Status

| Area | State |
|---|---|
| Service contract | Draft — [`docs/specs/service-contract.md`](docs/specs/service-contract.md) |
| Gateway, SDK, CLI | Not started |
| Services | Not started |
| Web GUI | Mockups done, not implemented |

## Planned features (v1)

| Selector | Services |
|---|---|
| Username | Sherlock (fast pass), Maigret (deep pass with profile extraction) |
| Email | holehe, Gravatar, DNS/MX validation |
| Phone number | Offline metadata (country, carrier, line type), ignorant |
| Any | SearXNG meta-search (self-hosted) |
| Image / avatar | Local perceptual hashing to correlate profiles that share an avatar; reverse image search through TinEye (API key) and prefilled Google Lens, Yandex and Bing links |

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

## Installation

Not available yet. Two modes are planned:

- `pipx install deepsift` for the CLI
- `docker compose up` for the full stack with the web GUI

## Roadmap

| Version | Scope |
|---|---|
| v1 | Gateway, SDK, CLI, web GUI, the services listed above |
| v1.5 | Login screen and user accounts, people search engines (Webmii and similar), GHunt |
| v2 | X, Instagram, TikTok |

## Ethics and legal

DeepSift only collects **publicly available** information. It will not integrate breached or stolen data, and it does not do facial recognition. Respect the terms of service of the sites you query and the laws that apply to you (GDPR in the EU). You are responsible for how you use it.

## License

[GPL-3.0](LICENSE). Some planned dependencies (holehe, ignorant) are GPL-3.0, so DeepSift is too.
