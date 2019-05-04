from datetime import datetime
from time import mktime

from discord.ext.commands import BadArgument, Converter
import parsedatetime


class Time(Converter):
    def __init__(self):
        self.cal = parsedatetime.Calendar()

    async def convert(self, ctx, argument):
        time, code = self.cal.parse(argument)
        if code == 0:
            raise BadArgument
        return datetime.fromtimestamp(mktime(time))
