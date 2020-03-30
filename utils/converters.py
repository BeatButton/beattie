from datetime import datetime
from time import mktime
from typing import Any

from parsedatetime import Calendar  # type: ignore
from discord.ext.commands import BadArgument, Converter, Context


class Time(Converter):
    def __init__(self) -> None:
        self.cal: Calendar = Calendar()  # type: ignore

    async def convert(self, ctx: Context, argument: str) -> datetime:
        time: Any
        code: int
        time, code = self.cal.parse(argument)
        if code == 0:
            raise BadArgument
        return datetime.fromtimestamp(mktime(time))
