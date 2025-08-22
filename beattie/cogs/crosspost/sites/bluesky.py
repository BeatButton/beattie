from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict

from discord.utils import find

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

    class PlcService(TypedDict):
        type: str
        serviceEndpoint: str

    class PlcDirectory(TypedDict):
        service: list[PlcService]

    class ProfileResponse(TypedDict):
        handle: str

    class Record(TypedDict):
        cid: str
        uri: str

    Ref = TypedDict("Ref", {"$link": str})

    class Video(TypedDict):
        ref: Ref

    class Image(TypedDict):
        ref: Ref

    class ImageContainer(TypedDict):
        image: Image

    ImagesEmbed = TypedDict(
        "ImagesEmbed",
        {
            "$type": Literal["app.bsky.embed.images"],
            "images": list[ImageContainer],
        },
    )

    ExternalMedia = TypedDict(
        "ExternalMedia",
        {
            "$type": Literal["external"],
        },
    )

    VideoMedia = TypedDict(
        "VideoMedia",
        {
            "$type": Literal["video"],
            "video": Video,
        },
    )

    Media = ExternalMedia | VideoMedia | ImagesEmbed

    RecordEmbed = TypedDict(
        "RecordEmbed",
        {
            "$type": Literal["app.bsky.embed.record"],
            "record": Record,
        },
    )

    VideoEmbed = TypedDict(
        "VideoEmbed",
        {
            "$type": Literal["app.bsky.embed.video"],
            "video": Video,
        },
    )

    RecordWithMediaEmbed = TypedDict(
        "RecordWithMediaEmbed",
        {
            "$type": Literal["app.bsky.embed.recordWithMedia"],
            "media": Media,
            "record": Record,
        },
    )

    Embed = RecordEmbed | ImagesEmbed | VideoEmbed | RecordWithMediaEmbed

    Post = TypedDict(
        "Post",
        {
            "text": str,
            "$type": str,
            "embed": NotRequired[Embed],
        },
    )

    class PostResponse(TypedDict):
        uri: str
        value: Post


POST_FMT = (
    "https://bsky.social/xrpc/com.atproto.repo.getRecord"
    "?repo={}&collection=app.bsky.feed.post&rkey={}"
)
PROFILE_FMT = "https://{}/xrpc/com.atproto.repo.describeRepo?repo={}"


class Bluesky(Site):
    name = "bsky"
    pattern = re.compile(
        r"(?:https://fed.brid.gy/r/)?https?://(?:(?:c|[fv]x)?"
        r"[bx]s[ky]yx?\.app|deer\.social)/profile/([^/]+)/post/([^\s/]+)",
    )

    async def handler(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        repo: str,
        rkey: str,
    ):
        xrpc_url = POST_FMT.format(repo, rkey)
        async with self.cog.get(xrpc_url) as resp:
            data: PostResponse = resp.json()

        post = data["value"]
        text = post["text"] or None

        embed = post.get("embed")
        if embed is None:
            return

        qtext = None
        qname = None
        if embed["$type"] == "app.bsky.embed.record":
            _, _, did, _, qrkey = embed["record"]["uri"].split("/")
            xrpc_url = POST_FMT.format(did, qrkey)
            async with self.cog.get(xrpc_url) as resp:
                data: PostResponse = resp.json()

            post = data["value"]
            qtext = post["text"]
            embed = post.get("embed")
            if embed is None:
                return

            pds = await self.get_pds(did)
            async with self.cog.get(PROFILE_FMT.format(pds, did)) as resp:
                pdata: ProfileResponse = resp.json()
            qname = pdata["handle"]

        images = []
        video = None
        match embed["$type"]:
            case "app.bsky.embed.images":
                images = embed["images"]
            case "app.bsky.embed.video":
                video = embed["video"]
            case "app.bsky.embed.recordWithMedia":
                media = embed["media"]
                match media["$type"]:
                    case "video":
                        video = media["video"]
                    case "app.bsky.embed.images":
                        images = media["images"]

        if not (images or video):
            return

        did = data["uri"].removeprefix("at://").partition("/")[0]

        queue.author = repo
        queue.link = f"https://bsky.app/profile/{repo}/post/{rkey}"

        if video:
            cid = video["ref"]["$link"]
            pds = await self.get_pds(did)
            url = f"{pds}/xrpc/com.atproto.sync.getBlob?did={did}&cid={cid}"
            filename = f"{cid}.mp4"
            queue.push_file(
                url,
                filename=filename,
            )

        for image in images:
            image = image["image"]
            image_id = image["ref"]["$link"]
            url = f"https://cdn.bsky.app/img/feed_fullsize/plain/{did}/{image_id}@jpeg"
            filename = f"{image_id}.jpeg"
            queue.push_file(url, filename=filename)

        match text, qtext:
            case None, None:
                pass
            case (txt, None) | (None, txt):
                queue.push_text(txt)
            case _:
                if qtext:
                    qtext = f" — *{qtext}*"
                queue.push_text(
                    f"\N{BRAILLE PATTERN BLANK}↳ @{qname}{qtext}",
                    escape=False,
                )
                queue.push_text(text)

    async def get_pds(self, did: str) -> str:
        async with self.cog.get(f"https://plc.directory/{did}") as resp:
            info: PlcDirectory = resp.json()
        service = find(
            lambda svc: svc["type"] == "AtprotoPersonalDataServer",
            info["service"],
        )
        if service:
            pds = service["serviceEndpoint"]
        else:
            pds = "https://bsky.social"
        return pds
