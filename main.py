#!/usr/bin/env python3
import asyncio
import logging
import platform
import sys
from pathlib import Path

import toml
from discord.ext.commands import when_mentioned_or

from bot import BeattieBot

if platform.system() != "Windows":
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

with open("config/config.toml") as file:
    config = toml.load(file)

debug = "debug" in sys.argv
loop = asyncio.get_event_loop()

if config.get("debug") or debug:
    prefixes = [config["test_prefix"]]
    token = config["test_token"]
else:
    prefixes = config["prefixes"]
    token = config["token"]
bot = BeattieBot(when_mentioned_or(*prefixes))

if debug:
    logger = logging.getLogger("discord")
    logger.setLevel(logging.DEBUG)
    bot.logger = logger
else:
    bot.new_logger()
    bot.loop.create_task(bot.swap_logs(False))

extensions = [f"cogs.{f.stem}" for f in Path("cogs").glob("*.py")]
extensions.append("jishaku")

for extension in extensions:
    try:
        bot.load_extension(extension)
    except Exception as e:
        print(f"Failed to load extension {extension}\n{type(e).__name__}: {e}")

bot.run(token)
