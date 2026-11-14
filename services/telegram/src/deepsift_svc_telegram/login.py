"""``deepsift-telegram``: log the dedicated Telegram account in once, check, log out."""

from __future__ import annotations

import argparse
import asyncio
import sys

from deepsift_sdk import ServiceError

from .gateway import make_client, session_path

WARNING = (
    "Use a DEDICATED Telegram account, never your personal or work number.\n"
    "API keys come from https://my.telegram.org > API development tools.\n"
)


async def login() -> int:
    print(WARNING, file=sys.stderr)
    client = make_client()
    await client.start()  # asks for the phone number, the code and the 2FA password
    me = await client.get_me()
    print(f"Logged in as {me.username or me.id}. Session: {session_path()}.session")
    await client.disconnect()
    return 0


async def status() -> int:
    client = make_client()
    await client.connect()
    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"logged in as {me.username or me.id}")
            return 0
        print("not logged in")
        return 1
    finally:
        await client.disconnect()


async def logout() -> int:
    client = make_client()
    await client.connect()
    if await client.is_user_authorized():
        await client.log_out()  # also ends the session on Telegram's side
    await client.disconnect()
    print("Logged out.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="deepsift-telegram")
    parser.add_argument("command", choices=["login", "status", "logout"])
    args = parser.parse_args()
    try:
        code = asyncio.run({"login": login, "status": status, "logout": logout}[args.command]())
    except ServiceError as exc:
        print(f"error: {exc.info.message}", file=sys.stderr)
        code = 2
    sys.exit(code)
