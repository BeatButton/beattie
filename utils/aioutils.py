import asyncio
import sys

DEFAULT = object()

async def anext(aiterable, default=DEFAULT):
    try:
        return await aiterable.__anext__()
    except StopAsyncIteration as e:
        if default is not DEFAULT:
            return default
        raise e from None

def aiter(obj):
    if hasattr(obj, '__aiter__'):
        return obj
    elif hasattr(obj, '__iter__'):
        return iter_to_aiter(obj)
    else:
        raise TypeError

async def iter_to_aiter(obj):
    for elem in obj:
        yield elem

async def achain(*aiters):
    for aiterator in aiters:
        aiterator = aiter(aiterator)
        async for elem in aiterator:
            yield elem

async def azip(*iters):
    sentinel = object()
    aiters = [aiter(it) for it in iters]
    while iterators:
        result = []
        for it in aiters:
            elem = await anext(it, sentinel)
            if elem is sentinel:
                return
            result.append(elem)
        yield tuple(result)

async def aenumerate(aiterator, start=0):
    async for elem in aiterator:
        yield start, elem
        start += 1

async def aislice(aiterator, *args):
    s = slice(*args)
    start = s.start or 0
    stop = s.stop or sys.maxsize
    step = s.step or 1
    indexes = iter(range(start, stop, step))
    try:
        next_idx = next(indexes)
    except StopIteration:
        for _ in azip(range(start), aiterator):
            pass
        return
    idx = 0
    try:
        async for idx, elem in aenumerate(aiterator):
            if idx == next_idx:
                yield elem
                next_idx = next(indexes)
    except StopIteration:
        for _ in zip(range(idx + 1, stop)):
            pass

async def areader(aiterable):
    """An async csv reader."""
    async for line in aiterable:
        yield [field.strip() for field in line.split(',')]

async def make_batches(iterable, size):
    """Make batches of size from iterable. This would be equivalent to slices
    from 0 to size, then size to size * 2, etc, of a list of the iterable."""
    iterator = aiter(iterable)
    async for first in iterator:
        yield achain([first], aislice(iterator, size - 1))

def do_every(seconds, coro, *args, **kwargs):
    async def task():
        while True:
            await asyncio.sleep(seconds)
            await coro(*args, **kwargs)
    return asyncio.get_event_loop().create_task(task())
