from datetime import datetime
from time import mktime
from typing import Any

from discord.ext.commands import BadArgument, Context, Converter
from parsedatetime import Calendar


class Time(Converter):
    def __init__(self) -> None:
        self.cal: Calendar = Calendar()

    async def convert(self, ctx: Context, argument: str) -> datetime:
        time: Any
        code: int
        time, code = self.cal.parse(argument)
        if code == 0:
            raise BadArgument
        return datetime.fromtimestamp(mktime(time))
