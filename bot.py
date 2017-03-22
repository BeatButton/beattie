import discord
from discord.ext.commands import Bot, Context, errors
from aiohttp import ClientSession

from utils import checks, contextmanagers


class BContext(Context):
    async def reply(self, content, sep='\n'):
        if self.me.bot:
            content = f'{self.author.mention}{sep}{content}'
        return await self.send(content)

    async def send(self, content=None, *, embed=None, **kwargs):
        if self.me.bot:
            return await super().send(content, embed=embed, **kwargs)
        elif content:
            content = f'{self.message.content}\n{content}'
            await self.message.edit(content=content)
            return self.message
        elif embed:
            await self.message.delete()
            return await super().send(embed=embed, **kwargs)

    def typing(self):
        if self.me.bot:
            return super().typing()
        else:
            return contextmanagers.null()


class BeattieBot(Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = ClientSession(loop=self.loop)

        @self.command(hidden=True)
        @checks.is_owner()
        async def reload(ctx, *, cog):
            self.unload_extension(cog)
            self.load_extension(cog)
            await ctx.send('Reload successful.')

    def __del__(self):
        self.session.close()

    async def handle_error(self, e, ctx):
        if isinstance(e, errors.MissingRequiredArgument):
            await ctx.send('Missing required arguments.')
        elif isinstance(e, errors.BadArgument):
            await ctx.send('Bad arguments.')
        elif isinstance(e, errors.CheckFailure):
            await ctx.send('You lack the required permissions.')
        elif (isinstance(e, errors.CommandInvokeError)
              and (isinstance(e.original, discord.errors.HTTPException)
              and e.original.response.status == 400)):
                await ctx.send('Message content too long.')
        elif not isinstance(e, errors.CommandNotFound):
            await ctx.send(f'{type(e).__name__}: {e}')
            raise e

    async def on_ready(self):
        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------')

    async def on_message(self, message):
        ctx = await self.get_context(message, cls=BContext)
        if ctx.prefix is not None:
            ctx.command = self.get_command(ctx.invoked_with.lower())
            await self.invoke(ctx)

    async def on_command_error(self, e, ctx):
        if not hasattr(ctx.command, 'on_error'):
            await self.handle_error(e, ctx)
