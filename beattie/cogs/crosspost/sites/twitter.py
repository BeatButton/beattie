from __future__ import annotations

import json
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
IMAGE_EXPR = re.compile(r"https://pbs\.twimg\.com/media/([\w-]+)\.(\w+)")
VIDEO_EXPR = re.compile(r"https://video.twimg.com/tweet_video/([\w-]+)\.mp4")


class Twitter(Site):
    name = "twitter"
    pattern = re.compile(
        r"https?://(?:(?:www|mobile|m)\.)?"
        r"(?:(?:.x|zz)?tw[ix]tter|(?:fix(?:up|v))?x(?:cancel)?)(?:vx)?"
        r"\.com/[^\s/]+/status/(\d+)"
    )

    method: Literal["fxtwitter"] | Literal["vxtwitter"] = "fxtwitter"
    rewrite_cdn: bool = True

    def get_media(self, tweet: dict[str, Any]) -> list[dict[str, str]] | None:
        match self.method:
            case "fxtwitter":
                return tweet.get("media", {}).get("all")
            case "vxtwitter":
                return tweet.get("media_extended")

    async def handler(
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
        tweet_id: str,
    ):
        headers = {"referer": f"https://x.com/i/status/{tweet_id}"}
        api_link = f"https://api.{self.method}.com/status/{tweet_id}"

        async with self.cog.get(
            api_link,
        ) as resp:
            tweet = await resp.json()
        if self.method == "fxtwitter":
            tweet = tweet["tweet"]

        if not (media := self.get_media(tweet)):
            qkey = {"fxtwitter": "quote", "vxtwitter": "qrt"}[self.method]
            if quote := tweet.get(qkey):
                media = self.get_media(quote)
        else:
            quote = None

        if not media:
            return

        queue.link = f"https://twitter.com/i/status/{tweet_id}"

        match self.method:
            case "fxtwitter":
                queue.author = tweet["author"]["id"]
            case "vxtwitter":
                queue.author = tweet["user_name"]

        def rewrite_video(url: str) -> str:
            if self.rewrite_cdn and (m := VIDEO_EXPR.match(url)):
                (name,) = m.groups()
                url = (
                    "https://cdn.xcancel.com/pic/video.twimg.com%2Ftweet_video%2F"
                    f"{name}.mp4"
                )
            return url

        url: str
        for medium in media:
            url = medium["url"]
            match medium["type"]:
                case "photo" | "image":
                    try:
                        if self.rewrite_cdn and (m := IMAGE_EXPR.match(url)):
                            name, ext = m.groups()
                            url = (
                                f"https://cdn.xcancel.com/pic/orig/media%2F{name}.{ext}"
                            )
                        else:
                            url = f"{url}:orig"
                        async with self.cog.get(
                            url,
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
                    url = rewrite_video(url)
                    queue.push_file(url, filename=filename, postprocess=ffmpeg_gif_pp)
                case "video":
                    queue.push_file(rewrite_video(url))

        text: str | None = html_unescape(tweet["text"]) or None
        qtext: str | None = html_unescape(quote["text"]) if quote else None
        match text, qtext:
            case None, None:
                pass
            case (txt, None) | (None, txt):
                queue.push_text(txt)
            case _:
                assert quote is not None
                match self.method:
                    case "fxtwitter":
                        qname = quote["author"]["screen_name"]
                    case "vxtwitter":
                        qname = quote["user_screen_name"]
                queue.push_text(
                    f"\N{BRAILLE PATTERN BLANK}↳ @{qname} — *{qtext}*", escape=False
                )
                queue.push_text(text)
