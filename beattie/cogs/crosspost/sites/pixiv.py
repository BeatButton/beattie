from __future__ import annotations

from datetime import datetime
from hashlib import md5
from typing import TYPE_CHECKING
import asyncio
import logging
import re
from discord.ext.commands import Cooldown
import toml

from lxml import html

from .site import Site
from ..postprocess import ugoira_pp

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Pixiv(Site):
    name = "pixiv"
    pattern = re.compile(
        r"https?://(?:www\.)?ph?ixiv\.net/(?:(?:en/)?artworks/|"
        r"member_illust\.php\?(?:\w+=\w+&?)*illust_id=|i/)(\d+)"
    )
    headers: dict[str, str] = {
        "App-OS": "android",
        "App-OS-Version": "4.4.2",
        "App-Version": "5.0.145",
        "User-Agent": "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)",
    }
    cooldown = Cooldown(10, 60)

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        self.logger = logging.getLogger(__name__)

    async def load(self):
        if self.cog.bot.extra.get("pixiv_login_task") is None:
            self.cog.bot.extra["pixiv_login_task"] = asyncio.create_task(
                self.login_loop()
            )

    async def login_loop(self):
        url = "https://oauth.secure.pixiv.net/auth/token"
        while True:
            with open("config/crosspost/pixiv.toml") as fp:
                login = toml.load(fp)

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

            now = datetime.now().isoformat()
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
                        use_default_headers=False,
                        headers=headers,
                    ) as resp:
                        res = (await resp.json())["response"]
                except Exception:
                    message = "An error occurred in the pixiv login loop"
                    self.logger.exception(message)
                    await asyncio.sleep(wait)
                    wait *= 2
                else:
                    break

            self.headers["Authorization"] = f'Bearer {res["access_token"]}'
            login["refresh_token"] = res["refresh_token"]
            with open("config/crosspost/pixiv.toml", "w") as fp:
                toml.dump(login, fp)
            await asyncio.sleep(res["expires_in"])

    async def handler(
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
        illust_id: str,
    ):
        params = {"illust_id": illust_id}
        url = "https://app-api.pixiv.net/v1/illust/detail"
        async with ctx.cog.get(
            url, params=params, use_default_headers=False, headers=self.headers
        ) as resp:
            res = await resp.json()
        try:
            res = res["illust"]
        except KeyError:
            queue.push_text(
                "This feature works sometimes, but isn't working right now!"
                f"\nDebug info:\n{res.get('error')}",
                force=True,
            )
            return

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

        queue.push_text(res["title"], bold=True)
        if caption := res.get("caption"):
            caption = re.sub(r"<br ?/?>", "\n", caption)
            root = html.document_fromstring(caption, self.cog.parser)
            text = root.text_content()
            queue.push_text(text)
