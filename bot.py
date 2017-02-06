from discord.ext.commands import Bot
from discord.ext.commands.errors import CommandNotFound, MissingRequiredArgument

class BeattieBot(Bot):
    def __init__(self, *args, **kwargs):
        if kwargs.get('self_bot', False):
            self.say = self.reply = self.edit
        super().__init__(*args, **kwargs)

    async def reply(self, ctx, message):
        return await ctx.channel.send(f'{ctx.message.author.mention}\n{message}')

    async def say(self, ctx, message):
        return await ctx.channel.send(message)

    async def edit(self, ctx, message):
        await ctx.message.edit(content=f'{ctx.message.content}\n{message}')
        return ctx.message

    async def handle_error(self, exception, ctx):
        if isinstance(exception, MissingRequiredArgument):
            await self.say(ctx, 'Missing required arguments.')
        elif not isinstance(exception, CommandNotFound):
            await self.say(ctx, 'Generic error handler triggered. '
                           'This should never happen.')
            if hasattr(exception, 'original'):
                exception = exception.original
            raise exception

    async def on_ready(self):
        self.command_prefix.append(self.user.mention + ' ')
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
        if ctx.command is None or not hasattr(ctx.command, 'on_error'):
            await self.handle_error(exception, ctx)
