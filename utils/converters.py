from datetime import datetime
from typing import Optional, Union

from discord.ext.commands import BadArgument, Context, Converter
from recurrent.event_parser import RecurringEvent


class Time(Converter):
    async def convert(
        self, ctx: Context, argument: str
    ) -> Union[RecurringEvent, datetime]:
        event = RecurringEvent()
        time: Optional[Union[str, datetime]] = event.parse(argument)
        if time is None:
            raise BadArgument
        elif isinstance(time, str):
            return event
        else:
            return time
