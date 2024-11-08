from __future__ import annotations

import asyncio
import re
from asyncio import subprocess
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory, NamedTemporaryFile
from typing import TYPE_CHECKING, Any, Awaitable, Callable
from zipfile import ZipFile

from beattie.utils.aioutils import try_wait_for
from beattie.utils.etc import replace_ext

if TYPE_CHECKING:
    from .fragment import FileFragment

    PP = Callable[[FileFragment], Awaitable[None]]


# postprocessors must set pp_bytes and pp_filename


async def ffmpeg_gif_pp(frag: FileFragment):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i",
        frag.urls[0],
        "-i",
        frag.urls[0],
        "-filter_complex",
        "[0:v]palettegen[p];[1:v][p]paletteuse",
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
        frag.pp_filename = replace_ext(frag.filename, "gif")


async def ffmpeg_mp4_pp(frag: FileFragment):
    with NamedTemporaryFile() as fp:
        fp.name
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


def magick_pp(ext: str) -> PP:
    async def inner(frag: FileFragment):
        proc = await asyncio.create_subprocess_exec(
            "magick",
            frag.urls[0],
            f"{ext}:-",
            stderr=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
        )

        try:
            stdout = await try_wait_for(proc)
        except asyncio.TimeoutError:
            pass
        else:
            frag.pp_bytes = stdout
            frag.pp_filename = f"{frag.filename.rpartition(".")[0]}.{ext}"

    return inner


magick_gif_pp = magick_pp("gif")
magick_png_pp = magick_pp("png")


async def ugoira_pp(frag: FileFragment):
    illust_id: str = frag.pp_extra
    url = "https://app-api.pixiv.net/v1/ugoira/metadata"
    params = {"illust_id": illust_id}
    headers = frag.headers
    async with frag.cog.get(url, params=params, headers=headers) as resp:
        res = (await resp.json())["ugoira_metadata"]

    zip_url = res["zip_urls"]["medium"]
    zip_url = re.sub(r"ugoira\d+x\d+", "ugoira1920x1080", zip_url)

    headers = frag.headers or {}

    headers = {
        **headers,
        "referer": f"https://www.pixiv.net/en/artworks/{illust_id}",
    }

    zip_bytes, _ = await frag.cog.save(zip_url, headers=headers)
    zfp = ZipFile(BytesIO(zip_bytes))

    with TemporaryDirectory() as td:
        tempdir = Path(td)
        zfp.extractall(tempdir)
        with open(tempdir / "durations.txt", "w") as fp:
            for frame in res["frames"]:
                duration = int(frame["delay"]) / 1000
                fp.write(f"file '{frame['file']}'\nduration {duration}\n")

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
