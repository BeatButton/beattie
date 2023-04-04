#!/usr/bin/env python3
import asyncio
import platform
import sys

import asyncpg
import toml

from bot import BeattieBot

if platform.system() != "Windows":
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

with open("config/config.toml") as file:
    config = toml.load(file)

debug = config.get("debug") or "debug" in sys.argv
if debug:
    prefixes = config["test_prefixes"]
    token = config["test_token"]
else:
    prefixes = config["prefixes"]
    token = config["token"]

password = config.get("config_password", "")
dsn = f"postgresql://beattie:{password}@localhost/beattie"


async def main():
    pool = await asyncpg.create_pool(dsn)
    assert pool is not None
    bot = BeattieBot(tuple(prefixes), pool=pool, debug=debug)
    async with bot:
        await bot.start(token)


asyncio.run(main())
