#!/usr/bin/env python3
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import asyncpg
import toml
import yarl

from discord import http, gateway

from beattie.bot import BeattieBot

if TYPE_CHECKING:
    from beattie.utils.type_hints import BotConfig

if sys.platform == "win32":
    from asyncio import run
else:
    from uvloop import run


async def get_pool(config: BotConfig) -> asyncpg.Pool:
    password = config.get("config_password", "")
    dsn = f"postgresql://beattie:{password}@localhost/beattie"

    return await asyncpg.create_pool(dsn)


async def main(config: BotConfig):
    debug = config.get("debug") or "debug" in sys.argv
    if debug:
        prefixes = config["test_prefixes"]
        token = config["test_token"]
    else:
        prefixes = config["prefixes"]
        token = config["token"]

    pool = await get_pool(config)

    if api := config.get("api"):
        http.Route.BASE = api
    if ws := config.get("gateway"):
        gateway.DiscordWebSocket.DEFAULT_GATEWAY = yarl.URL(ws)

    bot = BeattieBot(prefixes=tuple(prefixes), pool=pool, debug=debug)
    if ids := config.get("owner_ids"):
        bot.owner_ids = ids

    await bot.start(token)


if __name__ == "__main__":
    with open("config/config.toml") as file:
        config: BotConfig = toml.load(file)  # pyright: ignore[reportAssignmentType]
    try:
        run(main(config))
    except KeyboardInterrupt:
        pass
