from __future__ import annotations

import logging
import re
import urllib.parse as urlparse
from typing import TYPE_CHECKING

import aiohttp
from lxml import html
import toml

from beattie.utils.exceptions import ResponseError

from ..postprocess import ffmpeg_gif_pp
from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


API_FMT = "https://{}/api/v1/statuses/{}"


class Mastodon(Site):
    name = "mastodon"
    pattern = re.compile(r"(https?://([^\s/]+)/(?:\S+/)+([\w-]+))(?:[\s>/]|$)")

    auth: dict[str, dict[str, str]]

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        self.logger = logging.getLogger(__name__)
        with open("config/crosspost/mastodon.toml") as fp:
            self.auth = toml.load(fp)

    async def handler(
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
        link: str,
        site: str,
        post_id: str,
    ):
        info = self.cog.tldextract(link)
        domain = f"{info.domain}.{info.suffix}"
        if domain in GLOB_SITE_EXCLUDE:
            return False

        if auth := self.auth.get(site):
            headers = {"Authorization": f"Bearer {auth['token']}"}
        else:
            headers = {}

        api_url = API_FMT.format(site, post_id)
        try:
            async with self.cog.get(
                api_url, headers=headers, use_default_headers=False
            ) as resp:
                post = await resp.json()
        except (ResponseError, aiohttp.ClientError):
            self.logger.info(f"not a mastodon instance: {domain}")
            return False
        if not (images := post.get("media_attachments")):
            return False

        queue.author = post["account"]["url"]

        real_url = post["url"]
        queue.link = real_url
        if real_url.casefold() != link.casefold():
            queue.push_text(real_url)

        for image in images:
            urls = [url for url in [image["remote_url"], image["url"]] if url]

            for idx, url in enumerate(urls):
                if not urlparse.urlparse(url).netloc:
                    netloc = urlparse.urlparse(str(resp.url)).netloc
                    urls[idx] = f"https://{netloc}/{url.lstrip('/')}"
            if image.get("type") == "gifv":
                filename = (
                    f"{str(resp.url).rpartition('/')[2].removesuffix('.mp4')}.gif"
                )
                queue.push_file(*urls, filename=filename, postprocess=ffmpeg_gif_pp)
            else:
                queue.push_file(*urls)

        if content := post["content"]:
            if cw := post.get("spoiler_text"):
                queue.push_text(cw)

            fragments = html.fragments_fromstring(
                re.sub(r"<br ?/?>", "\n", content), parser=self.cog.parser
            )
            text = "\n".join(
                f if isinstance(f, str) else f.text_content() for f in fragments
            )
            queue.push_text(f">>> {text}")


GLOB_SITE_EXCLUDE = {
    "aiptcomics.com",
    "archiveofourown.org",
    "bad-dragon.com",
    "booth.pm",
    "bsky.app",
    "crepu.net",
    "deadline.com",
    "derpicdn.net",
    "discord.com",
    "discord.gg",
    "discordapp.com",
    "discordapp.net",
    "e621.net",
    "exhentai.org",
    "fanbox.cc",
    "fixupx.com",
    "fixvx.com",
    "forbes.com",
    "furaffinity.net",
    "fxtwitter.com",
    "gelbooru.com",
    "giphy.com",
    "hailuoai.com",
    "hiccears.com",
    "hollywoodreporter.com",
    "imgur.com",
    "inkbunny.net",
    "instagram.com",
    "itch.io",
    "iwastesomuchtime.com",
    "misskey.io",
    "nhentai.net",
    "nifty.org",
    "penny-arcade.com",
    "pixiv.net",
    "pomf.tv",
    "reddit.com",
    "rule34.xxx",
    "steampowered.com",
    "sxtwitter.com",
    "tenor.com",
    "threads.net",
    "tumblr.com",
    "twitter.com",
    "twittervx.com",
    "twxtter.com",
    "variety.com",
    "vxtwitter.com",
    "x.com",
    "xcancel.com",
    "xcancel.net",
    "y-gallery.net",
    "youtu.be",
    "youtube.com",
    "zztwitter.com",
}
