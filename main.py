#!/usr/bin/env python3
import asyncio
import logging
from pathlib import Path
import sys

from discord.ext.commands import when_mentioned_or
import yaml

from bot import BeattieBot

try:
    import uvloop
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

with open('config/config.yaml') as file:
    config = yaml.load(file)

self_bot = 'self' in sys.argv
debug = 'debug' in sys.argv
loop = asyncio.get_event_loop()

if self_bot:
    prefixes = [config['self_prefix']]
    token = config['self']
elif config['debug'] or debug:
    prefixes = [config['test_prefix']]
    token = config['test_token']
else:
    prefixes = config['prefixes']
    token = config['token']
bot = BeattieBot(when_mentioned_or(*prefixes), self_bot=self_bot)

if self_bot or debug:
    logger = logging.getLogger('discord')
    logger.setLevel(logging.CRITICAL)
    bot.logger = logger
else:
    bot.new_logger()
    bot.loop.create_task(bot.swap_logs(False))

extensions = [f'cogs.{f.stem}' for f in Path('cogs').glob('*.py')]

for extension in extensions:
    try:
        bot.load_extension(extension)
    except Exception as e:
        print(f'Failed to load extension {extension}\n{type(e).__name__}: {e}')

bot.run(token, bot=not self_bot)
