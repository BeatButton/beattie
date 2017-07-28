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


class Union(Converter):
    def __init__(self, *converters):
        self.converters = converters

    async def convert(self, ctx, arg):
        for converter in self.converters:
            try:
                return await ctx.command.do_conversion(ctx, converter, arg)
            except (BadArgument, ValueError, TypeError):
                pass
        raise BadArgument('Conversion failed for {!r}'.format(self))

    def __repr__(self):
        names = (getattr(converter, '__name__', type(converter).__name__)
                 for converter in self.converters)  
        return '{}({})'.format(type(self).__name__, ', '.join(names))
