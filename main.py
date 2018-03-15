#!/usr/bin/env python3
import asyncio
from datetime import datetime
import logging
import lzma
from pathlib import Path
import os
import sys
import tarfile

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
    prefixes = [config['self_prefix']]
    token = config['self']
elif config['debug'] or debug:
    prefixes = [config['test_prefix']]
    token = config['test_token']
else:
    prefixes = config['prefixes']
    token = config['token']
bot = BeattieBot(when_mentioned_or(*prefixes), self_bot=self_bot)

logger = logging.getLogger('discord')
if self_bot:
    logger.setLevel(logging.CRITICAL)
else:
    old_logs = Path('.').glob('discord*.log')
    logname = 'logs.tar'
    if os.path.exists(logname):
        mode = 'a'
    else:
        mode = 'w'
    with tarfile.open(logname, mode) as tar:
        for log in old_logs:
            with open(log, 'rb') as fp:
                data = lzma.compress(fp.read())
            name = f'{log.name}.xz'
            with open(name, 'wb') as fp:
                fp.write(data)
            tar.add(name)
            os.remove(name)
            log.unlink()

    logger.setLevel(logging.DEBUG)
    now = datetime.utcnow()
    filename = now.strftime('discord%Y%m%d%H%M.log')
    handler = logging.FileHandler(
        filename=filename, encoding='utf-8', mode='w')
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
