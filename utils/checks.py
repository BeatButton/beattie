from __future__ import annotations

from typing import Callable, TypeVar

from discord import Member
from discord.ext import commands
from discord.ext.commands import Context

from utils.type_hints import GuildMessageable

T = TypeVar("T")


def is_owner_or(**perms: bool) -> Callable[[T], T]:
    async def predicate(ctx: Context) -> bool:
        author = ctx.author
        channel = ctx.channel
        if ctx.guild is None:
            return True
        assert isinstance(author, Member)
        assert isinstance(channel, GuildMessageable)
        if await ctx.bot.is_owner(author):
            return True
        permissions = channel.permissions_for(author)
        return all(
            getattr(permissions, perm, None) == value for perm, value in perms.items()
        )

    return commands.check(predicate)
