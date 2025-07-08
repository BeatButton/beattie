# ruff: noqa: S105, S324

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from hashlib import md5
from typing import TYPE_CHECKING

from lxml import html

from discord.ext.commands import Cooldown

from beattie.utils.aioutils import adump, aload

from ..postprocess import ugoira_pp
from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


CONFIG = "config/crosspost/pixiv.toml"


class Pixiv(Site):
    name = "pixiv"
    pattern = re.compile(
        r"https?://(?:www\.)?ph?ixiv\.net/(?:(?:en/)?artworks/|"
        r"member_illust\.php\?(?:\w+=\w+&?)*illust_id=|i/)(\d+)",
    )
    headers: dict[str, str]
    cooldown = Cooldown(10, 60)

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        self.headers = {
            "App-OS": "android",
            "App-OS-Version": "4.4.2",
            "App-Version": "5.0.145",
            "User-Agent": "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)",
        }
        self.logger = logging.getLogger(__name__)

    async def load(self):
        if self.cog.bot.extra.get("pixiv_login_task") is None:
            self.cog.bot.extra["pixiv_login_task"] = asyncio.create_task(
                self.login_loop(),
            )

        if headers := self.cog.bot.extra.get("pixiv_headers"):
            self.headers = headers
        else:
            self.cog.bot.extra["pixiv_headers"] = self.headers

    async def login_loop(self):
        url = "https://oauth.secure.pixiv.net/auth/token"
        while True:
            login = await aload(CONFIG)

            data = {
                "get_secure_url": 1,
                "client_id": "MOBrBDS8blbauoSck0ZfDbtuzpyT",
                "client_secret": "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj",
            }

            data["grant_type"] = "refresh_token"
            data["refresh_token"] = login["refresh_token"]

            hash_secret = (
                "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
            )

            now = datetime.now().isoformat()  # noqa: DTZ005
            headers = {
                "X-Client-Time": now,
                "X-Client-Hash": md5((now + hash_secret).encode("utf-8")).hexdigest(),
            }

            while True:
                wait = 1
                try:
                    async with self.cog.get(
                        url,
                        method="POST",
                        data=data,
                        headers=headers,
                    ) as resp:
                        res = resp.json()["response"]
                except Exception:
                    message = "An error occurred in the pixiv login loop"
                    self.logger.exception(message)
                    await asyncio.sleep(wait)
                    wait *= 2
                else:
                    break

            self.headers["Authorization"] = f'Bearer {res["access_token"]}'
            login["refresh_token"] = res["refresh_token"]

            await adump(CONFIG, login)
            await asyncio.sleep(res["expires_in"])

    async def handler(
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
        illust_id: str,
    ):
        params = {"illust_id": illust_id}
        url = "https://app-api.pixiv.net/v1/illust/detail"
        async with ctx.cog.get(url, params=params, headers=self.headers) as resp:
            res = resp.json()

        res = res["illust"]

        queue.author = res["user"]["id"]

        headers = {
            **self.headers,
            "referer": f"https://www.pixiv.net/en/artworks/{illust_id}",
        }

        queue.link = f"https://www.pixiv.net/en/artworks/{illust_id}"

        if single := res["meta_single_page"]:
            url = single["original_image_url"]

            if "ugoira" in url:
                queue.push_file(
                    url,
                    postprocess=ugoira_pp,
                    headers=headers,
                    pp_extra=illust_id,
                    can_link=False,
                )
            else:
                queue.push_fallback(url, res["image_urls"]["large"], headers=headers)
        elif multi := res["meta_pages"]:
            for page in multi:
                queue.push_fallback(
                    page["image_urls"]["original"],
                    page["image_urls"]["large"],
                    headers=headers,
                )
        else:
            msg = "illust had no pages"
            raise RuntimeError(msg)

        queue.push_text(res["title"], bold=True)
        if caption := res.get("caption"):
            caption = re.sub(r"<br ?/?>", "\n", caption)
            root = html.document_fromstring(caption, self.cog.parser)
            text = root.text_content()
            queue.push_text(text)
