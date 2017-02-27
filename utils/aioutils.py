import functools

import aiofiles
import aitertools

aopen = functools.partial(aiofiles.open, encoding='utf-8')


async def areader(aiofile):
    async for line in aiofile:
        yield [val.strip() for val in line.split(',')]


async def make_batches(iterable, size):
    iterator = await aitertools.aiter(iterable)
    async for first in iterator:
        yield aitertools.chain([first], aitertools.islice(iterator, size - 1))
