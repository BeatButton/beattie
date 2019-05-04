from discord.ext import commands


def is_owner_or(**perms):
    async def predicate(ctx):
        if await ctx.bot.is_owner(ctx.author):
            return True
        permissions = ctx.channel.permissions_for(ctx.author)
        return all(
            getattr(permissions, perm, None) == value for perm, value in perms.items()
        )

    return commands.check(predicate)
