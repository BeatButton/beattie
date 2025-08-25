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

if platform.system() != "Windows":
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

with open("config/config.toml") as file:
    config: BotConfig = toml.load(file)  # pyright: ignore[reportAssignmentType]

debug = config.get("debug") or "debug" in sys.argv
if debug:
    prefixes = config["test_prefixes"]
    tokens = [config["test_token"]]
else:
    prefixes = config["prefixes"]
    tokens = config["tokens"]

password = config.get("config_password", "")
dsn = f"postgresql://beattie:{password}@localhost/beattie"


async def main():
    pool = await asyncpg.create_pool(dsn)
    shared = Shared(prefixes=tuple(prefixes), pool=pool, debug=debug)
    await shared.async_init()
    bots: list[BeattieBot] = [BeattieBot(shared) for _ in tokens]
    async with MultiAsyncWith(bots) as bots, asyncio.TaskGroup() as tg:
        bots_tokens = [*zip(bots, tokens)]
        shared.bot_ids = set()
        shared.bots = []
        for bot in bots:
            bot.shared = shared
            shared.bots.append(bot)
        for bot, token in bots_tokens:
            tg.create_task(bot.start(token))


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
