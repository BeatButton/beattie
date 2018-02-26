#!/usr/bin/env python3
import asyncio
import logging
from pathlib import Path
import os
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

os.chdir(os.path.dirname(os.path.abspath(__file__)))

with open('config/config.yaml') as file:
    config = yaml.load(file)

self_bot = 'self' in sys.argv
debug = 'debug' in sys.argv
loop = asyncio.get_event_loop()

if self_bot:
    prefixes = ['self>']
    token = config['self']
elif config['debug'] or debug:
    prefixes = [config['test_prefix']]
    token = config['test_token']
    loop.set_debug(True)
else:
    prefixes = config['prefixes']
    token = config['token']
bot = BeattieBot(when_mentioned_or(*prefixes), self_bot=self_bot)



logger = logging.getLogger('discord')
if self_bot:
    logger.setLevel(logging.CRITICAL)
else:
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(
        filename='discord.log', encoding='utf-8', mode='w')
    handler.setFormatter(
        logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
    logger.addHandler(handler)
bot.logger = logger

extensions = [f'cogs.{f.stem}' for f in Path('cogs').glob('*.py')]

for extension in extensions:
    try:
        bot.load_extension(extension)
    except Exception as e:
        print(f'Failed to load extension {extension}\n{type(e).__name__}: {e}')

bot.run(token, bot=not self_bot)
