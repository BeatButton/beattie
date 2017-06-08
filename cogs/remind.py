import asyncio
from collections import namedtuple
from datetime import datetime

from discord.ext import commands

from schema.remind import Table, Message
from utils.converters import Time
from utils.etc import reverse_insort


Task = namedtuple('Task', 'time channel message')


class Remind:
    def __init__(self, bot):
        self.bot = bot
        self.queue = []
        self.db = self.bot.db
        self.db.bind_tables(Table)
        self.timer = self.bot.loop.create_task(asyncio.sleep(0))
        self.bot.loop.create_task(self.init())

    async def init(self):
        await self.bot.wait_until_ready()
        if not self.bot.user.bot:
            return
        async with self.db.get_session() as s:
            query = s.select(Message).order_by(Message.time)
            self.queue = [Task(*record.to_dict().values())
                          async for record in await query.all()]
        self.queue.sort(reverse=True)
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
        await ctx.send(f"Okay, I'll remind you.")

    async def schedule_message(self, time, channel, message):
        async with self.db.get_session() as s:
            await s.add(Message(time=time, channel=channel, message=message))
        task = Task(time, channel, message)
        if not self.queue or task < self.queue[-1]:
            self.queue.append(task)
            self.timer.cancel()
            await self.start_timer()
        else:
            reverse_insort(self.queue, task, hi=len(self.queue) - 1)

    async def send_message(self, task):
        channel = self.bot.get_channel(task.channel)
        await channel.send(task.message)
        async with self.db.get_session() as s:
            query = ('DELETE FROM message WHERE '
                     'time = $1 AND channel = $2 AND message = $3;')
            await s.execute(query, {f'param_{i}': val
                                    for i, val in enumerate(task)})

    async def start_timer(self):
        self.timer = self.bot.loop.create_task(self.sleep())

    async def sleep(self):
        while self.queue:
            delta = (self.queue[-1].time - datetime.now()).total_seconds()
            if delta <= 0:
                await self.send_message(self.queue.pop())
            else:
                await asyncio.sleep(min(delta, 3_000_000))


def setup(bot):
    bot.add_cog(Remind(bot))
