from __future__ import annotations

import asyncio
import re
from asyncio import subprocess
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import TYPE_CHECKING, Any, Callable
from zipfile import ZipFile

from beattie.utils.aioutils import try_wait_for
from beattie.utils.etc import replace_ext

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from .fragment import FileFragment

    PP = Callable[[FileFragment], Awaitable[None]]


# postprocessors must set pp_bytes and pp_filename


async def ffmpeg_gif_pp(frag: FileFragment):
    with NamedTemporaryFile() as fp:
        fp.write(frag.file_bytes)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-f",
            "mp4",
            "-i",
            fp.name,
            "-filter_complex",
            "[0:v]palettegen[p];[0:v][p]paletteuse",
            "-f",
            "gif",
            "pipe:",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        try:
            stdout = await try_wait_for(proc)
        except asyncio.TimeoutError:
            pass
        else:
            if stdout:
                frag.pp_bytes = stdout
                frag.pp_filename = replace_ext(frag.filename, "gif")


async def ffmpeg_m3u8_to_mp4_pp(frag: FileFragment):
    with NamedTemporaryFile() as fp:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i",
            frag.urls[0],
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-f",
            "mp4",
            fp.name,
            "-y",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            await try_wait_for(proc)
        except asyncio.TimeoutError:
            pass
        else:
            frag.pp_filename = f"{frag.filename.rpartition(".")[0]}.mp4"
            fp.seek(0)
            frag.pp_bytes = fp.read()


def magick_pp(to: str) -> PP:
    async def inner(frag: FileFragment):
        ext = frag.filename.rpartition(".")[2]
        proc = await asyncio.create_subprocess_exec(
            "magick",
            f"{ext}:-",
            f"{to}:-",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        try:
            stdout = await try_wait_for(proc, frag.file_bytes)
        except asyncio.TimeoutError:
            pass
        else:
            frag.pp_bytes = stdout
            frag.pp_filename = f"{frag.filename.rpartition(".")[0]}.{to}"

    return inner


magick_gif_pp = magick_pp("gif")
magick_png_pp = magick_pp("png")


def write_durations(tempdir: Path, res: dict[str, Any]):
    with open(tempdir / "durations.txt", "w") as fp:
        for frame in res["frames"]:
            duration = int(frame["delay"]) / 1000
            fp.write(f"file '{frame['file']}'\nduration {duration}\n")


async def ugoira_pp(frag: FileFragment):
    illust_id: str = frag.pp_extra
    url = "https://app-api.pixiv.net/v1/ugoira/metadata"
    params = {"illust_id": illust_id}
    headers = frag.headers
    async with frag.cog.get(url, params=params, headers=headers) as resp:
        res = resp.json()["ugoira_metadata"]

    zip_url = res["zip_urls"]["medium"]
    zip_url = re.sub(r"ugoira\d+x\d+", "ugoira1920x1080", zip_url)

    headers = frag.headers or {}

    headers["referer"] = f"https://www.pixiv.net/en/artworks/{illust_id}"

    zip_bytes, _ = await frag.cog.save(zip_url, headers=headers)
    zfp = ZipFile(BytesIO(zip_bytes))

    with TemporaryDirectory() as td:
        tempdir = Path(td)
        zfp.extractall(tempdir)
        await asyncio.to_thread(write_durations, tempdir, res)

        proc = await subprocess.create_subprocess_exec(
            "ffmpeg",
            "-i",
            f"{tempdir}/%06d.jpg",
            "-vf",
            "palettegen",
            f"{tempdir}/palette.png",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await proc.wait()

        proc = await subprocess.create_subprocess_exec(
            "ffmpeg",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            f"{tempdir}/durations.txt",
            "-i",
            f"{tempdir}/palette.png",
            "-lavfi",
            "paletteuse",
            "-f",
            "gif",
            "pipe:1",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            stdout = await try_wait_for(proc)
        except asyncio.TimeoutError:
            pass
        else:
            frag.pp_bytes = stdout
            frag.pp_filename = f"{illust_id}.gif"
