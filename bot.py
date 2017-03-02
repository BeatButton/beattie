from discord.ext.commands import Bot, Context, errors
from aiohttp import ClientSession


class BContext(Context):
    async def reply(self, content, sep='\n'):
        return await self.send(f'{self.message.author.mention}{sep}{content}')


class BeattieBot(Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = ClientSession(loop=self.loop)

    def __del__(self):
        self.session.close()

    async def handle_error(self, exception, ctx):
        if isinstance(exception, errors.MissingRequiredArgument):
            await ctx.send('Missing required arguments.')
        elif isinstance(exception, errors.CheckFailure):
            await ctx.send('You lack the required permissions.')
        elif not isinstance(exception, errors.CommandNotFound):
            await ctx.send('Generic error handler triggered. '
                           'This should never happen.')
            try:
                raise exception.original
            except AttributeError:
                raise exception

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

    async def on_command_error(self, exception, ctx):
        if not hasattr(ctx.command, 'on_error'):
            await self.handle_error(exception, ctx)
