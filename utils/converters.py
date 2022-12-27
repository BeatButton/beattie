from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from discord.ext.commands import BadArgument, Converter
from recurrent import RecurringEvent

from context import BContext
from schema.remind import Timezone
from utils.etc import UTC

GMT_TRANS = str.maketrans("+-", "-+")


class TimeConverter(Converter):
    async def convert(self, ctx: BContext, argument: str) -> RecurringEvent | datetime:
        async with ctx.bot.db.get_session() as s:
            tz = (
                await s.select(Timezone)
                .where(Timezone.user_id == ctx.author.id)  # type: ignore
                .first()
            )

        if tz:
            tz = ZoneInfo(tz.timezone)
        else:
            tz = UTC

        now = datetime.now().astimezone(tz)

        event = RecurringEvent(now)
        time: str | datetime | None = event.parse(argument)
        if time is None:
            raise BadArgument
        elif isinstance(time, str):
            return event
        else:
            return time.replace(tzinfo=tz)


class TimezoneConverter(Converter):
    async def convert(self, ctx: BContext, argument: str) -> ZoneInfo:
        try:
            return ZoneInfo(argument)
        except ZoneInfoNotFoundError as e:
            if argument.startswith(("GMT", "UTC")):
                try:
                    return ZoneInfo(
                        f"Etc/{argument.replace('UTC', 'GMT').translate(GMT_TRANS)}"
                    )
                except ZoneInfoNotFoundError:
                    raise BadArgument("Not a time zone", e.args[0])
            else:
                raise BadArgument("Not a time zone", e.args[0])
