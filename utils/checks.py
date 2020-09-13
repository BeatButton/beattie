from __future__ import annotations

from typing import TYPE_CHECKING

from discord import Member, TextChannel
from discord.ext import commands
from discord.ext.commands import Context

if TYPE_CHECKING:
    from discord.ext.commands.core import _CheckDecorator


def is_owner_or(**perms: bool) -> _CheckDecorator:
    async def predicate(ctx: Context) -> bool:
        author = ctx.author
        channel = ctx.channel
        if not isinstance(channel, TextChannel):
            return True
        assert isinstance(author, Member)
        if await ctx.bot.is_owner(author):
            return True
        permissions = channel.permissions_for(author)
        return all(
            getattr(permissions, perm, None) == value for perm, value in perms.items()
        )

    return commands.check(predicate)
