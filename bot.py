import discord
from discord.ext.commands import Bot, Context, errors
from aiohttp import ClientSession


class BContext(Context):
    async def reply(self, content, sep='\n'):
        if self.me.bot:
            content = f'{self.author.mention}{sep}{content}'
        return await self.send(content)

    async def send(self, content=None, **kwargs):
        if self.me.bot:
            return await super().send(content, **kwargs)
        elif content:
            content = f'{self.message.content}\n{content}'
            await self.message.edit(content=content)
            return self.message


class BeattieBot(Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = ClientSession(loop=self.loop)

    def __del__(self):
        self.session.close()

    async def handle_error(self, e, ctx):
        if isinstance(e, errors.MissingRequiredArgument):
            await ctx.send('Missing required arguments.')
        elif isinstance(e, errors.BadArgument):
            await ctx.send('Bad arguments.')
        elif isinstance(e, errors.CheckFailure):
            await ctx.send('You lack the required permissions.')
        elif isinstance(e, errors.CommandInvokeError):
            if (isinstance(e.original, discord.errors.HTTPException)
               and e.original.response.status == 400):
                await ctx.send('Message content too long.')
        elif not isinstance(e, errors.CommandNotFound):
            await ctx.send('Generic error handler triggered. '
                           'This should never happen.')
            try:
                raise e.original
            except AttributeError:
                raise e

    async def on_ready(self):
        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------')

    async def on_message(self, message):
        ctx = await self.get_context(message, cls=BContext)
        if ctx.prefix is not None:
            ctx.command = self.commands.get(ctx.invoked_with.lower())
            await self.invoke(ctx)

    async def on_command_error(self, e, ctx):
        if not hasattr(ctx.command, 'on_error'):
            await self.handle_error(e, ctx)
