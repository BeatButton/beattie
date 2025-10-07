#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import platform
import sys
from typing import TYPE_CHECKING

import asyncpg
import toml

from beattie.bot import BeattieBot, Shared
from beattie.utils.contextmanagers import MultiAsyncWith

if TYPE_CHECKING:
    from beattie.utils.type_hints import BotConfig

if platform.system() == "Windows":
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
        tokens = [config["test_token"]]
    else:
        prefixes = config["prefixes"]
        tokens = config["tokens"]

    pool = await get_pool(config)

    shared = Shared(prefixes=tuple(prefixes), pool=pool, debug=debug)
    await shared.async_init()

    bots = [BeattieBot(shared) for _ in tokens]
    async with MultiAsyncWith(bots) as bots, asyncio.TaskGroup() as tg:
        shared.bots = bots
        for bot in bots:
            bot.shared = shared
        for bot, token in zip(bots, tokens):
            tg.create_task(bot.start(token))


if __name__ == "__main__":
    with open("config/config.toml") as file:
        config: BotConfig = toml.load(file)  # pyright: ignore[reportAssignmentType]
    try:
        run(main(config))
    except KeyboardInterrupt:
        pass
