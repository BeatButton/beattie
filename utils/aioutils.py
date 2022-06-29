import asyncio
from typing import Any, Awaitable, Callable, Optional, TypeVar

import discord

T = TypeVar("T")


def do_every(
    seconds: int, coro: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
) -> asyncio.Task:
    async def task() -> None:
        while True:
            await asyncio.sleep(seconds)
            await coro(*args, **kwargs)

    return asyncio.create_task(task())


async def squash_unfindable(coro: Awaitable[T]) -> Optional[T]:
    try:
        return await coro
    except (discord.Forbidden, discord.NotFound):
        return None
