import asyncio
import json
import logging

import discord
from discord.ext.commands import when_mentioned_or

from bot import BeattieBot

try:
    import uvloop
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

with open('config.json') as file:
    config = json.load(file)

token = config['token']

bot = BeattieBot(when_mentioned_or('>'))

for extension in ('default', 'rpg', 'eddb', 'repl', 'wolfram'):
    try:
        bot.load_extension(extension)
    except Exception as e:
        print(f'Failed to load extension {extension}\n{type(e).__name__}: {e}')

logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
handler = logging.FileHandler(
    filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(
    logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)
bot.logger = logger
bot.run(token)
