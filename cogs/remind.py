import asyncio
from bisect import insort_left
from collections import namedtuple
from datetime import datetime

from discord.ext import commands

from schema.remind import Table, Message
from utils.converters import Time


Task = namedtuple('Task', 'time channel message')


class Remind:
    def __init__(self, bot):
        self.bot = bot
        self.queue = []
        self.db = self.bot.db
        self.db.bind_tables(Table)
        self.timer = None
        self.bot.loop.create_task(self.init())

    async def init(self):
        await self.bot.wait_until_ready()
        async with self.db.get_session() as s:
            query = s.select(Message).order_by(Message.time)
            self.queue = [Task(*record.to_dict().values())
                          async for r in await query.all()]
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
        if self.queue:
            old = self.queue[0]
        else:
            old = None
        task = Task(time, channel, message)
        insort_left(self.queue, task)
        if old is not self.queue[0]:
            if self.timer:
                self.timer.cancel()
                self.timer = None
            await self.start_timer()

    async def send_message(self, task):
        channel = self.bot.get_channel(task.channel)
        await channel.send(task.message)
        async with self.db.get_session() as s:
            message = task.message.replace("'", "''")
            query = ('DELETE FROM message WHERE '
                     f"time = '{task.time}' "
                     f'AND channel = {task.channel} '
                     f"AND message = '{message}';")
            await s.execute(query, {})

    async def start_timer(self):
        self.timer = self.bot.loop.create_task(self.sleep())

    async def sleep(self):
        try:
            while self.queue:
                delta = (self.queue[0].time - datetime.now()).total_seconds()
                if delta <= 0:
                    await self.send_message(self.queue[0])
                    del self.queue[0]
                else:
                    await asyncio.sleep(min(delta, 3_000_000))
        except Exception as e:
            print(e)


def setup(bot):
    bot.add_cog(Remind(bot))
