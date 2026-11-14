# deepsift-gateway

The DeepSift gateway: REST and WebSocket API (contract section 7), service registry,
pivot engine and correlation. It serves the web GUI too.

## Run it

| Setup | Command | Tasks run |
|---|---|---|
| Laptop, no Docker | `pipx install "deepsift-gateway[services]"` then `deepsift-gateway` | inside the gateway process |
| Stack | `docker compose up --build` | in the service workers, over Redis |

It listens on `127.0.0.1:8000` by default. On first start without `DEEPSIFT_API_TOKEN`
it creates a token in `$DEEPSIFT_DATA_DIR/api-token` (mode 0600) and logs the path.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `DEEPSIFT_API_TOKEN` / `_FILE` | generated | Bearer token; the GUI exchanges it for a session cookie |
| `DEEPSIFT_DATABASE_URL` / `_FILE` | SQLite in the data dir | e.g. `postgresql+asyncpg://deepsift@postgres/deepsift` |
| `DEEPSIFT_DATABASE_PASSWORD` / `_FILE` | — | Inserted into the database URL |
| `DEEPSIFT_REDIS_URL` (or `REDIS_URL`) | — | Set it to send tasks to workers; unset runs them in-process |
| `DEEPSIFT_DATA_DIR` | `~/.local/share/deepsift` | Token, SQLite, blobs |
| `DEEPSIFT_BLOBS_DIR` | `<data dir>/blobs` | Shared with avatar-hash, tineye, telegram |
| `DEEPSIFT_GUI_DIR` | — | Built GUI (`gui/dist`) to serve on `/` |
| `DEEPSIFT_ALLOWED_ORIGINS` | — | Extra browser origins, comma-separated (e.g. the Vite dev server) |
| `DEEPSIFT_HOST`, `DEEPSIFT_PORT` | `127.0.0.1`, `8000` | Listen address |
| `DEEPSIFT_FORWARDED_ALLOW_IPS` | — | Trust `X-Forwarded-*` from this reverse proxy |
| `DEEPSIFT_HSTS` | off | `1` behind HTTPS |
| `DEEPSIFT_SESSION_TTL` | `43200` | Session lifetime in seconds |

## Database

The schema is managed with Alembic (`src/deepsift_gateway/migrations`). The gateway
upgrades the database itself at start; a database created before migrations existed is
adopted as revision `0001`. After changing a model, add a revision:

```
uv run python -c "from alembic import command; from sqlalchemy import create_engine; \
from deepsift_gateway.db import alembic_config; \
e = create_engine('sqlite:////tmp/dev.db'); c = e.connect(); \
command.upgrade(alembic_config(c), 'head'); \
command.revision(alembic_config(c), message='what changed', autogenerate=True); c.commit()"
```

`gateway/tests/test_migrations.py` fails when a model change has no migration.

## Security

| Layer | What the gateway does |
|---|---|
| Auth | Bearer token, or a session cookie `__Host-deepsift_session` (`HttpOnly`, `Secure`, `SameSite=Strict`); only its SHA-256 is stored. Failed logins are throttled (5 per 10 min per client) |
| CSRF | Cookie requests that change state need an allowed `Origin`; WebSocket handshakes too |
| Fetch Metadata | Cross-site requests to the API are refused before auth |
| CSP | GUI page: per-request nonce, `strict-dynamic`, Trusted Types, `object-src 'none'`, `base-uri 'none'`, `frame-ancestors 'none'`; violations reported to `/api/v1/reports`. API: `default-src 'none'` |
| Other headers | `nosniff`, `Referrer-Policy: no-referrer`, COOP/CORP `same-origin`, `X-Frame-Options: DENY`, `Permissions-Policy`, `Cache-Control: no-store` on the API, HSTS on demand |
| Inputs | Pydantic limits on every body, 1 MiB body cap (10 MiB for image uploads), options checked against manifests, images checked by magic number |
| Outputs | Blobs served sandboxed with their sniffed type; CSV export neutralises formulas; HTML export escapes everything and runs no script |
| Logout | `Clear-Site-Data: "cookies", "storage", "cache"` |
