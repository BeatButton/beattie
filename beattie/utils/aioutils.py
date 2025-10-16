from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, NoReturn, TypeVar

import toml

import discord

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from os import PathLike

T = TypeVar("T")


def do_every(
    seconds: int,
    coro: Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> asyncio.Task[NoReturn]:
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


async def aload(path: str | bytes | PathLike) -> dict[str, Any]:
    return await asyncio.to_thread(_load, path)


def _load(path: str | bytes | PathLike) -> dict[str, Any]:
    with open(path) as fp:
        return toml.load(fp)


async def adump(path: str | bytes | PathLike, data: dict[str, Any]):
    return await asyncio.to_thread(_dump, path, data)


def _dump(path: str | bytes | PathLike, data: dict[str, Any]):
    with open(path, "w") as fp:
        toml.dump(data, fp)
