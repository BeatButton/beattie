import asyncio


def do_every(seconds, coro, *args, **kwargs):
    async def task():
        while True:
            await asyncio.sleep(seconds)
            await coro(*args, **kwargs)

    return asyncio.get_event_loop().create_task(task())
