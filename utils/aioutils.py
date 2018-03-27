import asyncio
import functools

import aiofiles
import aitertools

aopen = functools.partial(aiofiles.open, encoding='utf-8')


async def areader(aiofile):
    """An async csv reader."""
    async for line in aiofile:
        yield [val.strip() for val in line.split(',')]


async def make_batches(iterable, size):
    """Make batches of size from iterable. This would be equivalent to slices
    from 0 to size, then size to size * 2, etc, of a list of the iterable."""
    iterator = await aitertools.aiter(iterable)
    async for first in iterator:
        yield aitertools.chain([first], aitertools.islice(iterator, size - 1))


def do_every(seconds, coro, *args, **kwargs):
    async def task():
        while True:
            await asyncio.sleep(seconds)
            await coro(*args, **kwargs)
    return asyncio.get_event_loop().create_task(task())