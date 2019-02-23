import asyncio
from collections import namedtuple
from datetime import datetime

from discord.ext import commands

from schema.remind import Table, Message
from utils.converters import Time
from utils.etc import reverse_insort


Task = namedtuple('Task', 'time channel text')


class Remind(commands.Cog):
    def __init__(self, bot):
        self.queue = []
        self.loop = bot.loop
        self.db = bot.db
        self.bot = bot
        self.db.bind_tables(Table)
        self.timer = self.loop.create_task(asyncio.sleep(0))
        self.loop.create_task(self.__init())

    def cog_unload(self):
        self.timer.cancel()

    async def __init(self):
        await self.bot.wait_until_ready()
        if not self.bot.user.bot:
            return
        await Message.create(if_not_exists=True)
        async with self.db.get_session() as s:
            query = s.select(Message).order_by(Message.time, sort_order='desc')
            self.queue = [Task(*record.to_dict().values())
                          async for record in await query.all()]
        await self.start_timer()

    @commands.command()
    async def remind(self, ctx, time: Time, *, topic: commands.clean_content = None):
        """Have the bot remind you about something.
           First put time (in quotes if there are spaces), then topic"""
        if topic is not None:
            topic = f'that {topic}'
        else:
            topic = 'about something'
        message = (f'{ctx.author.mention}\n'
                   f'You asked to be reminded {topic}.')
        await self.schedule_message(time, ctx.channel.id, message)
        await ctx.send(f"Okay, I'll remind you.")

    @remind.error
    async def remind_error(self, ctx, e):
        if isinstance(e, commands.BadArgument):
            await ctx.send('Bad input. Valid input examples:\n'
                           'remind 10m pizza\n'
                           'remind "two days" check progress'
                           )
        else:
            await ctx.bot.handle_error(ctx, e)

    async def schedule_message(self, time, channel, text):
        async with self.db.get_session() as s:
            await s.add(Message(time=time, channel=channel, text=text))
        task = Task(time, channel, text)
        if not self.queue or task < self.queue[-1]:
            self.queue.append(task)
            self.timer.cancel()
            await self.start_timer()
        else:
            reverse_insort(self.queue, task, hi=len(self.queue) - 1)

    async def send_message(self, task):
        channel = self.bot.get_channel(task.channel)
        if channel is not None:
            await channel.send(task.text)
        async with self.db.get_session() as s:

            query = s.select(Message).where((Message.time == task.time)
                                            & (Message.channel == task.channel)
                                            & (Message.text == task.text))
            message = await query.first()
            await s.remove(message)

    async def start_timer(self):
        self.timer = self.loop.create_task(self.sleep())

    async def sleep(self):
        while self.queue:
            delta = (self.queue[-1].time - datetime.now()).total_seconds()
            if delta <= 0:
                await self.send_message(self.queue.pop())
            else:
                await asyncio.sleep(min(delta, 3_000_000))


def setup(bot):
    bot.add_cog(Remind(bot))
