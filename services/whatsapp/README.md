# whatsapp

Tells whether a phone number has a WhatsApp account, and returns what its owner's privacy settings show to everyone: profile picture, "about" text, business details. The picture goes to `avatar-hash` like any other avatar, so it can be matched with other sites.

**Off by default.** Turn it on per search with `--enable whatsapp`, or in the stack with the `whatsapp` compose profile.

## Read this first

- **It needs a WhatsApp account: use a dedicated one** (a separate SIM), never your personal or work number. Lookups are made by that account, so WhatsApp knows who asked.
- **The person you look up is not notified.** Contact discovery is a server query: no message, request or notification reaches them.
- **This uses WhatsApp Web's protocol through [Baileys](https://github.com/WhiskeySockets/Baileys), not an official API.** It goes against WhatsApp's terms of service, and the linked account can be banned, especially with many lookups. The service paces itself: 10 s minimum between lookups and 50 per day by default (`min_interval`, `daily_limit`). Raising these increases the risk.
- **Only public data comes back.** If the owner shows their picture or "about" to contacts only, it stays hidden. The service never tries to get around privacy settings.
- **You are responsible for your use.** A phone number and a profile picture are personal data (GDPR). Use it for legitimate investigations.

## Link the account

From a clone, with Node 20+:

```
cd services/whatsapp
npm ci && npm link                     # installs the deepsift-whatsapp command
deepsift-whatsapp link                 # shows a QR code to scan: WhatsApp > Linked devices
deepsift-whatsapp link --phone +33…    # or: an 8-character code to type in WhatsApp
deepsift-whatsapp status
```

The session is kept in `~/.local/share/deepsift/whatsapp/auth` (or `$DEEPSIFT_DATA_DIR/whatsapp/auth`). `deepsift-whatsapp unlink` deletes it; also remove the device in WhatsApp > Linked devices.

## Use

```
deepsift phone +33612345678 --enable whatsapp
deepsift-whatsapp check +33612345678   # quick check without the rest of DeepSift
```

In Docker, the session lives in the `whatsapp-data` volume:

The service runs with the stack but stays unchecked and idle until the account is linked, once:

```
docker compose exec svc-whatsapp node src/cli.js link --phone +33XXXXXXXXX && docker compose restart svc-whatsapp
```

## What it reports

| Entity | Link | When |
|---|---|---|
| `profile` `https://wa.me/<number>` | `found_on` the phone | the number has an account. Attributes: `about`, `business`, business category, description, address, websites |
| `image` | `avatar` from the profile | the picture is public |
| `email` | `business_email` from the profile | a business account shows an email; it then pivots to the email services |

## Development

```
npm ci
npm test                 # node:test, with a fake WhatsApp socket and a fake clock
```

`src/contract.js` implements the DeepSift contract in JavaScript; `src/worker.js` speaks the same Redis streams as the Python SDK; `src/deepsift_svc_whatsapp` is the Python bridge used by the CLI in local mode.
