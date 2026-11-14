# deepsift (CLI)

The `deepsift` command. Two modes:

| Mode | How | Where services run |
|---|---|---|
| Local (default) | `deepsift user nightowl_77` | In the CLI process, with the services installed next to it |
| Gateway | `deepsift --gateway http://127.0.0.1:47800 user nightowl_77`, or `DEEPSIFT_GATEWAY_URL` | On the gateway (in-process or Docker workers); the investigation stays there and shows in the GUI |

In gateway mode the token comes from `DEEPSIFT_API_TOKEN`, `DEEPSIFT_API_TOKEN_FILE`, or, for a gateway on this machine, the `api-token` file it writes in `$DEEPSIFT_DATA_DIR`. Pivots then use the services enabled on the gateway; `--enable` adds an opt-in service for the selector only.

```
deepsift services                         # installed services and their state
deepsift user nightowl_77                 # username
deepsift email john@example.org           # email
deepsift phone +33612345678               # phone number
deepsift phone 0612345678 --region FR     # national format
deepsift domain example.org               # domain
deepsift image https://example.org/a.png  # image URL
deepsift search <anything>                # detect the type, then run matching services
```

Options for every search:

| Option | Effect |
|---|---|
| `-s, --service NAME` | Only run this service (repeatable) |
| `-o, --output FILE` | Save findings as JSON |
| `--min high\|medium\|low` | Hide findings below this confidence level |
| `--opt service.option=value` | Set a service option, typed by its manifest (repeatable). E.g. `maigret.top_sites=0` (all sites), `dns-mail.resolver=doh`, `holehe.password_recovery=true` |
| `-e, --enable NAME` | Turn on a service that is off by default, e.g. `whatsapp` (read its README first) |
| `-d, --depth N` | Pivot hops (default 1, max 3, 0 = off): services also run on what was found, e.g. avatars go to `avatar-hash` |

While the search runs, the sieve shows each service's progress. Findings found by several services are merged and scored (noisy-OR, see the contract's section 13). Profiles that use the same picture share a letter in the Avatar column and get a confidence bonus. Run `deepsift services` to see each service's state; a service that works better with an API key says so (e.g. `GRAVATAR_API_KEY`). Downloaded images are kept in `~/.local/share/deepsift/blobs` (or `$DEEPSIFT_DATA_DIR/blobs`).
