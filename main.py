#!/usr/bin/env python3
import asyncio
import platform
import sys

import asyncpg
import toml

from bot import BeattieBot, Shared
from utils.contextmanagers import MultiAsyncWith

if platform.system() != "Windows":
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

with open("config/config.toml") as file:
    config = toml.load(file)

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
    assert pool is not None
    shared = Shared(prefixes=tuple(prefixes), pool=pool, debug=debug)
    await shared.async_init()
    bots: list[BeattieBot] = [BeattieBot(shared) for _ in tokens]
    async with MultiAsyncWith(bots) as bots, asyncio.TaskGroup() as tg:
        bots_tokens = list(zip(bots, tokens))
        shared.bot_ids = set()
        shared.bots = list()
        for bot in bots:
            bot.shared = shared
            shared.bots.append(bot)
        for bot, token in bots_tokens:
            tg.create_task(bot.start(token))


asyncio.run(main())
