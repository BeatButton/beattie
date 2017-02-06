import asyncio
import json
import sys

from bot import BeattieBot

try:
    import uvloop
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

with open('config.json') as file:
    config = json.load(file)

if 'self' in sys.argv:
    token = config['self']
    self_bot = True
    prefix = ['b>']
else:
    token = config['token']
    self_bot = False
    prefix = ['>']

bot = BeattieBot(command_prefix=prefix, self_bot=self_bot)

for extension in ('default', 'eddb', 'rpg'):
    try:
        bot.load_extension(extension)
    except Exception as e:
        print(f'Failed to load extension {extension}\n{type(e).__name__}: {e}')

bot.run(token, bot=not self_bot)
