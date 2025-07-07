from __future__ import annotations

import re
from html import unescape as html_unescape
from typing import TYPE_CHECKING, Any, Literal

from beattie.utils.exceptions import ResponseError

from ..postprocess import ffmpeg_gif_pp
from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


VIDEO_WIDTH = re.compile(r"vid/(\d+)x")

Method = Literal["fxtwitter", "vxtwitter"]


class Twitter(Site):
    name = "twitter"
    pattern = re.compile(
        r"https?://(?:(?:www|mobile|m)\.)?"
        r"(?:(?:.x|zz)?tw[ix]tter|(?:fix(?:up|v)|girlcock|stupidpenis)?x"
        r"(?:cancel)?)(?:vx)?\.com/[^\s/]+/status/(\d+)",
    )

    method: Method = "fxtwitter"

    def get_media(
        self,
        tweet: dict[str, Any],
        method: Method,
    ) -> list[dict[str, str]] | None:
        match method:
            case "fxtwitter":
                return tweet.get("media", {}).get("all")
            case "vxtwitter":
                return tweet.get("media_extended")

    async def handler(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        tweet_id: str,
    ):
        try:
            await self.with_method(queue, tweet_id, self.method)
        except Exception:
            fallback: Method
            match self.method:
                case "fxtwitter":
                    fallback = "vxtwitter"
                case "vxtwitter":
                    fallback = "fxtwitter"
            await self.with_method(queue, tweet_id, fallback)

    async def with_method(
        self,
        queue: FragmentQueue,
        tweet_id: str,
        method: Method,
    ):
        headers = {"referer": f"https://x.com/i/status/{tweet_id}"}
        api_link = f"https://api.{method}.com/status/{tweet_id}"

        async with self.cog.get(
            api_link,
        ) as resp:
            tweet = resp.json()
        if method == "fxtwitter":
            tweet = tweet["tweet"]

        if not (media := self.get_media(tweet, method)):
            qkey = {"fxtwitter": "quote", "vxtwitter": "qrt"}[method]
            if quote := tweet.get(qkey):
                media = self.get_media(quote, method)
        else:
            quote = None

        if not media:
            return

        queue.link = f"https://twitter.com/i/status/{tweet_id}"

        match method:
            case "fxtwitter":
                queue.author = tweet["author"]["id"]
            case "vxtwitter":
                queue.author = tweet["user_name"]

        url: str
        for medium in media:
            url = medium["url"]
            match medium["type"]:
                case "photo" | "image":
                    try:
                        async with self.cog.get(
                            f"{url}:orig",
                            method="HEAD",
                            headers=headers,
                        ) as resp:
                            url = str(resp.url)
                    except ResponseError as e:
                        if e.code != 404:
                            raise
                    queue.push_file(url)
                case "gif":
                    base = url.rpartition("/")[2].rpartition(".")[0]
                    filename = f"{base}.mp4"
                    queue.push_file(url, filename=filename, postprocess=ffmpeg_gif_pp)
                case "video":
                    queue.push_file(url)

        text: str | None = html_unescape(tweet["text"]) or None
        qtext: str | None = html_unescape(quote["text"]) if quote else None
        match text, qtext:
            case None, None:
                pass
            case (txt, None) | (None, txt):
                queue.push_text(txt)
            case _:
                assert quote is not None
                match method:
                    case "fxtwitter":
                        qname = quote["author"]["screen_name"]
                    case "vxtwitter":
                        qname = quote["user_screen_name"]
                if qtext:
                    qtext = f" — *{qtext}*"
                queue.push_text(
                    f"\N{BRAILLE PATTERN BLANK}↳ @{qname}{qtext}",
                    escape=False,
                )
                queue.push_text(text)
