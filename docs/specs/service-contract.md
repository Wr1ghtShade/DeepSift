# Service contract

**Status:** draft · **Contract version:** 1

This document defines how DeepSift services talk to the gateway. Any service that follows it can be added to a deployment without changes to the gateway, the CLI or the GUI.

## 1. Concepts

| Term | Meaning |
|---|---|
| **Selector** | What the user types: a username, an email, a phone number, a domain or an image |
| **Entity** | A typed piece of data: a selector, or something a service found (a profile, an account, an avatar…) |
| **Link** | A directed relation between two entities (`found_on`, `same_avatar`, `mentions`…) |
| **Service** | A process that accepts entities of some types and emits new entities and links |
| **Task** | One request for one service to process one entity |
| **Run** | All tasks started from one selector in one investigation |
| **Investigation** | A named case grouping runs, entities and links |
| **Pivot** | Using an entity found by one service as the input of another |

## 2. Entity types

| Type | `value` | Notable `attributes` |
|---|---|---|
| `username` | `nightowl_77` | — |
| `email` | `n.owl@example.org` (lower-cased) | — |
| `phone` | E.164, `+33612345678` | — |
| `domain` | `example.org` (lower-cased, no trailing dot) | — |
| `url` | absolute URL | — |
| `image` | URL or `blob:<sha256>` | `mime`, `width`, `height` |
| `profile` | profile URL | `site`, `username`, `display_name`, `bio`, `location`, `created_at`, `avatar_url` |
| `account` | `<site>:<selector>` | `site`, `exists`, `recovery_hint` |
| `identity` | free text | `name`, `aliases` |
| `web_page` | URL | `title`, `snippet`, `engine` |
| `phone_meta` | E.164 | `country`, `carrier`, `line_type`, `valid` |
| `mx_record` | host | `priority`, `domain` |
| `image_hash` | `phash:<64-bit hex>` | `algo`, `phash`, `dhash`, `sha256`, `width`, `height`, `format`, `trivial` (near-blank picture, e.g. a default avatar) |
| `avatar_group` | group id | `members`. Made by the orchestrator, not by a service (section 6) |

### Entity object

```json
{
  "type": "profile",
  "value": "https://github.com/nightowl_77",
  "attributes": { "site": "GitHub", "username": "nightowl_77", "avatar_url": "https://…" },
  "confidence": 0.9
}
```

- `confidence` is the service's own estimate, from 0 to 1. The gateway combines estimates from several services into the score shown to users.
- **Identity key:** two entities are the same when `type` and the normalized `value` are equal. The gateway merges them and keeps the list of services that found each one.
- **URL normalization** (`url`, `profile`, `web_page`, and `image` when it is a URL): lower-case scheme and host, no fragment, no trailing slash. Path and query keep their case. So `HTTPS://GitHub.com/x/` from one service and `https://github.com/x` from another are one profile.

## 3. Manifest

Every service ships a `manifest.yaml` and publishes it when it registers.

```yaml
contract: 1
name: maigret                 # unique, [a-z0-9-]
version: 0.1.0                # the service's own semver
description: Username search on 3000+ sites with profile extraction
inputs: [username]
outputs: [profile, identity, image]
links: [found_on]
mode: library                 # library | api | local
license: MIT                  # licence of the wrapped tool
timeout: 300s                 # per task
concurrency: 2                # tasks run in parallel by one instance
rate_limit: 1/s               # optional, towards external sites
secrets: []                   # names of required secrets, e.g. [TINEYE_API_KEY]
config: []                    # required non-secret settings from the environment, e.g. [SEARXNG_URL]
optional_secrets: []          # names of secrets that improve results, e.g. [GRAVATAR_API_KEY]
enabled_by_default: true      # false: runs only when turned on (sensitive or account-based services)
options:                      # optional, shown in the GUI and as CLI flags
  depth:
    type: enum
    values: [top500, all]
    default: top500
```

Rules:

- `inputs` and `outputs` use the types of section 2. A new type needs a change to this document.
- `secrets` lists **names only**. Values come from environment variables or Docker secrets and never travel on the bus.
- `config` works like `secrets` for readiness, for values that are not secret (an instance URL).
- A service with a missing secret or config registers anyway with state `needs_config`. The gateway does not send it tasks.
- `optional_secrets` raise limits or unlock fields when set; the service works without them.
- In local mode, a service missing a required secret is skipped (not failed) unless it is named with `--service`.
- `enabled_by_default: false` marks a service that must be turned on explicitly (CLI `--enable`, a compose profile, a gateway setting): services that act through the user's own account, go against a platform's terms, or carry a higher legal risk. Opt-in services are not used for pivots unless turned on either.

## 4. Registration and health

Transport is Redis. All keys are prefixed with `deepsift:`.

1. At startup, the service writes its manifest to the stream `deepsift:registry` with `event: register`.
2. Every 15 s it sets `deepsift:heartbeat:<name>:<instance_id>` with a 45 s TTL. The value holds `state` (`ready`, `busy`, `needs_config`), the number of running tasks and `missing`: what is still to do (secrets from the manifest, plus `Service.missing_setup()` such as a login). A `needs_config` worker checks again at every heartbeat and starts taking tasks once nothing is missing, without a restart.
3. On shutdown it writes `event: deregister`.

The gateway reads the registry stream and the heartbeats. A service with no live heartbeat is shown as offline.

## 5. Tasks and results

### Streams

| Stream | Writer | Reader |
|---|---|---|
| `deepsift:tasks:<service>` | gateway | the service, through the consumer group `<service>` |
| `deepsift:events` | services | gateway |

Using a consumer group lets several instances of one service share the load. A service acknowledges (`XACK`) a task only after it has sent `completed` or `failed`. Tasks left pending longer than `timeout` are claimed again (`XAUTOCLAIM`), up to 2 retries.

### Task message

```json
{
  "contract": 1,
  "task_id": "01J…",
  "run_id": "01J…",
  "investigation_id": "01J…",
  "service": "maigret",
  "input": { "id": "ent_…", "type": "username", "value": "nightowl_77" },
  "options": { "depth": "top500" },
  "deadline": "2026-11-14T12:00:00Z"
}
```

IDs are ULIDs.

### Event messages

Every event carries `contract`, `task_id`, `service` and `event`.

| `event` | Extra fields | Meaning |
|---|---|---|
| `started` | — | The service picked up the task |
| `progress` | `done`, `total`, `message` | Optional, drives the progress lanes in the GUI |
| `entity` | `entity`, `link` | One finding. `link` is `{ "from": "<id>", "rel": "found_on" }`, where `from` is the task's input or an entity the same task reported earlier (e.g. `avatar` from a profile) |
| `completed` | `count` | No more findings for this task |
| `failed` | `error` | See section 8 |

Services send findings as they find them. They do not batch them until the end.

## 6. Pivots

The gateway owns pivots. Services never call each other.

- When an `entity` event arrives, the gateway lists the services whose `inputs` include its type.
- **Manual mode (default):** the GUI and CLI offer these services as pivots.
- **Automatic mode:** set per run with `max_depth` (default 1, maximum 3). The gateway starts the tasks itself and never runs the same service twice on the same entity.
- **CLI local mode** pivots automatically with `--depth` (default 1, `0` turns pivots off). `--service` limits the services run on the selector itself; pivots may use any installed service.

### Correlation

Some conclusions need every result of a run, which no single service sees. The orchestrator (the gateway, or the CLI in local mode) draws them:

- **Avatar groups.** Profiles are linked to their avatar (`avatar`), avatars to their `image_hash` (`hash`). Hashes within 6 bits of each other (Hamming distance on the 64-bit pHash) are clustered, transitively. Hashes flagged `trivial` are left out. A cluster that covers two profiles or more becomes an avatar group, and its profiles get the avatar bonus (section 13).

## 7. Gateway API

Base path: `/api/v1`. JSON everywhere. Timestamps are ISO 8601 in UTC.

| Method and path | Purpose |
|---|---|
| `POST /investigations` | Create an investigation `{ "name" }` |
| `GET /investigations` | List investigations, with their entity count |
| `GET /investigations/{id}` | One investigation with its runs |
| `DELETE /investigations/{id}` | Delete it, its runs and its entities |
| `POST /investigations/{id}/runs` | Start a run `{ "selector", "type"?, "services"?, "options"?, "auto_pivot"?, "max_depth"? }`. Without `type`, the gateway detects it. Without `services`, it uses every enabled service, with a live configured instance, that accepts the type. `options` is `{ service: { option: value } }`, checked against the manifests. `max_depth` (default 1) applies only with `auto_pivot: true` |
| `GET /runs/{id}` | A run and its tasks |
| `POST /runs/{id}/cancel` | Stop a run (`409` if it is not running) |
| `GET /investigations/{id}/entities` | Entities, with filters `type`, `service`, `min_confidence`, and `limit`/`offset` |
| `GET /investigations/{id}/graph` | Entities, links and avatar groups, for the graph view |
| `GET /entities/{id}` | One entity, its investigation, its sources, its links and the services it can be pivoted to |
| `POST /entities/{id}/pivot` | Run services on this entity `{ "services"?, "max_depth"? }` |
| `GET /investigations/{id}/export?format=json\|csv\|html` | Report |
| `GET /services` | Registered services: manifest, state, instances, enabled |
| `PATCH /services/{name}` | `{ "enabled": bool }`, overrides `enabled_by_default` |
| `POST /blobs` | Upload an image (PNG, JPEG, GIF, WebP, 10 MiB max); returns `{ "sha256", "selector": "blob:<sha256>" }` |
| `GET /blobs/{sha256}` | A stored image |
| `WS /investigations/{id}/stream` | Live messages, below |
| `GET /info` | Gateway version, contract, executor (`local` or `redis`), database, counts |
| `GET /health` | Liveness, no auth |
| `POST /session`, `GET /session`, `DELETE /session` | Browser login with the token, status, logout |
| `POST /reports` | CSP violation reports (Reporting API), no auth |

**Auth.** Every route but `health`, `session` and `reports` needs either `Authorization: Bearer <token>` or the session cookie that `POST /session { "token" }` sets. Cookie requests that change state, and WebSocket handshakes, must come from an allowed `Origin`. Details in `gateway/README.md`.

**Stream messages.** Each has a `type`:

| `type` | Fields |
|---|---|
| `run.started` | `run` |
| `task.queued` | `task` (`id`, `run_id`, `service`, `entity_id`, `depth`, `status`) |
| `task.started` | `run_id`, `task_id`, `service` |
| `task.progress` | `done`, `total`, `message` |
| `task.entity` | `entity` (merged, with `score`, `level`, `sources`), `link` (`source`, `rel`, `target`, database ids) |
| `entity.merged` | Same fields, for an entity already known in the investigation |
| `task.completed`, `task.failed` | `task`, with `count` or `error` |
| `run.completed` | `run_id`, `status` (`completed` or `cancelled`), `avatar_groups` |
| `stream.lagged` | The client fell behind; the gateway closes the socket and the client reloads |

Services found by a worker keep their own entity ids inside the task (for `link.from`); the gateway gives every merged entity its own id.

The gateway runs tasks in two ways: over Redis (section 5) when `DEEPSIFT_REDIS_URL` is set, otherwise in its own process with the installed services, like the CLI's local mode. A task with no final event after `timeout × 3 + 60 s` is failed with `timeout`. Runs still open when the gateway stops are marked `interrupted` at the next start.

The CLI uses this API when a gateway is configured. Otherwise it runs services as local processes behind the same contract (section 9).

## 8. Errors

```json
{ "code": "rate_limited", "message": "429 from target site", "retryable": true }
```

| `code` | Retryable | Meaning |
|---|---|---|
| `invalid_input` | no | The value does not fit the type |
| `needs_config` | no | A secret is missing |
| `rate_limited` | yes | The target site throttled the service |
| `upstream_error` | yes | The target site or API failed |
| `timeout` | yes | The deadline passed |
| `internal` | no | Bug in the service |

## 9. Local mode (CLI without Docker)

The SDK provides an in-process bus with the same messages. `deepsift user nightowl_77` loads the installed services as Python entry points (group `deepsift.services`) and runs them without Redis or a gateway. Results are printed, or saved with `--output`. The local run honours each manifest's `concurrency`.

### Services in other languages

A service can be written in any language: in the stack it only has to speak the Redis streams of sections 4 and 5. For local mode it also implements a **stdio mode**:

- it reads **one task** as a JSON line on stdin;
- it writes **events** as JSON lines on stdout (same format as on the bus), ending with `completed` or `failed`;
- it writes logs on stderr only, and exits.

A small Python package makes it discoverable: a subclass of `deepsift_sdk.external.ExternalService` with the command to run, declared in the `deepsift.services` entry points. `DEEPSIFT_<NAME>_CMD` overrides the command. A missing program is reported as `needs_config` with an install hint. `services/whatsapp` (Node) is the reference.

## 10. Security

- Only the gateway is exposed. Services open no inbound port.
- Secrets live in environment variables or Docker secrets, never in manifests, messages or logs.
- v1 binds to localhost or an internal network, behind Caddy for TLS. Authentication (login screen, user accounts) is planned for v1.5.
- Downloaded avatars are stored by SHA-256 and served only through the gateway.
- **Fetching URLs found online.** A service that downloads URLs taken from scraped pages must only reach public addresses, checking each redirect hop, and cap the size. Without a proxy it resolves the host and refuses any non-global address. Behind an HTTP(S) proxy it refuses private IP literals, `localhost`, single-label names and internal suffixes (`.local`, `.lan`, `.internal`…), and the proxy filters the rest. Egress rules on the host are the second layer.

## 11. Data policy

- Public sources only. No breached or stolen data, no breach-search engines built on leaks.
- No facial recognition.
- Each service respects the target site's rate limits and declares them in its manifest.

## 12. Versioning

- `contract` is an integer carried by every manifest and message.
- Adding optional fields keeps the version. Removing or changing a field increments it.
- The gateway accepts the current version and the one before it.

## 13. Confidence

Each service gives every entity its own `confidence` (0 to 1). When several services find the same entity (same identity key, section 2), the gateway combines them with a noisy-OR:

```
combined = 1 − Π (1 − cᵢ)
```

Each extra source raises the score without ever passing 1. A `profile` whose avatar belongs to an `avatar_group` already linked to the selector gets a bonus of +0.15, capped at 1.

| Level shown | Combined score |
|---|---|
| High | ≥ 0.8 |
| Medium | ≥ 0.5 |
| Low | < 0.5 |

Example: Sherlock gives 0.6 and Maigret 0.7, so the profile scores 1 − 0.4 × 0.3 = 0.88 (High). Found by Sherlock alone, it stays at 0.6 (Medium).

## 14. Storage

Downloaded files (avatars, exports) are content-addressed: stored under their SHA-256, which removes duplicates for free. v1 uses a local volume (`/data/blobs/<first 2 hex>/<sha256>`). Every image runs as the same user, `deepsift` with uid and gid 10001, so all of them can read and write the shared volume. The SDK hides it behind a `Storage` interface so an S3-compatible backend (MinIO) can replace it later without changes to services.

## Decisions log

| Date | Decision |
|---|---|
| 2026-11-14 | Bus: Redis Streams. The SDK keeps a `Bus` interface so NATS JetStream stays possible |
| 2026-11-14 | Storage: local content-addressed volume in v1, MinIO later (section 14) |
| 2026-11-14 | Confidence: noisy-OR with an avatar bonus (section 13) |
| 2026-11-14 | Gateway: FastAPI, PostgreSQL in the stack and SQLite on a laptop (SQLAlchemy async); runs tasks in-process when no Redis is set |
| 2026-11-14 | Gateway auth: one API token until the login screen; browsers swap it for a `__Host-` session cookie. Security follows web.dev / modern-web-guidance (nonce CSP + Trusted Types, Fetch Metadata, COOP/CORP) |
