# telegram

Finds the Telegram account behind a phone number or a public @username, with what Telegram shows to anyone: names, @usernames, bio, profile picture, last-seen category (recently, within a week…), and the premium, bot, scam or fake flags. A username found from a phone number pivots to Sherlock and Maigret; the picture goes to `avatar-hash`.

**Off by default.** Turn it on per search with `--enable telegram`, or in the stack with the `telegram` compose profile.

## Read this first

- **It uses the official Telegram API with a user account: use a dedicated one** (a separate SIM), never your personal or work number.
- **A phone number only matches if its owner allows it.** Telegram returns the account only when the owner's "Who can find me by my number" setting lets you. Otherwise the answer is the same as "no account".
- **The owner is not notified.** The number is imported as a temporary contact, the way Telegram's apps find people, and deleted right after.
- **Telegram limits contact imports per account.** The service paces itself (10 s between lookups, 50 per day by default) and stops when Telegram asks to wait. Pushing harder can get the account restricted.
- **You are responsible for your use.** Use it for legitimate investigations, within Telegram's terms and the GDPR.

## Set up

1. Get an `api_id` and an `api_hash` on <https://my.telegram.org> > API development tools, while logged in with the dedicated account.
2. Export them, then log in once (you will be asked for the number, the code Telegram sends, and the 2FA password if any):

```
export TELEGRAM_API_ID=123456
export TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
deepsift-telegram login
deepsift-telegram status
```

The session is kept in `~/.local/share/deepsift/telegram/deepsift.session` (or under `$DEEPSIFT_DATA_DIR`). `deepsift-telegram logout` ends it on Telegram's side too. One session can only be used by one process at a time: run either the CLI or the worker.

## Use

```
deepsift phone +33612345678 --enable telegram
deepsift user nightowl_77 --enable telegram
```

In Docker, the keys come from your `.env` and the session lives in the `telegram-data` volume:

```
docker compose --profile telegram run --rm svc-telegram deepsift-telegram login
docker compose --profile telegram up -d svc-telegram
```

## What it reports

| Entity | Link | When |
|---|---|---|
| `profile` `t.me/<username>` (or `tg://user?id=<id>`) | `found_on` the input | an account is found |
| `image` `blob:<sha256>` | `avatar` from the profile | the picture is public |
| `identity` | `identity` from the profile | the account has a name |
| `username` | `username` from the profile | the input was a phone and the account has a @username |
| `phone` | `phone` from the profile | the input was a username and the number is shown |
