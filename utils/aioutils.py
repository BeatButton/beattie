import asyncio
from typing import Any, Callable, Awaitable


def do_every(
    seconds: int, coro: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
) -> asyncio.Task:
    async def task() -> None:
        while True:
            await asyncio.sleep(seconds)
            await coro(*args, **kwargs)

    return asyncio.get_event_loop().create_task(task())
