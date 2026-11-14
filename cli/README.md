# deepsift (CLI)

The `deepsift` command. For now it runs in local mode: installed services run in-process, without Redis or a gateway.

```
deepsift services                         # installed services and their state
deepsift user nightowl_77                 # username
deepsift email john@example.org           # email
deepsift phone +33612345678               # phone number
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
| `-d, --depth N` | Pivot hops (default 1, max 3, 0 = off): services also run on what was found, e.g. avatars go to `avatar-hash` |

While the search runs, the sieve shows each service's progress. Findings found by several services are merged and scored (noisy-OR, see the contract's section 13). Profiles that use the same picture share a letter in the Avatar column and get a confidence bonus. Run `deepsift services` to see each service's state; a service that works better with an API key says so (e.g. `GRAVATAR_API_KEY`). Downloaded images are kept in `~/.local/share/deepsift/blobs` (or `$DEEPSIFT_DATA_DIR/blobs`).
