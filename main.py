#!/usr/bin/env python
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

if self_bot:
    prefixes = ['self>']
    token = config['self']
elif config['debug']:
    prefixes = [config['test_prefix']]
    token = config['test_token']
else:
    prefixes = config['prefixes']
    token = config['token']
bot = BeattieBot(when_mentioned_or(*prefixes), self_bot=self_bot)

extensions = [f'cogs.{f.stem}' for f in Path('cogs').glob('*.py')]

for extension in extensions:
    try:
        bot.load_extension(extension)
    except Exception as e:
        print(f'Failed to load extension {extension}\n{type(e).__name__}: {e}')

if self_bot:
    logger = logging.getLogger('discord')
    logger.setLevel(logging.CRITICAL)
else:
    logger = logging.getLogger('discord')
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(
        filename='discord.log', encoding='utf-8', mode='w')
    handler.setFormatter(
        logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
    logger.addHandler(handler)
bot.logger = logger


bot.run(token, bot=not self_bot)
