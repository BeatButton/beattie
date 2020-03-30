from __future__ import annotations  # type: ignore

from discord.ext import commands
from discord.ext.commands import Context

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discord.ext.commands import _CheckDecorator


def is_owner_or(**perms: bool) -> _CheckDecorator:
    async def predicate(ctx: Context) -> bool:
        if await ctx.bot.is_owner(ctx.author):
            return True
        permissions = ctx.channel.permissions_for(ctx.author)  # type: ignore
        return all(
            getattr(permissions, perm, None) == value for perm, value in perms.items()
        )

    return commands.check(predicate)
