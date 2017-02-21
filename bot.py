from discord.ext.commands import Bot
from discord.ext.commands.errors import CommandNotFound, MissingRequiredArgument
from aiohttp import ClientSession

class BeattieBot(Bot):
    async def reply(self, ctx, message):
        return await ctx.send(f'{ctx.message.author.mention}\n{message}')

    async def handle_error(self, exception, ctx):
        if isinstance(exception, MissingRequiredArgument):
            await ctx.send('Missing required arguments.')
        elif not isinstance(exception, CommandNotFound):
            await ctx.send('Generic error handler triggered. '
                           'This should never happen.')
            try:
                raise exception.original
            except AttributeError:
                raise exception

    async def on_ready(self):
        self.session = ClientSession()
        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------')

    async def on_message(self, message):
        msg = message.content.split(None, 1)
        msg[0] = msg[0].lower()
        message.content = ' '.join(msg)
        await self.process_commands(message)

    async def on_command_error(self, exception, ctx):
        if not hasattr(ctx.command, 'on_error'):
            await self.handle_error(exception, ctx)
