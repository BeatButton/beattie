#!/usr/bin/env python3
import asyncio
import aiohttp
import platform
import sys
from pathlib import Path

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

extensions = [f"cogs.{f.stem}" for f in Path("cogs").glob("*.py")]
extensions.append("jishaku")


async def main() -> None:
    bot = BeattieBot(tuple(prefixes), debug=debug)
    async with bot:
        bot.session = aiohttp.ClientSession()
        await bot.db.connect()
        await bot.config.async_init()
        for extension in extensions:
            try:
                await bot.load_extension(extension)
            except Exception as e:
                print(f"Failed to load extension {extension}\n{type(e).__name__}: {e}")

        await bot.start(token)


asyncio.run(main())
