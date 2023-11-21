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
    bots: list[BeattieBot] = [
        BeattieBot(tuple(prefixes), pool=pool, debug=debug) for _ in tokens
    ]
    async with MultiAsyncWith(bots) as bots:
        bots_tokens = list(zip(bots, tokens))
        bot_ids: set[int] = set()
        shared = Shared(bot_ids)
        for bot in bots:
            bot.shared = shared
        for bot, token in bots_tokens[:-1]:
            asyncio.create_task(bot.start(token))
        bot, token = bots_tokens[-1]
        await bot.start(token)


asyncio.run(main())
