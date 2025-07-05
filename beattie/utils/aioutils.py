import asyncio
from collections.abc import Awaitable
from typing import Any, Callable, TypeVar

import discord

T = TypeVar("T")


def do_every(
    seconds: int, coro: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
) -> asyncio.Task:
    async def task():
        while True:
            await coro(*args, **kwargs)
            await asyncio.sleep(seconds)

    return asyncio.create_task(task())


async def squash_unfindable(coro: Awaitable[T]) -> T | None:
    try:
        return await coro
    except (discord.Forbidden, discord.NotFound):
        return None


async def try_wait_for(
    proc: asyncio.subprocess.Process,
    in_bytes: bytes = None,
    *,
    timeout: float | None = 120,
    kill_timeout: float | None = 5,
) -> bytes:
    try:
        out, _err = await asyncio.wait_for(proc.communicate(in_bytes), timeout=timeout)
    except asyncio.TimeoutError:
        await gently_kill(proc, timeout=kill_timeout)
        raise
    else:
        return out


async def gently_kill(proc: asyncio.subprocess.Process, *, timeout: float | None):
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
