from datetime import datetime
from typing import Optional

from discord.ext.commands import BadArgument, Context, Converter
from recurrent.event_parser import RecurringEvent


class TimeConverter(Converter):
    async def convert(self, ctx: Context, argument: str) -> RecurringEvent | datetime:
        event = RecurringEvent()
        time: Optional[str | datetime] = event.parse(argument)
        if time is None:
            raise BadArgument
        elif isinstance(time, str):
            return event
        else:
            return time
