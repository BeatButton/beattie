from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from recurrent import RecurringEvent

from discord.ext.commands import BadArgument, Converter

from beattie.utils.etc import UTC

if TYPE_CHECKING:
    from collections.abc import Collection

    from beattie.context import BContext

GMT_TRANS = str.maketrans("+-", "-+")
MINOR = frozenset(("cups", "swords", "wands", "pentacles"))
SUITS = frozenset((*MINOR, "major"))


class TimeConverter(Converter):
    async def convert(self, ctx: BContext, argument: str) -> RecurringEvent | datetime:
        async with ctx.bot.pool.acquire() as conn:
            tz = await conn.fetchval(
                "SELECT timezone FROM timezone WHERE user_id = $1",
                ctx.author.id,
            )

        if tz:
            tz = ZoneInfo(tz)
        else:
            tz = UTC

        event = RecurringEvent(datetime.now(tz))
        time: str | datetime | None = event.parse(argument)
        if time is None:
            raise BadArgument
        if isinstance(time, str):
            return event
        return time.replace(tzinfo=tz)


class TimezoneConverter(Converter):
    async def convert(self, _ctx: BContext, argument: str) -> ZoneInfo:
        argument = argument.replace(" ", "_")
        try:
            return ZoneInfo(argument)
        except ZoneInfoNotFoundError as e:
            if argument.startswith(("GMT", "UTC")):
                try:
                    return ZoneInfo(
                        f"Etc/{argument.replace('UTC', 'GMT').translate(GMT_TRANS)}",
                    )
                except ZoneInfoNotFoundError:
                    msg = "Not a time zone"
                    raise BadArgument(msg, e.args[0]) from None
            else:
                msg = "Not a time zone"
                raise BadArgument(msg, e.args[0]) from None


class SuitConverter(Converter):
    async def convert(self, _ctx: BContext, argument: str) -> Collection[str]:
        if not argument:
            return SUITS

        suits = set(argument.lower().split())
        if "minor" in suits:
            suits.remove("minor")
            suits.update(MINOR)

        if bad_suits := suits - SUITS:
            msg = "Not a suit"
            raise BadArgument(msg, ", ".join(bad_suits))

        return suits


RANGE_EXPR = re.compile(r"^(?:(?:\d+(?:-\d+)?),?)+$")


class RangesConverter(Converter):
    async def convert(self, _ctx: BContext, argument: str) -> list[tuple[int, int]]:
        if not RANGE_EXPR.match(argument):
            msg = "Failed to parse ranges."
            raise BadArgument(msg)

        out = []
        for part in argument.split(","):
            if not part:
                continue
            start, _, end = part.partition("-")
            out.append((int(start), int(end or start)))

        return out
