# services

One folder per service: a Python package with its `manifest.yaml`, a `Dockerfile` and tests. Each package declares its class as an entry point in the `deepsift.services` group.

| Service | Accepts | Returns | State |
|---|---|---|---|
| [`sherlock`](sherlock/) | username | profile | ✅ Done |
| [`maigret`](maigret/) | username | profile, identity, image | ✅ Done |
| [`holehe`](holehe/) | email | account | ✅ Done |
| [`gravatar`](gravatar/) | email | profile, image, identity | ✅ Done |
| [`dns-mail`](dns-mail/) | email, domain | mx_record | ✅ Done |
| `phone-meta` | phone | phone_meta | Planned |
| `ignorant` | phone | account | Planned |
| `searxng` | all | web_page | Planned |
| [`avatar-hash`](avatar-hash/) | image | image_hash | ✅ Done |
| `tineye` | image | web_page | Planned |

To add one, copy `sherlock/`, change the manifest, implement `run()`, and add the folder to `members` in the root `pyproject.toml`.
