# services

One folder per service: a Python package with its `manifest.yaml`, a `Dockerfile` and tests. Each package declares its class as an entry point in the `deepsift.services` group.

| Service | Accepts | Returns | State |
|---|---|---|---|
| [`sherlock`](sherlock/) | username | profile | ✅ Done |
| [`maigret`](maigret/) | username | profile, identity, image | ✅ Done |
| [`holehe`](holehe/) | email | account | ✅ Done |
| [`gravatar`](gravatar/) | email | profile, image, identity | ✅ Done |
| [`dns-mail`](dns-mail/) | email, domain | mx_record | ✅ Done |
| [`phone-meta`](phone-meta/) | phone | phone_meta | ✅ Done |
| [`ignorant`](ignorant/) | phone | account | ✅ Done |
| [`searxng`](searxng/) | username, email, phone, domain | web_page | ✅ Done |
| [`avatar-hash`](avatar-hash/) | image | image_hash | ✅ Done |
| [`tineye`](tineye/) (needs `TINEYE_API_KEY`) | image | web_page | ✅ Done |
| [`telegram`](telegram/) (off by default) | phone, username | profile, image, identity, username, phone | ✅ Done |
| [`whatsapp`](whatsapp/) (Node, off by default) | phone | profile, image, email | ✅ Done |

Services can be written in any language: `whatsapp/` is a Node example (contract section 9).

To add a Python one, copy `sherlock/`, change the manifest, implement `run()`, and add the folder to `members` in the root `pyproject.toml`.
