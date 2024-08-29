from __future__ import annotations

from typing import TYPE_CHECKING

from discord.ext import commands
from discord.ext.commands import BadArgument, Converter, FlagConverter

from beattie.utils.converters import RangesConverter

if TYPE_CHECKING:
    from .cog import Crosspost

    from beattie.context import BContext


class Site(Converter):
    async def convert(self, ctx: BContext, argument: str) -> str:
        command = ctx.command
        assert command is not None
        cog = command.cog
        assert isinstance(cog, Crosspost)
        if not any(site.name == argument for site in cog.sites):
            raise BadArgument
        return argument


class PostFlags(FlagConverter, case_insensitive=True, delimiter="="):
    pages: int | list[tuple[int, int]] | None = commands.flag(
        converter=int | RangesConverter | None
    )
    text: bool | None
