import discord

class Paginator:
    """Paginates between a list of embeds."""
    def __init__(self, ctx, pages):
        self.ctx = ctx
        self.pages = pages
        self.message = None
        self.curr = 0
                
    async def run(self):
        self.message = await self.ctx.send(embed=self.pages[0])
        self.ctx.bot.add_listener(self.on_reaction_add)
        for reaction in self.handlers:
            await self.message.add_reaction(reaction)

    async def on_reaction_add(self, reaction, user):
        if reaction.message.id != self.message.id:
            return

        if user.id != self.ctx.bot.user.id:
            try:
                await self.message.remove_reaction(reaction, user)
            except discord.Forbidden:
                pass

        if user.id != self.ctx.author.id:
            return

        handler = self.handlers.get(str(reaction.emoji))
        if handler is not None:
            await handler(self)

    async def update(self):
        await self.message.edit(embed=self.pages[self.curr])

    async def first(self):
        self.curr = 0        
        await self.update()

    async def next(self):
        if self.curr == len(self.pages) - 1:
            return
        self.curr += 1
        await self.update()
        
    async def back(self):
        if self.curr == 0:
            return
        self.curr -= 1
        await self.update()

    async def last(self):
        self.curr = len(self.pages) - 1
        await self.update()

    async def stop(self):
        self.ctx.bot.remove_listener(self.on_reaction_add)
        await self.message.delete()
        
    handlers = {
        '⏮': first,
        '◀': back,
        '⏹': stop,
        '▶': next,
        '⏭': last,
    }
