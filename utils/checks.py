from discord.ext import commands


def is_owner_or(**perms):
    async def predicate(ctx):
        owner = await ctx.bot.is_owner(ctx.author)
        permissions = ctx.channel.permissions_for(ctx.author)
        return all(getattr(permissions, perm, None) == value
                   for perm, value in perms.items()) or owner
    return commands.check(predicate)
