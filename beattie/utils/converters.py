import re
from collections.abc import Collection
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from recurrent import RecurringEvent

from discord.ext.commands import BadArgument, Converter

from beattie.context import BContext
from beattie.utils.etc import UTC

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
        elif isinstance(time, str):
            return event
        else:
            return time.replace(tzinfo=tz)


class TimezoneConverter(Converter):
    async def convert(self, ctx: BContext, argument: str) -> ZoneInfo:
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
                    raise BadArgument("Not a time zone", e.args[0])
            else:
                raise BadArgument("Not a time zone", e.args[0])


class SuitConverter(Converter):
    async def convert(self, ctx: BContext, argument: str) -> Collection[str]:
        if not argument:
            return SUITS

        suits = set(argument.lower().split())
        if "minor" in suits:
            suits.remove("minor")
            suits.update(MINOR)

        if bad_suits := suits - SUITS:
            raise BadArgument("Not a suit", ", ".join(bad_suits))

        return suits


RANGE_EXPR = re.compile(r"^(?:(?:\d+(?:-\d+)?),?)+$")


class RangesConverter(Converter):
    async def convert(self, ctx: BContext, argument: str) -> list[tuple[int, int]]:
        if not RANGE_EXPR.match(argument):
            raise BadArgument("Failed to parse ranges.")

        out = []
        for part in argument.split(","):
            if not part:
                continue
            start, _, end = part.partition("-")
            out.append((int(start), int(end or start)))

        return out
