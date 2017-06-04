import asyncio
from bisect import insort_left
from collections import namedtuple
from datetime import datetime
import operator

import asyncpg
from discord.ext import commands
import yaml

from utils.converters import Time


Task = namedtuple('Task', 'time channel message')


class Remind:
    def __init__(self, bot):
        with open('config/config.yaml') as file:
            data = yaml.load(file)
        self.password = data.get('config_password', '')
        self.bot = bot
        self.queue = []
        self.bot.loop.create_task(self.init())

    async def init(self):
        self.pool = await asyncpg.create_pool(user='beattie',
                                              password=self.password,
                                              database='schedule',
                                              host='localhost')
        async with self.pool.acquire() as conn:
            query = 'SELECT * from message;'
            for record in await conn.fetch(query):
                insort_left(self.queue, Task(*record))
        await self.start_timer()

    @commands.command()
    async def remind(self, ctx, *, inp):
        """Have the bot remind you about something.
           First put time, then optionally a topic after a comma."""
        try:
            time, topic = (i.strip() for i in inp.split(','))
        except ValueError:
            time, topic = inp, 'something'
        time = await Time().convert(ctx, time)
        message = (f'{ctx.author.mention}\n'
                   f'You asked to be reminded about {topic}.')
        await self.schedule_message(time, ctx.channel.id, message)

    async def schedule_message(self, time, channel, message):
        args = (time, channel, message)
        async with self.pool.acquire() as conn:
            query = 'INSERT INTO message VALUES($1, $2, $3);'
            await conn.execute(query, *args)
        if self.queue:
            old = self.queue[0]
        else:
            old = None
        task = Task(*args)
        insort_left(self.queue, task)
        if old is not self.queue[0]:
            if self.timer:
                self.timer.cancel()
            await self.start_timer()

    async def send_message(self, task):
        channel = self.bot.get_channel(task.channel)
        await channel.send(task.message)
        async with self.pool.acquire() as conn:
            query = ('DELETE FROM message WHERE '
                     'channel = $1 AND message = $2 AND time = $3;')
            await conn.execute(query, *task)

    async def start_timer(self):
        self.timer = self.bot.loop.create_task(self.sleep())

    async def sleep(self):
        while self.queue:
            delta = (self.queue[0].time - datetime.now()).total_seconds()
            if delta <= 0:
                await self.send_message(self.queue[0])
                del self.queue[0]
            else:
                await asyncio.sleep(min(delta, 1_000_000))


def setup(bot):
    bot.add_cog(Remind(bot))
