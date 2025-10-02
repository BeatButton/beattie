from __future__ import annotations

from typing import TYPE_CHECKING

from discord.ext import commands
from discord.ext.commands import BadArgument, Converter, FlagConverter
from discord.ext.commands.converter import _convert_to_bool
from discord.utils import find

from beattie.utils.converters import RangesConverter

from .translator import DONT, Language

if TYPE_CHECKING:
    from beattie.context import BContext

    from .cog import Crosspost


class Site(Converter):
    async def convert(self, ctx: BContext, argument: str) -> str:
        command = ctx.command
        assert command is not None
        cog = command.cog
        if not any(site.name == argument for site in cog.sites):
            raise BadArgument
        return argument


class LanguageConverter(Converter):
    async def convert(self, ctx: BContext, argument: str) -> Language:
        cog: Crosspost = ctx.bot.get_cog("Crosspost")  # type: ignore
        if (translator := cog.translator) is None:
            msg = "no translator available"
            raise BadArgument(msg)

        langs = await translator.languages()

        try:
            on = _convert_to_bool(argument)
        except BadArgument:
            pass
        else:
            if on:
                return langs["en"]
            return DONT

        lower = argument.lower()
        if lang := langs.get(lower):
            return lang

        if lang := find(lambda lang: lang.name.lower() == lower, langs.values()):
            return lang

        msg = f'Failed to find language with name or code "{argument}".'
        raise BadArgument(msg)


class PostFlags(FlagConverter, case_insensitive=True, delimiter="="):
    pages: int | list[tuple[int, int]] | None = commands.flag(
        converter=int | RangesConverter | None,
    )
    page: int | None
    text: bool | None

    def __bool__(self) -> bool:
        return any(prop is not None for prop in vars(self).values())
