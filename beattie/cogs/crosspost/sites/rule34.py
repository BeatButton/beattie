from __future__ import annotations

import re
from html import unescape as html_unescape
from typing import TYPE_CHECKING

from .booru import API_PARAMS, get_booru_post
from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


API_URL = "https://rule34.xxx/index.php"


class Rule34(Site):
    name = "r34"
    pattern = re.compile(r"https?://rule34\.xxx/index\.php\?(?:\w+=[^&]+&?){2,}")

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, link: str):
        params = {**API_PARAMS}
        post = await get_booru_post(self.cog, link, API_URL, params)
        if post is None:
            return
        queue.push_file(post["file_url"])
        if source := post.get("source"):
            queue.push_text(html_unescape(source), quote=False, force=True)
